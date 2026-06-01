from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import os

from orchestrated_loop.gate_cli import decision_for_hook_event
from orchestrated_loop.gate_ledger import EVENT_REQUESTED, GateLedger
from orchestrated_loop.gate_models import GateResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"


def _risky_event(tmp_path: Path, command: str = "git push") -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(tmp_path),
        "run_id": "run-test",
        "iteration": 1,
    }


def _run_cli(tmp_path: Path, payload, *, extra_args=None):
    """Invoke the CLI as a real subprocess feeding ``payload`` on stdin.

    PYTHONPATH=src is set so the subprocess can import the package without
    relying on the editable install being present (robust both ways).
    """
    args = [sys.executable, "-m", "orchestrated_loop.gate_cli", "--workspace", str(tmp_path)]
    if extra_args:
        args.extend(extra_args)
    env = {"PYTHONPATH": str(SRC)}
    full_env = {**os.environ, **env}
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        args,
        input=stdin,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=str(PROJECT_ROOT),
    )
    return proc


def _decision_from_proc(proc) -> dict:
    """Unwrap the PreToolUse decision from the CLI's stdout.

    Claude Code expects the decision under a ``hookSpecificOutput`` envelope
    (hookEventName=PreToolUse). The inner dict carries permissionDecision /
    permissionDecisionReason — the same flat shape decision_for_hook_event
    returns — so existing assertions stay unchanged via this unwrap."""
    raw = json.loads(proc.stdout)
    assert raw["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    return raw["hookSpecificOutput"]


def test_main_emits_hookspecificoutput_envelope(tmp_path):
    """Phase 5: Claude Code expects the decision wrapped in hookSpecificOutput
    with hookEventName=PreToolUse — not the flat dict. The flat dict stays the
    return of decision_for_hook_event; only main()'s stdout is wrapped."""
    proc = _run_cli(tmp_path, _risky_event(tmp_path))
    assert proc.returncode == 0, proc.stderr
    raw = json.loads(proc.stdout)
    assert "hookSpecificOutput" in raw
    inner = raw["hookSpecificOutput"]
    assert inner["hookEventName"] == "PreToolUse"
    assert inner["permissionDecision"] == "deny"
    assert "permissionDecisionReason" in inner


def test_blocks_first_risky_tool(tmp_path):
    proc = _run_cli(tmp_path, _risky_event(tmp_path))
    assert proc.returncode == 0, proc.stderr
    decision = _decision_from_proc(proc)
    assert decision["permissionDecision"] == "deny"
    assert "gate" in decision["permissionDecisionReason"].lower()
    assert (tmp_path / "state" / "GATE_LEDGER.jsonl").exists()


def test_allows_non_risky(tmp_path):
    event = {"tool_name": "Read", "tool_input": {"file_path": "x.py"}, "cwd": str(tmp_path)}
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "allow"
    assert decision["permissionDecisionReason"] == "not gated"
    assert not (tmp_path / "state" / "GATE_LEDGER.jsonl").exists()


_ANTHROPIC_SECRET = "sk-ant-" + "A1b2C3d4E5f6G7h8I9j0"


def test_secret_in_risky_tool_denied_without_ledger(tmp_path):
    """secret-sweep is a PURE LOCAL policy: a secret-bearing input is denied
    immediately, with no gate request and no B roundtrip (no ledger write)."""
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
    }
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"
    assert "secret" in decision["permissionDecisionReason"].lower()
    assert "anthropic api key" in decision["permissionDecisionReason"].lower()
    # No ledger: secret-sweep never requests a review.
    assert not (tmp_path / "state" / "GATE_LEDGER.jsonl").exists()


def test_secret_in_non_risky_tool_also_denied(tmp_path):
    """'Ganz vorne, alle Tools': secret-sweep runs BEFORE is_risky, so even a
    normally non-gated tool (Read) is denied if it carries a secret."""
    event = {
        "tool_name": "Read",
        "tool_input": {"content": f"key = {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
    }
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"
    assert "secret" in decision["permissionDecisionReason"].lower()
    assert not (tmp_path / "state" / "GATE_LEDGER.jsonl").exists()


def test_secret_ignores_global_shadow_and_denies(tmp_path, monkeypatch):
    """secret-sweep is a LOCAL enforce policy with its own switch. The global
    shadow (ORCH_GATE_MODE / --shadow), which softens the *repo-write* gate, must
    NOT soften secret-sweep: a secret is still denied hard. This is the whole
    point of splitting the two policy classes — secret-sweep stays enforce even
    while the review-needing gate runs in shadow during rollout."""
    monkeypatch.setenv("ORCH_GATE_MODE", "shadow")
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
    }
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"].lower()
    assert "secret" in reason
    # No ledger: secret-sweep never requests a review, enforce or not.
    assert not (tmp_path / "state" / "GATE_LEDGER.jsonl").exists()


