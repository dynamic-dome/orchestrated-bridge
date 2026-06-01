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
from orchestrated_loop.gate_secret_sweep import secret_sweep_violation

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


def _hook_envelope(decision: dict[str, str]) -> dict[str, Any]:
    """Wrap a flat decision into the Claude-Code PreToolUse stdout envelope.

    Claude Code reads a PreToolUse hook's permission decision from
    ``hookSpecificOutput`` (hookEventName=PreToolUse); the flat dict alone is
    NOT honoured by current versions. The flat shape stays the return of
    decision_for_hook_event (unit-tested directly); only main()'s stdout is
    wrapped here so the live hook actually blocks.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision["permissionDecision"],
            "permissionDecisionReason": decision["permissionDecisionReason"],
        }
    }


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


def decision_for_hook_event(
    event: dict, workspace: Path, local_policy: str = "enforce"
) -> dict:
    """Decide allow/deny for a Claude-Code PreToolUse hook event.

    Returns a dict shaped as a PreToolUse decision:
    ``{"permissionDecision": "allow"|"deny", "permissionDecisionReason": ...}``.

    Two INDEPENDENT policy classes with separate switches:

    * **Local policies** (secret-sweep; later db-safety/deploy-safety) are
      decidable immediately, with no reviewer. They obey ``local_policy``
      (``"enforce"`` by default → hard deny; ``"shadow"`` → log-only). They do
      NOT obey the global repo-write ``shadow`` flag — that would be a footgun:
      a secret leak must stay blocked even while the review gate is softened for
      rollout.
    * **Review policy** (the repo-write gate) needs a cross-device reviewer to
      resolve, so it cannot safely enforce on its own yet. It obeys the global
      ``shadow`` flag (CLI ``--shadow`` / ``ORCH_GATE_MODE``): risky tools create
      or reuse a gate and are denied until a reviewer records an accepted result;
      in shadow the gate is still recorded but the decision is always ``allow``
      so a rollout never blocks (and never self-DoSes without a live reviewer).

    Non-risky, secret-free tools pass through untouched.
    """
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Both switches are OPERATOR-controlled only (CLI flags / env). They are
    # deliberately NOT read from the hook event payload: a field in the event
    # would let the very call being checked soften its own gate — a bypass that
    # has no place in a security tripwire (see test_event_payload_cannot_*).
    shadow = (
        os.environ.get("ORCH_GATE_MODE") == "shadow"
        or bool(event.get("_shadow_flag"))
    )
    local_shadow = local_policy == "shadow"

    # secret-sweep: a PURE LOCAL policy that runs FIRST, before is_risky, for
    # EVERY tool. A tool input that would write or expose a secret is denied
    # immediately — no gate request, no ledger, no B roundtrip (a secret leak is
    # never a "wait for review" case). It runs ahead of is_risky on purpose
    # (defense-in-depth): a secret must be caught regardless of whether the
    # repo-write matcher happens to also fire. It obeys its OWN local_policy
    # switch (default enforce), NOT the global repo-write shadow flag.
    secret = secret_sweep_violation(tool_input)
    if secret is not None:
        return _shadowed(local_shadow, DENY, f"secret: {secret}")

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
    parser.add_argument(
        "--shadow",
        action="store_true",
        help="Repo-write (review) gate: never block, log only. Does NOT affect secret-sweep.",
    )
    parser.add_argument(
        "--local-policy",
        choices=("enforce", "shadow"),
        default="enforce",
        help="Local policies (secret-sweep): 'enforce' (default) blocks hard; "
        "'shadow' logs only. Independent of --shadow.",
    )
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
        print(json.dumps(_hook_envelope(_decision(ALLOW, "no hook event"))))
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

    decision = decision_for_hook_event(event, workspace, local_policy=args.local_policy)
    print(json.dumps(_hook_envelope(decision)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
