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
