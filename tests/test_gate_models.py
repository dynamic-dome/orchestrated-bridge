from __future__ import annotations

from pathlib import Path

import pytest

from orchestrated_loop.gate_models import GateRequest, GateResult, make_gate_id


def test_digest_rejects_uncanonicalisable_input(tmp_path):
    # MAJOR #1 (code-review): mixed-type/unorderable keys must fail-fast with a
    # clear ValueError from the gate path, NOT an opaque TypeError mid-lock.
    with pytest.raises(ValueError):
        GateRequest.new(
            run_id="run-1",
            iteration=1,
            stage="build",
            action="apply_changes",
            tool_name="write_file",
            tool_input={1: "a", "b": 2},
            workspace=tmp_path,
            requires=[],
        )


def test_gate_id_is_stable_shape():
    gate_id = make_gate_id()
    assert gate_id.startswith("gate-")
    assert len(gate_id) <= 64


def test_gate_request_requires_known_stage(tmp_path):
    request = GateRequest.new(
        run_id="run-1",
        iteration=1,
        stage="build",
        action="apply_changes",
        tool_name="write_file",
        tool_input={"path": "src/foo.py", "content": "x"},
        workspace=tmp_path,
        requires=["tests_pass"],
    )
    payload = request.to_dict()
    assert payload["status"] == "requested"
    assert payload["tool_input_digest"].startswith("sha256:")


def test_gate_request_rejects_unknown_stage(tmp_path):
    with pytest.raises(ValueError):
        GateRequest.new(
            run_id="run-1",
            iteration=1,
            stage="frobnicate",
            action="apply_changes",
            tool_name="write_file",
            tool_input={"path": "src/foo.py"},
            workspace=tmp_path,
            requires=[],
        )


def test_digest_is_canonical(tmp_path):
    request_a = GateRequest.new(
        run_id="run-1",
        iteration=1,
        stage="build",
        action="apply_changes",
        tool_name="write_file",
        tool_input={"a": 1, "b": 2},
        workspace=tmp_path,
        requires=[],
    )
    request_b = GateRequest.new(
        run_id="run-1",
        iteration=1,
        stage="build",
        action="apply_changes",
        tool_name="write_file",
        tool_input={"b": 2, "a": 1},
        workspace=tmp_path,
        requires=[],
    )
    assert request_a.tool_input_digest == request_b.tool_input_digest


def test_gate_result_accepted_requires_evidence():
    result = GateResult.accepted(
        gate_id="gate-1",
        accepted_by="judge",
        evidence={"check": "tests_pass", "result": "ok"},
    )
    payload = result.to_dict()
    assert payload["status"] == "accepted"
    assert payload["evidence"] == {"check": "tests_pass", "result": "ok"}
    assert payload["accepted_by"] == "judge"


def test_gate_result_rejected_carries_reason():
    result = GateResult.rejected(
        gate_id="gate-1",
        rejected_by="judge",
        reason="x",
        evidence={"check": "tests_pass", "result": "fail"},
    )
    payload = result.to_dict()
    assert payload["status"] == "rejected"
    assert payload["reason"] == "x"
    assert payload["rejected_by"] == "judge"


def test_gate_result_expired_status():
    result = GateResult.expired(gate_id="gate-1", reason="stale")
    payload = result.to_dict()
    assert payload["status"] == "expired"
    assert payload["reason"] == "stale"


def test_times_are_utc_z(tmp_path):
    request = GateRequest.new(
        run_id="run-1",
        iteration=1,
        stage="review",
        action="approve",
        tool_name="judge",
        tool_input={},
        workspace=tmp_path,
        requires=[],
    )
    payload = request.to_dict()
    assert payload["created_at"].endswith("Z")
    assert payload["expires_at"].endswith("Z")
