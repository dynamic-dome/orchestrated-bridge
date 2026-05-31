from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrated_loop.gate_models import GateRequest, GateResult

EVENT_REQUESTED = "gate_requested"
EVENT_RESULT = "gate_result"


class GateLedger:
    """Append-only JSONL ledger of gate requests and results.

    Each event is a single compact JSON line under
    ``workspace/state/GATE_LEDGER.jsonl``. The ledger is the "lock" of the
    gate architecture: it records when a gate is requested and when it is
    resolved, and answers idempotency questions (is there a pending gate for
    this tool input?).
    """

    def __init__(self, workspace: Path) -> None:
        self._path = Path(workspace) / "state" / "GATE_LEDGER.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def record_request(self, request: GateRequest) -> None:
        self._append(
            {
                "event": EVENT_REQUESTED,
                "gate_id": request.gate_id,
                "payload": request.to_dict(),
            }
        )

    def record_result(self, result: GateResult) -> None:
        self._append(
            {
                "event": EVENT_RESULT,
                "gate_id": result.gate_id,
                "payload": result.to_dict(),
            }
        )

    def events(self) -> list[dict[str, Any]]:
        """Return all events in order; malformed/empty lines are skipped."""
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def latest(self, gate_id: str) -> dict[str, Any] | None:
        """Return the payload of the most recent event for ``gate_id``."""
        payload: dict[str, Any] | None = None
        for event in self.events():
            if event.get("gate_id") == gate_id:
                payload = event.get("payload")
        return payload

    def find_open_by_digest(self, digest: str) -> dict[str, Any] | None:
        """Return the payload of the newest pending request for ``digest``.

        A request is *pending* (open) when its gate has a matching
        ``tool_input_digest`` but no later ``gate_result`` event. This lets a
        caller reuse an existing gate instead of creating a duplicate.
        """
        resolved: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for event in self.events():
            kind = event.get("event")
            gate_id = event.get("gate_id")
            if kind == EVENT_RESULT:
                if gate_id is not None:
                    resolved.add(gate_id)
                continue
            if kind == EVENT_REQUESTED:
                payload = event.get("payload")
                if (
                    isinstance(payload, dict)
                    and payload.get("tool_input_digest") == digest
                ):
                    candidates.append(payload)
        for payload in reversed(candidates):
            if payload.get("gate_id") not in resolved:
                return payload
        return None

    def _append(self, obj: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
