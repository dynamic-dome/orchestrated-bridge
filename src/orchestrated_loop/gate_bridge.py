"""Bridge adapter: turn a GateRequest into a dual-bridge ``kind: review`` task
and collect the reviewer's verdict back from the bridge inbox.

This is the Phase-3 link between the gate (orchestrated-loop) and the
cross-device reviewer (Claude on Laptop B, over dual-bridge). It deliberately
does NOT import dual-bridge: that repo lives outside this package and ships no
installable module. Instead the (small, stable) file protocol is *mirrored*
here — task frontmatter shape, the strict task_id format, lane-aware paths, and
UTF-8-without-BOM writes.

Lane mechanics (GT2, verified against dual-bridge/scripts/handoff_poll.py:
``poll_once`` iterates ``receive_lanes()`` and ``_poll_lane(lane)`` reads
``lane_outbox(lane)`` / writes ``lane_inbox(lane)`` for the SAME lane):

    A (initiator) writes the gate task into  lane-A-to-B/outbox/
    B polls lane A-to-B, reviews, writes the result into lane-A-to-B/inbox/
    A collects the verdict from              lane-A-to-B/inbox/

So both the task and its result live on the single ``A-to-B`` lane. The
``lane-B-to-A`` lane is for B-initiated tasks and is irrelevant to the gate
(A always initiates).
"""
from __future__ import annotations

import re
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrated_loop.gate_models import GateRequest

# A-initiated gate tasks always travel the A-to-B lane.
GATE_LANE = "A-to-B"

# Mirror of dual-bridge bridge_common._TASK_ID_RE. The bridge poller hard-rejects
# any task_id that does not match this exact shape (path-traversal / branch-
# injection guard), quarantining the task into _errors/. A gate task with a
# malformed id would therefore be silently dropped — so we generate ids in the
# bridge's own make_task_id() shape and keep the regex here as a tripwire.
_TASK_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}-[0-9a-f]+-[0-9a-f]{4}$")

_id_counter = count()


def _make_task_id() -> str:
    """Sortable, collision-free id in the bridge's make_task_id() shape:
    ``YYYYMMDD-HHMMSS-<micros>-<seq>-<rand>``."""
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    seq = next(_id_counter)
    return f"{stamp}-{now.microsecond:06d}-{seq:x}-{uuid4().hex[:4]}"


def _now_iso() -> str:
    """Local wall-clock, second precision — matches the bridge's now_iso()."""
    return datetime.now().replace(microsecond=0).isoformat()


