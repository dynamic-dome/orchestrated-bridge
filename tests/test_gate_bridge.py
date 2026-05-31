from __future__ import annotations

from pathlib import Path

from orchestrated_loop.gate_bridge import BridgeGateClient
from orchestrated_loop.gate_models import GateRequest


def _make_request(workspace: Path) -> GateRequest:
    return GateRequest.new(
        run_id="run-abc123",
        iteration=2,
        stage="build",
        action="tool_use",
        tool_name="Bash",
        tool_input={"command": "git push"},
        workspace=workspace,
        requires=["dual_bridge_review_verdict", "repo_allowlist"],
    )


# --- Lane-aware task write (GT2) --------------------------------------------


def test_write_gate_task_lands_in_send_lane_outbox(tmp_path):
    """A initiates -> task goes into lane-A-to-B/outbox (GT2)."""
    client = BridgeGateClient(tmp_path)
    request = _make_request(tmp_path)

    task_path = client.write_gate_task(request)

    assert task_path.parent == tmp_path / "lane-A-to-B" / "outbox"
    assert task_path.name.startswith("task-")
    assert task_path.name.endswith(".md")
    assert task_path.exists()


def test_gate_task_frontmatter_is_review_without_repo(tmp_path):
    client = BridgeGateClient(tmp_path)
    request = _make_request(tmp_path)

    task_path = client.write_gate_task(request)
    text = task_path.read_text(encoding="utf-8")

    assert "kind: review" in text
    assert "adapter: claude" in text
    assert f"gate_id: {request.gate_id}" in text
    assert f"run_id: {request.run_id}" in text
    assert "stage: build" in text
    assert "status: open" in text
    # review path needs NO repo (only codex/implement does)
    assert "repo:" not in text


def test_gate_task_id_is_valid_bridge_shape(tmp_path):
    """The bridge poller hard-validates the task_id; a bad shape is quarantined.
    Our self-mirrored id must match make_task_id() exactly."""
    import re

    client = BridgeGateClient(tmp_path)
    task_path = client.write_gate_task(_make_request(tmp_path))
    text = task_path.read_text(encoding="utf-8")

    task_id_line = next(
        line for line in text.splitlines() if line.startswith("task_id:")
    )
    task_id = task_id_line.split(":", 1)[1].strip()
    # Same regex the bridge enforces (bridge_common._TASK_ID_RE).
    assert re.match(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}-[0-9a-f]+-[0-9a-f]{4}$", task_id)


def test_written_task_has_no_bom(tmp_path):
    client = BridgeGateClient(tmp_path)
    task_path = client.write_gate_task(_make_request(tmp_path))
    raw = task_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")


# --- Result discovery by gate_id --------------------------------------------


def _write_fake_result(
    bridge_root: Path, *, gate_id: str, verdict: str, status: str = "done"
) -> None:
    """Simulate what the bridge poller writes back into lane-A-to-B/inbox after
    a review: a result-*.md with the mirrored gate_id and a verdict field."""
    inbox = bridge_root / "lane-A-to-B" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        f"status: {status}\n"
        "kind: review\n"
        "adapter: claude\n"
        f"gate_id: {gate_id}\n"
        f"verdict: {verdict}\n"
        "verdict_reason: looks fine\n"
        "from: codex@laptop-b\n"
        "---\n"
        "## Ergebnis\nreviewed\n"
    )
    (inbox / f"result-20260531-101501-123456-0-a1b2.md").write_text(
        body, encoding="utf-8", newline="\n"
    )


def test_collect_result_matches_by_gate_id(tmp_path):
    client = BridgeGateClient(tmp_path)
    request = _make_request(tmp_path)
    _write_fake_result(tmp_path, gate_id=request.gate_id, verdict="accepted")

    found = client.collect_result(request.gate_id)

    assert found is not None
    assert found["verdict"] == "accepted"
    assert found["status"] == "done"
    assert found["gate_id"] == request.gate_id
    assert found["lane"] == "A-to-B"
    assert found["result_path"].endswith("result-20260531-101501-123456-0-a1b2.md")


def test_collect_result_none_when_gate_id_absent(tmp_path):
    client = BridgeGateClient(tmp_path)
    _write_fake_result(tmp_path, gate_id="gate-other", verdict="accepted")

    assert client.collect_result("gate-mine-not-here") is None


def test_collect_result_none_on_empty_inbox(tmp_path):
    client = BridgeGateClient(tmp_path)
    assert client.collect_result("gate-anything") is None


def test_collect_result_ignores_drive_conflict_copies(tmp_path):
    """Google-Drive conflict copies look like 'result-... (1).md' — skip them."""
    client = BridgeGateClient(tmp_path)
    inbox = tmp_path / "lane-A-to-B" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    body = "---\nstatus: done\ngate_id: gate-x\nverdict: accepted\n---\nx\n"
    (inbox / "result-20260531-101501-123456-0-a1b2 (1).md").write_text(
        body, encoding="utf-8", newline="\n"
    )

    assert client.collect_result("gate-x") is None


# --- Legacy fallback (no lanes present) -------------------------------------


def test_legacy_fallback_when_no_lanes(tmp_path):
    """If the bridge root has a flat outbox/ (no lane-* dirs), fall back to it."""
    (tmp_path / "outbox").mkdir(parents=True, exist_ok=True)
    client = BridgeGateClient(tmp_path)
    task_path = client.write_gate_task(_make_request(tmp_path))

    assert task_path.parent == tmp_path / "outbox"
