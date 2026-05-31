from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from orchestrated_loop.gate_ledger import EVENT_REQUESTED, GateLedger
from orchestrated_loop.gate_models import GateRequest

# Iteration 1 risky-matcher: a repo-write policy. This is a DELIBERATELY MINIMAL
# Iteration-1 allowlist, NOT a complete mutation taxonomy. It gates the known
# first-party tools that mutate the working tree, plus ALL MCP tools (fail-CLOSED
# for mcp__*: an MCP tool has external side effects by definition, so gate it
# rather than maintain an ever-growing verb whitelist). Unknown non-MCP tools
# still pass through (fail-open) — acceptable for the walking skeleton, but the
# matcher is NOT a hard security boundary on its own; the ledger + enforce step
# downstream are. Backlog: tighten unknown-tool handling, secret-sweep policy.
RISKY_TOOL_NAMES = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"}
# Fail-closed for every MCP tool, not just a verb whitelist (write/create/...):
# mutating verbs like send/push/execute/commit/merge/publish would otherwise slip
# through. MCP tools cross a trust boundary, so all of them are gated.
RISKY_MCP_PATTERN = re.compile(r"^mcp__", re.IGNORECASE)

# Stage/policy constants for the repo-write gate. KNOWN_STAGES in gate_models
# only allows build/review/final_report/dco_import; repo writes are a "build"
# concern in Iteration 1.
GATE_STAGE = "build"
GATE_ACTION = "tool_use"
GATE_REQUIRES = ["dual_bridge_review_verdict", "repo_allowlist"]

ALLOW = "allow"
DENY = "deny"


def is_risky(tool_name: str) -> bool:
    """Return True if a tool should be gated under the repo-write policy."""
    if tool_name in RISKY_TOOL_NAMES:
        return True
    return bool(RISKY_MCP_PATTERN.match(tool_name))


def _decision(permission: str, reason: str) -> dict[str, str]:
    return {"permissionDecision": permission, "permissionDecisionReason": reason}


def _latest_resolved_gate(ledger: GateLedger, digest: str) -> dict[str, Any] | None:
    """Find the newest gate_requested event for ``digest`` (open or resolved).

    gate_ledger only exposes ``find_open_by_digest`` (which excludes resolved
    gates), so we walk the events ourselves to locate the most recent request
    matching the digest, then resolve its latest status via ``ledger.latest``.
    """
    newest_gate_id: str | None = None
    for event in ledger.events():
        if event.get("event") != EVENT_REQUESTED:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("tool_input_digest") == digest:
            gate_id = payload.get("gate_id")
            if isinstance(gate_id, str):
                newest_gate_id = gate_id
    return ledger.latest(newest_gate_id) if newest_gate_id else None


def decision_for_hook_event(event: dict, workspace: Path) -> dict:
    """Decide allow/deny for a Claude-Code PreToolUse hook event.

    Returns a dict shaped as a PreToolUse decision:
    ``{"permissionDecision": "allow"|"deny", "permissionDecisionReason": ...}``.

    Risky tools (repo-write policy) create or reuse a gate in the ledger and are
    denied until a reviewer records an accepted result. Non-risky tools pass
    through without touching the ledger. In shadow mode the gate is still
    recorded but the decision is always ``allow`` so a rollout never blocks.
    """
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Shadow mode is OPERATOR-controlled only (CLI --shadow sets _shadow_flag,
    # or the ORCH_GATE_MODE env var). It is deliberately NOT read from the hook
    # event payload: gate_mode in the event would let the very call being checked
    # disable its own gate — a bypass that has no place in a security tripwire.
    shadow = (
        os.environ.get("ORCH_GATE_MODE") == "shadow"
        or bool(event.get("_shadow_flag"))
    )

    if not is_risky(tool_name):
        return _decision(ALLOW, "not gated")

    workspace = Path(workspace)
    ledger = GateLedger(workspace)

    request = GateRequest.new(
        run_id=event.get("run_id") or "unknown",
        iteration=event.get("iteration", 0),
        stage=GATE_STAGE,
        action=GATE_ACTION,
        tool_name=tool_name,
        tool_input=tool_input,
        workspace=workspace,
        requires=GATE_REQUIRES,
    )
    digest = request.tool_input_digest

    # 1) An open (pending, unresolved) gate already exists for this input.
    open_gate = ledger.find_open_by_digest(digest)
    if open_gate is not None:
        gate_id = open_gate.get("gate_id")
        return _shadowed(
            shadow,
            DENY,
            f"gate {gate_id} requested — awaiting review",
        )

    # 2) No open gate, but a resolved one may exist for this input.
    resolved = _latest_resolved_gate(ledger, digest)
    if resolved is not None:
        status = resolved.get("status")
        gate_id = resolved.get("gate_id")
        if status == "accepted":
            return _shadowed(shadow, ALLOW, f"gate {gate_id} accepted")
        if status == "rejected":
            reason = resolved.get("reason") or ""
            return _shadowed(shadow, DENY, f"gate {gate_id} rejected: {reason}")
        # expired or unknown terminal state -> re-request below.

    # 3) First contact (or expired): record a new gate request and deny.
    ledger.record_request(request)
    return _shadowed(
        shadow,
        DENY,
        f"gate {request.gate_id} requested — awaiting review",
    )


def _shadowed(shadow: bool, permission: str, reason: str) -> dict[str, str]:
    """Apply shadow mode: log/decide as usual but always allow when shadowing."""
    if not shadow:
        return _decision(permission, reason)
    verb = "deny" if permission == DENY else "allow"
    return _decision(ALLOW, f"shadow: would {verb} — {reason}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude-Code PreToolUse gate hook for the dual-bridge architecture."
    )
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--shadow", action="store_true", help="Never block; log only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Fail-OPEN on a broken/empty stdin: the real enforcement lives in the
    # ledger + downstream enforce step, NOT in this fragile stdin parse. A
    # malformed hook event must never hard-block the user; it just passes
    # through with a clear reason.
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        event = None
    if not isinstance(event, dict):
        print(json.dumps(_decision(ALLOW, "no hook event")))
        return 0

    if args.shadow:
        event["_shadow_flag"] = True

    # Workspace resolution: --workspace -> event["cwd"] -> CWD.
    if args.workspace is not None:
        workspace = args.workspace
    elif event.get("cwd"):
        workspace = Path(event["cwd"])
    else:
        workspace = Path.cwd()

    decision = decision_for_hook_event(event, workspace)
    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
