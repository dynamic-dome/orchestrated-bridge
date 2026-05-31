from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

KNOWN_STAGES = {"build", "review", "final_report", "dco_import"}
RESULT_STATUSES = {"accepted", "rejected", "expired"}
GATE_TTL = timedelta(hours=2)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_z(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_gate_id() -> str:
    """Return a sortable gate id, e.g. ``gate-20260531-101500-000001-a1b2``."""
    now = _utc_now()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    micro_part = f"{now.microsecond:06d}"
    tail = uuid4().hex[:4]
    return f"gate-{date_part}-{time_part}-{micro_part}-{tail}"


def _tool_input_digest(tool_input: dict[str, Any]) -> str:
    """Canonical sha256 digest of a tool input, used as the gate dedupe key.

    Fail-fast (NOT fail-open): a tool input we cannot canonicalise raises
    ValueError here rather than crashing later inside the lock path with an
    opaque TypeError. This is the gate's safety mechanism — a malformed input
    must be rejected loudly, never silently waved through.

    Caveat (representation-sensitive): the digest is over the JSON text, so
    ``1`` and ``1.0`` hash differently, as do non-ASCII normalisation variants.
    Two semantically-equal inputs serialised through different layers (e.g. a
    Node<->Python bridge round-trip, global rule §17) may not dedupe. Acceptable
    for Iteration 1: tool inputs come from one Claude-hook code path with string
    keys; full numeric/Unicode normalisation is backlog if cross-layer dedupe
    becomes a real need.
    """
    try:
        canonical = json.dumps(
            tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except TypeError as exc:
        # Unorderable/mixed-type keys ({1: ..., "b": ...}) or non-serialisable
        # values. Refuse rather than let the orchestrator crash mid-gate.
        raise ValueError(f"tool_input is not canonicalisable for a gate digest: {exc}") from exc
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GateRequest:
    gate_id: str
    run_id: str
    iteration: int
    stage: str
    action: str
    tool_name: str
    tool_input_digest: str
    workspace: str
    requires: list[str]
    status: str
    created_at: str
    expires_at: str

    @classmethod
    def new(
        cls,
        run_id: str,
        iteration: int,
        stage: str,
        action: str,
        tool_name: str,
        tool_input: dict[str, Any],
        workspace: Path,
        requires: list[str],
    ) -> GateRequest:
        if stage not in KNOWN_STAGES:
            raise ValueError(
                f"unknown stage {stage!r}; expected one of {sorted(KNOWN_STAGES)}"
            )
        now = _utc_now()
        return cls(
            gate_id=make_gate_id(),
            run_id=run_id,
            iteration=iteration,
            stage=stage,
            action=action,
            tool_name=tool_name,
            tool_input_digest=_tool_input_digest(tool_input),
            workspace=Path(workspace).as_posix(),
            requires=list(requires),
            status="requested",
            created_at=_iso_z(now),
            expires_at=_iso_z(now + GATE_TTL),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "run_id": self.run_id,
            "iteration": self.iteration,
            "stage": self.stage,
            "action": self.action,
            "tool_name": self.tool_name,
            "tool_input_digest": self.tool_input_digest,
            "workspace": self.workspace,
            "requires": list(self.requires),
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    completed_at: str
    accepted_by: str | None = None
    rejected_by: str | None = None
    reason: str | None = None
    evidence: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise ValueError(
                f"unknown result status {self.status!r}; "
                f"expected one of {sorted(RESULT_STATUSES)}"
            )

    @classmethod
    def accepted(
        cls,
        gate_id: str,
        accepted_by: str,
        evidence: dict[str, Any],
    ) -> GateResult:
        return cls(
            gate_id=gate_id,
            status="accepted",
            completed_at=_iso_z(_utc_now()),
            accepted_by=accepted_by,
            evidence=evidence,
        )

    @classmethod
    def rejected(
        cls,
        gate_id: str,
        rejected_by: str,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> GateResult:
        return cls(
            gate_id=gate_id,
            status="rejected",
            completed_at=_iso_z(_utc_now()),
            rejected_by=rejected_by,
            reason=reason,
            evidence=evidence,
        )

    @classmethod
    def expired(cls, gate_id: str, reason: str = "") -> GateResult:
        return cls(
            gate_id=gate_id,
            status="expired",
            completed_at=_iso_z(_utc_now()),
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "gate_id": self.gate_id,
            "status": self.status,
            "completed_at": self.completed_at,
        }
        if self.accepted_by is not None:
            payload["accepted_by"] = self.accepted_by
        if self.rejected_by is not None:
            payload["rejected_by"] = self.rejected_by
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.evidence is not None:
            payload["evidence"] = self.evidence
        return payload