def test_secret_local_policy_shadow_logs_but_allows(tmp_path):
    """secret-sweep CAN be softened, but only via its OWN switch
    (local_policy='shadow'), not via the global repo-write shadow. Used for a
    log-only rollout before flipping local policies to enforce."""
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
    }
    decision = decision_for_hook_event(event, tmp_path, local_policy="shadow")
    assert decision["permissionDecision"] == "allow"
    reason = decision["permissionDecisionReason"].lower()
    assert "shadow" in reason and "secret" in reason


def test_local_policy_enforce_is_default(tmp_path):
    """Default local_policy is enforce: a secret is denied even with no flags
    and no env set."""
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
    }
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"
    assert "secret" in decision["permissionDecisionReason"].lower()


def test_repo_write_gate_still_shadow_while_secret_enforces(tmp_path):
    """The two switches are independent: with the global shadow on (repo-write
    gate softened) a RISKY-but-clean action is allowed (would-deny logged), while
    a SECRET action under the same call is still denied hard."""
    clean = {
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
        "cwd": str(tmp_path),
        "_shadow_flag": True,
    }
    clean_decision = decision_for_hook_event(clean, tmp_path)
    assert clean_decision["permissionDecision"] == "allow"
    assert "shadow" in clean_decision["permissionDecisionReason"].lower()

    secret = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
        "_shadow_flag": True,
    }
    secret_decision = decision_for_hook_event(secret, tmp_path)
    assert secret_decision["permissionDecision"] == "deny"
    assert "secret" in secret_decision["permissionDecisionReason"].lower()


def test_clean_non_risky_still_not_gated(tmp_path):
    """Regression: a clean (secret-free) non-risky tool stays 'not gated'."""
    event = {"tool_name": "Read", "tool_input": {"file_path": "src/app.py"},
             "cwd": str(tmp_path)}
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "allow"
    assert decision["permissionDecisionReason"] == "not gated"


def test_idempotent_reuse(tmp_path):
    event = _risky_event(tmp_path)
    first = decision_for_hook_event(event, tmp_path)
    second = decision_for_hook_event(event, tmp_path)
    assert first["permissionDecision"] == "deny"
    assert second["permissionDecision"] == "deny"
    # Same gate id is referenced in both reasons (idempotent reuse).
    gate_ids = []
    for reason in (first["permissionDecisionReason"], second["permissionDecisionReason"]):
        for token in reason.split():
            if token.startswith("gate-"):
                gate_ids.append(token)
    assert len(gate_ids) == 2
    assert gate_ids[0] == gate_ids[1]
    # Only ONE gate_requested event in the ledger.
    ledger = GateLedger(tmp_path)
    requested = [e for e in ledger.events() if e.get("event") == EVENT_REQUESTED]
    assert len(requested) == 1


def _gate_id_from_reason(reason: str) -> str:
    for token in reason.split():
        if token.startswith("gate-"):
            return token
    raise AssertionError(f"no gate id in reason: {reason!r}")


def test_accepted_gate_allows(tmp_path):
    event = _risky_event(tmp_path)
    first = decision_for_hook_event(event, tmp_path)
    assert first["permissionDecision"] == "deny"
    gate_id = _gate_id_from_reason(first["permissionDecisionReason"])

    ledger = GateLedger(tmp_path)
    ledger.record_result(
        GateResult.accepted(gate_id, accepted_by="judge", evidence={"check": "ok"})
    )

    second = decision_for_hook_event(event, tmp_path)
    assert second["permissionDecision"] == "allow"
    assert gate_id in second["permissionDecisionReason"]
    assert "accepted" in second["permissionDecisionReason"]


def test_rejected_gate_denies(tmp_path):
    event = _risky_event(tmp_path)
    first = decision_for_hook_event(event, tmp_path)
    gate_id = _gate_id_from_reason(first["permissionDecisionReason"])

    ledger = GateLedger(tmp_path)
    ledger.record_result(
        GateResult.rejected(gate_id, rejected_by="judge", reason="unsafe push")
    )

    second = decision_for_hook_event(event, tmp_path)
    assert second["permissionDecision"] == "deny"
    assert gate_id in second["permissionDecisionReason"]
    assert "rejected" in second["permissionDecisionReason"]
    assert "unsafe push" in second["permissionDecisionReason"]


