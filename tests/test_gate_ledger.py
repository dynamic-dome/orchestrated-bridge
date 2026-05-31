from __future__ import annotations

from orchestrated_loop.gate_ledger import GateLedger
from orchestrated_loop.gate_models import GateRequest, GateResult


def _make_request(workspace):
    return GateRequest.new(
        run_id="run-1",
        iteration=1,
        stage="build",
        action="apply_changes",
        tool_name="write_file",
        tool_input={"path": "src/foo.py", "content": "x"},
        workspace=workspace,
        requires=["tests_pass"],
    )


def test_path_is_under_state(tmp_path):
    ledger = GateLedger(tmp_path)
    assert ledger.path == tmp_path / "state" / "GATE_LEDGER.jsonl"


def test_ledger_appends_and_reads_latest(tmp_path):
    ledger = GateLedger(tmp_path)
    request = _make_request(tmp_path)
    ledger.record_request(request)

    assert ledger.latest(request.gate_id)["status"] == "requested"

    result = GateResult.accepted(
        gate_id=request.gate_id,
        accepted_by="judge",
        evidence={"check": "tests_pass", "result": "ok"},
    )
    ledger.record_result(result)

    assert ledger.latest(request.gate_id)["status"] == "accepted"


def test_find_open_by_digest_reuses_pending_gate(tmp_path):
    ledger = GateLedger(tmp_path)
    request = _make_request(tmp_path)
    ledger.record_request(request)

    found = ledger.find_open_by_digest(request.tool_input_digest)
    assert found is not None
    assert found["gate_id"] == request.gate_id


def test_find_open_by_digest_none_after_result(tmp_path):
    ledger = GateLedger(tmp_path)
    request = _make_request(tmp_path)
    ledger.record_request(request)

    result = GateResult.accepted(
        gate_id=request.gate_id,
        accepted_by="judge",
        evidence={"check": "tests_pass", "result": "ok"},
    )
    ledger.record_result(result)

    assert ledger.find_open_by_digest(request.tool_input_digest) is None


def test_malformed_lines_are_ignored(tmp_path):
    ledger = GateLedger(tmp_path)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    with ledger.path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write("\n")
        handle.write("42\n")  # valid JSON but not a dict -> isinstance guard skips it

    request = _make_request(tmp_path)
    ledger.record_request(request)

    events = ledger.events()
    assert len(events) == 1
    assert events[0]["event"] == "gate_requested"
    assert ledger.latest(request.gate_id)["status"] == "requested"
