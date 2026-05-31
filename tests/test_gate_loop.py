from __future__ import annotations

import json
from pathlib import Path

from orchestrated_loop import orchestrate
from orchestrated_loop.dco_import import build_dco_import_package
from orchestrated_loop.loop import build_parser
from orchestrated_loop.run_status import build_run_status


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- CLI wiring (GT4: own arg, not in the --goal exclusive group) -----------


def test_gate_mode_arg_defaults_off():
    args = build_parser().parse_args([])
    assert args.gate_mode == "off"


def test_gate_mode_arg_accepts_modes():
    for mode in ("off", "shadow", "enforce"):
        args = build_parser().parse_args(["--gate-mode", mode])
        assert args.gate_mode == mode


def test_gate_mode_not_in_goal_exclusive_group():
    """GT4: --gate-mode must coexist with --goal (own arg, not mutually exclusive)."""
    args = build_parser().parse_args(["--goal", "do X", "--gate-mode", "enforce"])
    assert args.goal == "do X"
    assert args.gate_mode == "enforce"


# --- off mode: no gate artifacts --------------------------------------------


def test_gate_mode_off_writes_no_ledger(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="off")
    assert not (tmp_path / "state" / "GATE_LEDGER.jsonl").exists()


def test_gate_mode_off_handoff_not_gate_required(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="off")
    handoff = _read_json(tmp_path / "state" / "DCO_HANDOFF.json")
    assert handoff["safety"].get("gate_required", False) is False


# --- shadow/enforce: gate artifacts present ---------------------------------


def test_enforce_mode_ensures_ledger_and_artifact_index(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="enforce")
    ledger = tmp_path / "state" / "GATE_LEDGER.jsonl"
    assert ledger.exists()
    artifacts = _read_json(tmp_path / "state" / "ARTIFACTS.json")["artifacts"]
    paths = {a["path"] for a in artifacts}
    assert "state/GATE_LEDGER.jsonl" in paths


def test_enforce_mode_sets_handoff_safety_fields(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="enforce")
    handoff = _read_json(tmp_path / "state" / "DCO_HANDOFF.json")
    assert handoff["safety"]["gate_required"] is True
    assert handoff["safety"]["gate_mode"] == "enforce"


def test_shadow_mode_sets_handoff_safety_fields(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="shadow")
    handoff = _read_json(tmp_path / "state" / "DCO_HANDOFF.json")
    assert handoff["safety"]["gate_required"] is True
    assert handoff["safety"]["gate_mode"] == "shadow"


def test_run_status_reports_gate_section(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="enforce")
    status = build_run_status(tmp_path)
    assert "gate" in status
    assert status["gate"]["mode"] == "enforce"
    assert status["gate"]["open_count"] == 0


def test_run_status_gate_off_when_disabled(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85, gate_mode="off")
    status = build_run_status(tmp_path)
    assert status["gate"]["mode"] == "off"
    assert status["gate"]["open_count"] == 0


# --- dco_import: gate_policy only when gate_required -------------------------


def test_dco_import_carries_gate_policy_when_enabled(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99, gate_mode="enforce")
    package = build_dco_import_package(tmp_path)
    assert package["safety"]["gate_policy"]["gate_required"] is True
    assert package["safety"]["gate_policy"]["gate_mode"] == "enforce"


def test_dco_import_omits_gate_policy_when_off(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99, gate_mode="off")
    package = build_dco_import_package(tmp_path)
    assert "gate_policy" not in package["safety"]