def _is_conflict_copy(name: str) -> bool:
    """Google-Drive conflict copies look like 'result-... (1).md'. Skip them."""
    return "(" in name and ")" in name


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal flat ``key: value`` frontmatter parser (mirrors the bridge's).
    Tolerant of a leading BOM; returns {} if no frontmatter block is present."""
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()
    return fm


def _build_document(frontmatter: dict[str, str], body: str) -> str:
    """Serialize a flat frontmatter dict + body (mirrors the bridge's)."""
    out = ["---"]
    for key, val in frontmatter.items():
        out.append(f"{key}: {val}" if val != "" else f"{key}:")
    out.append("---")
    out.append("")
    out.append(body.rstrip("\n"))
    out.append("")
    return "\n".join(out)


class BridgeGateClient:
    """Write gate-review tasks into the bridge and collect verdicts back.

    No dual-bridge import: the file protocol is mirrored. Lanes-only — the gate
    task always travels the A-to-B lane (the only lane an A-initiated task may
    use, and the only outbox the current poller scans). There is deliberately NO
    flat outbox/inbox fallback: it would be a dead drop the poller never reads.
    """

    def __init__(self, bridge_root: Path) -> None:
        self._root = Path(bridge_root)

    # --- path resolution (lanes-only) ---------------------------------------
    # NO flat outbox/inbox fallback. The CURRENT dual-bridge poller
    # (handoff_poll.py _poll_lane) scans ONLY lane-<lane>/outbox and writes ONLY
    # lane-<lane>/inbox — the Stage-2a lane split removed flat-dir handling.
    # Writing a gate task into a legacy flat outbox/ would be a DEAD DROP the
    # poller never reads: the hook + ledger would wait forever for a review that
    # never runs (Codex-Verifier MAJOR, 2026-05-31). So the gate always uses the
    # A-to-B lane, which is also the only lane an A-initiated task may travel.

    def _outbox(self) -> Path:
        return self._root / f"lane-{GATE_LANE}" / "outbox"

    def _inbox(self) -> Path:
        return self._root / f"lane-{GATE_LANE}" / "inbox"

    # --- task write ---------------------------------------------------------

    def write_gate_task(self, request: GateRequest) -> Path:
        """Write a ``kind: review`` task for ``request`` into the send-lane
        outbox and return the written path.

        The reviewer (Claude on B) must answer with a ``VERDICT: accepted`` /
        ``VERDICT: rejected`` marker line; the bridge's review path parses it
        fail-closed into the result frontmatter.
        """
        task_id = _make_task_id()
        # Defensive: never emit an id the bridge would quarantine.
        assert _TASK_ID_RE.match(task_id), f"generated invalid task_id {task_id!r}"

        frontmatter = {
            "created": _now_iso(),
            "schema_version": "2",
            "agent": "claude@laptop-a",
            "from": "claude@laptop-a",
            "to": "codex@laptop-b",
            "target_agent": "laptop-b-reviewer",
            "purpose": "handoff",
            "status": "open",
            "task_id": task_id,
            "kind": "review",
            "adapter": "claude",
            # No `repo`: the review path needs none (only codex/implement does).
            "base_branch": "main",
            "claimed_by": "",
            "claimed_at": "",
            # Gate-evidence fields — mirrored verbatim into the result by the
            # bridge's MIRROR_FIELDS (Phase 0, schliesst GT1).
            "gate_id": request.gate_id,
            "run_id": request.run_id,
            "stage": request.stage,
            "requires": ",".join(request.requires),
        }
        # The reviewer must SEE the concrete action — a digest-only task makes it
        # refuse to judge (correctly). action_summary carries the real command.
        action_summary = request.action_summary or f"{request.tool_name} (no details)"
        body = (
            "## Auftrag\n"
            "Adversarially review whether the following action is safe to allow. "
            "Judge THIS action only — do not look for any external gate framework; "
            "everything you need is right here.\n\n"
            f"ACTION TO REVIEW: {action_summary}\n\n"
            f"(context: run {request.run_id}, stage {request.stage}, "
            f"action {request.action}, gate {request.gate_id})\n\n"
            "Check for: destructive ops (rm -rf, DROP TABLE, force-push, writes "
            "outside the workspace), test-vs-production-DB risk, path/quoting "
            "traps, unauthorised outward effects (deploys, network, publishing).\n\n"
            "Reply with a one-paragraph judgement, then END with exactly one "
            "marker line — nothing after it:\n"
            "`VERDICT: accepted`  (safe to allow)\n"
            "`VERDICT: rejected`  (block it)\n"
            "If anything is unclear, answer `VERDICT: rejected` (fail-closed).\n\n"
            "## Akzeptanzkriterien\n"
            "- [ ] Result liegt im inbox/ mit demselben task_id und gate_id\n"
            "- [ ] Antwort endet mit einer VERDICT-Markerzeile\n\n"
            "## Ergebnis\n"
            "<wird vom Reviewer auf B gefüllt>\n"
        )

        outbox = self._outbox()
        outbox.mkdir(parents=True, exist_ok=True)
        out_path = outbox / f"task-{task_id}.md"
        # UTF-8 *without* BOM (global rule §10.7): a BOM corrupts the bridge's
        # flat frontmatter parser and downstream readers.
        out_path.write_text(
            _build_document(frontmatter, body), encoding="utf-8", newline="\n"
        )
        return out_path

    # --- result collection --------------------------------------------------

    def collect_result(self, gate_id: str) -> dict[str, Any] | None:
        """Return the verdict evidence for ``gate_id``, or None if no matching
        result is in the inbox yet.

        Matches on the mirrored ``gate_id`` in the result frontmatter (Phase 0),
        NOT on the bridge task_id — the gate owns gate_id, the bridge owns
        task_id, and one gate maps to exactly one review result.
        """
        inbox = self._inbox()
        if not inbox.exists():
            return None
        for path in sorted(inbox.glob("result-*.md")):
            if _is_conflict_copy(path.name):
                continue
            try:
                fm = _parse_frontmatter(path.read_text(encoding="utf-8-sig"))
            except OSError:
                continue
            if fm.get("gate_id") != gate_id:
                continue
            return {
                "gate_id": gate_id,
                "status": fm.get("status", ""),
                "verdict": fm.get("verdict", ""),
                "verdict_reason": fm.get("verdict_reason", ""),
                "lane": GATE_LANE,
                "result_path": path.as_posix(),
            }
        return None