def test_shadow_mode_allows_but_logs(tmp_path, monkeypatch):
    # Shadow is operator-controlled (env / --shadow), NOT from the event payload
    # (see test_event_payload_cannot_enable_shadow). It allows but still logs.
    monkeypatch.setenv("ORCH_GATE_MODE", "shadow")
    decision = decision_for_hook_event(_risky_event(tmp_path), tmp_path)
    assert decision["permissionDecision"] == "allow"
    assert "shadow" in decision["permissionDecisionReason"].lower()
    # The gate was still logged.
    ledger = GateLedger(tmp_path)
    requested = [e for e in ledger.events() if e.get("event") == EVENT_REQUESTED]
    assert len(requested) == 1


def test_mcp_write_tool_is_risky(tmp_path):
    event = {
        "tool_name": "mcp__github__create_pull_request",
        "tool_input": {"title": "x"},
        "cwd": str(tmp_path),
    }
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"


def test_malformed_stdin_fails_open(tmp_path):
    proc = _run_cli(tmp_path, "{bad json")
    assert proc.returncode == 0, proc.stderr
    decision = _decision_from_proc(proc)
    assert decision["permissionDecision"] == "allow"

    proc_empty = _run_cli(tmp_path, "")
    assert proc_empty.returncode == 0, proc_empty.stderr
    decision_empty = _decision_from_proc(proc_empty)
    assert decision_empty["permissionDecision"] == "allow"


def test_event_payload_cannot_enable_shadow(tmp_path):
    # MAJOR-1 (code-review): a gate_mode field in the UNTRUSTED hook event must
    # NOT disable the gate. Shadow is operator-only (env / --shadow). A risky
    # call carrying gate_mode=shadow must still be denied.
    event = _risky_event(tmp_path)
    event["gate_mode"] = "shadow"
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"
    assert "shadow" not in decision["permissionDecisionReason"].lower()


def test_env_shadow_still_works(tmp_path, monkeypatch):
    # The operator-controlled env var IS a valid shadow trigger.
    monkeypatch.setenv("ORCH_GATE_MODE", "shadow")
    decision = decision_for_hook_event(_risky_event(tmp_path), tmp_path)
    assert decision["permissionDecision"] == "allow"
    assert "shadow" in decision["permissionDecisionReason"].lower()


def test_cli_local_policy_shadow_flag_softens_secret(tmp_path):
    """--local-policy shadow softens secret-sweep to log-only (subprocess/CLI
    level). Default (no flag) denies a secret hard."""
    secret_event = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
    }
    # Default: enforce -> deny.
    proc_default = _run_cli(tmp_path, secret_event)
    assert proc_default.returncode == 0, proc_default.stderr
    assert _decision_from_proc(proc_default)["permissionDecision"] == "deny"

    # --local-policy shadow -> allow, logged.
    proc_shadow = _run_cli(tmp_path, secret_event, extra_args=["--local-policy", "shadow"])
    assert proc_shadow.returncode == 0, proc_shadow.stderr
    decision = _decision_from_proc(proc_shadow)
    assert decision["permissionDecision"] == "allow"
    assert "secret" in decision["permissionDecisionReason"].lower()


def test_event_payload_cannot_soften_local_policy(tmp_path):
    """Mirror of test_event_payload_cannot_enable_shadow: an UNTRUSTED event must
    not soften secret-sweep. A local_policy field in the payload is ignored; the
    secret is still denied."""
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": f"echo {_ANTHROPIC_SECRET}"},
        "cwd": str(tmp_path),
        "local_policy": "shadow",
    }
    decision = decision_for_hook_event(event, tmp_path)
    assert decision["permissionDecision"] == "deny"
    assert "secret" in decision["permissionDecisionReason"].lower()


def test_expired_gate_is_re_requested(tmp_path):
    # MINOR-2 (code-review): an expired gate must trigger a fresh request, not
    # stay stuck. Expect a new gate id and two gate_requested events.
    event = _risky_event(tmp_path)
    first = decision_for_hook_event(event, tmp_path)
    gate_id = _gate_id_from_reason(first["permissionDecisionReason"])

    ledger = GateLedger(tmp_path)
    ledger.record_result(GateResult.expired(gate_id, reason="stale"))

    second = decision_for_hook_event(event, tmp_path)
    assert second["permissionDecision"] == "deny"
    new_gate_id = _gate_id_from_reason(second["permissionDecisionReason"])
    assert new_gate_id != gate_id
    requested = [e for e in ledger.events() if e.get("event") == EVENT_REQUESTED]
    assert len(requested) == 2
