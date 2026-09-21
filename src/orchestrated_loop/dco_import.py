from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dco_validate import validate_dco_handoff

ROLE_MAP = {
    "Orchestrator": "planner",
    "Researcher": "researcher",
    "Builder": "implementer",
    "Judge": "verifier",
}

STAGE_OUTPUTS = {
    "plan": ["state/PLAN.md", "state/TASKS.json"],
    "research": ["state/RESEARCH.md"],
    "build": ["deliverables/"],
    "review": ["state/REVIEW.md"],
    "improve": ["state/TODO.md", "state/HANDOFF.md"],
}

ROLE_CARDS = {
    "planner": {
        "display_name": "Planner",
        "profile_name": "code_safe",
        "purpose": "Turn one operator goal into scoped work items and dependency order.",
        "capabilities": ["decompose_goal", "define_acceptance_tests", "sequence_dependencies"],
        "tools": ["workspace_files", "plan_artifacts"],
        "allowed_stages": ["plan"],
        "safety_rules": ["write production DCO state", "store secrets", "write outside workspace"],
        "handoff_contract": {
            "reads": ["state/GOAL.json", "state/DCO_HANDOFF.json"],
            "writes": ["state/PLAN.md", "state/TASKS.json"],
        },
    },
    "researcher": {
        "display_name": "Researcher",
        "profile_name": "research",
        "purpose": "Collect source-grounded context for the current plan without changing code.",
        "capabilities": ["answer_research_questions", "collect_citations", "identify_open_questions"],
        "tools": ["workspace_files", "research_adapter"],
        "allowed_stages": ["research"],
        "safety_rules": ["write production DCO state", "store secrets", "write outside workspace"],
        "handoff_contract": {
            "reads": ["state/PLAN.md", "state/TASKS.json"],
            "writes": ["state/RESEARCH.md"],
        },
    },
    "implementer": {
        "display_name": "Implementer",
        "profile_name": "code_safe",
        "purpose": "Apply the scoped build task inside the selected workspace.",
        "capabilities": ["apply_workspace_changes", "produce_artifacts", "run_targeted_checks"],
        "tools": ["workspace_files", "test_runner"],
        "allowed_stages": ["build"],
        "safety_rules": ["write production DCO state", "store secrets", "write outside workspace"],
        "handoff_contract": {
            "reads": ["state/PLAN.md", "state/RESEARCH.md"],
            "writes": ["deliverables/"],
        },
    },
    "verifier": {
        "display_name": "Verifier",
        "profile_name": "review",
        "purpose": "Review outputs against the goal and produce evidence-backed next actions.",
        "capabilities": ["review_goal_alignment", "verify_required_checks", "surface_blockers"],
        "tools": ["workspace_files", "test_runner"],
        "allowed_stages": ["review"],
        "safety_rules": ["write production DCO state", "store secrets", "write outside workspace"],
        "handoff_contract": {
            "reads": ["state/RESULTS.json", "state/HANDOFF.md"],
            "writes": ["state/REVIEW.md"],
        },
    },
    "supervisor": {
        "display_name": "Supervisor",
        "profile_name": "review",
        "purpose": "Convert review findings into the next improvement loop or final handoff.",
        "capabilities": ["prioritize_improvements", "prepare_handoff", "decide_next_operator_action"],
        "tools": ["workspace_files", "run_status"],
        "allowed_stages": ["improve"],
        "safety_rules": ["write production DCO state", "store secrets", "write outside workspace"],
        "handoff_contract": {
            "reads": ["state/REVIEW.md", "state/TODO.md"],
            "writes": ["state/TODO.md", "state/HANDOFF.md"],
        },
    },
}


class DCOImportError(RuntimeError):
    """Raised when a DCO handoff cannot be converted into a read-only import package."""


def build_dco_import_package(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    state = workspace / "state"
    validation = validate_dco_handoff(workspace)
    if not validation["valid"]:
        raise DCOImportError("DCO handoff is invalid; refusing to create worker backlog.")

    handoff = _load_json(state / "DCO_HANDOFF.json")
    backlog = _build_worker_backlog(workspace, handoff)
    agent_cards = _build_agent_cards(handoff["workflow_id"], backlog["tasks"])
    safety = {
        "read_only": True,
        "mutates_dco": False,
        "target_workspace": str(workspace),
    }
    # Carry a gate_policy through to the worker package only when the upstream
    # handoff marks the run as gated (Phase 4). When the gate is off, the field
    # is absent — no false signal that workers are gated.
    handoff_safety = handoff.get("safety", {})
    if isinstance(handoff_safety, dict) and handoff_safety.get("gate_required"):
        safety["gate_policy"] = {
            "gate_required": True,
            "gate_mode": handoff_safety.get("gate_mode", "enforce"),
            "gate_ledger": handoff_safety.get("gate_ledger", "state/GATE_LEDGER.jsonl"),
        }
    package = {
        "version": 1,
        "created_at": _utc_now(),
        "workflow_id": handoff["workflow_id"],
        "source_handoff": "state/DCO_HANDOFF.json",
        "validation_report": "state/DCO_VALIDATION.json",
        "task_queue": "state/DCO_WORKER_TASKS.json",
        "agent_cards": "state/AGENT_CARDS.json",
        "audit_log": "state/DCO_AUDIT.jsonl",
        "task_count": len(backlog["tasks"]),
        "status": handoff["status"],
        "safety": safety,
    }

    _write_json(state / "AGENT_CARDS.json", agent_cards)
    _write_json(state / "DCO_WORKER_TASKS.json", backlog)
    _write_json(state / "DCO_IMPORT.json", package)
    _append_audit(
        state / "DCO_AUDIT.jsonl",
        {
            "type": "dco_import.created",
            "workflow_id": package["workflow_id"],
            "task_count": package["task_count"],
            "mutates_dco": False,
        },
    )
    _update_artifact_index(state / "ARTIFACTS.json")
    return package


def _build_worker_backlog(workspace: Path, handoff: dict[str, Any]) -> dict[str, Any]:
    work_items = handoff["delegation"]["work_items"]
    tasks = [_build_worker_task(workspace, handoff, item) for item in work_items]
    return {
        "version": 1,
        "created_at": _utc_now(),
        "workflow_id": handoff["workflow_id"],
        "import_mode": "read_only",
        "source_handoff": "state/DCO_HANDOFF.json",
        "target_workspace": str(workspace),
        "tasks": tasks,
    }


def _build_worker_task(
    workspace: Path,
    handoff: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    stage = str(item["stage"])
    owner = str(item["owner"])
    agent_role = _agent_role(owner, stage)
    required_inputs = _input_files_for_stage(handoff, stage)
    return {
        "task_id": f"{handoff['workflow_id']}:{item['id']}",
        "workflow_id": handoff["workflow_id"],
        "source_work_item_id": item["id"],
        "stage": stage,
        "agent_role": agent_role,
        "agent_card_ref": f"state/AGENT_CARDS.json#{agent_role}",
        "runtime_hint": "local_or_command_adapter",
        "title": item["title"],
        "brief": item.get("description", ""),
        "depends_on": item.get("depends_on", []),
        "status": "queued",
        "input_contract": {
            "goal": handoff["intent"]["goal"],
            "required_files": required_inputs,
            "target_workspace": str(workspace),
        },
        "output_contract": {
            "required_files": STAGE_OUTPUTS.get(stage, ["state/HANDOFF.md"]),
            "verdict_file": "state/REVIEW.md",
        },
        "allowed_changes": handoff["delegation"].get("allowed_changes", []),
        "forbidden_actions": handoff["delegation"].get("forbidden_changes", []),
        "verification_checks": handoff["verification"].get("required_checks", []),
    }


def _build_agent_cards(workflow_id: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    roles = _unique([str(task["agent_role"]) for task in tasks])
    cards = []
    for role in roles:
        template = ROLE_CARDS.get(role, _default_role_card(role))
        cards.append({"role": role, **template})
    return {
        "version": 1,
        "created_at": _utc_now(),
        "workflow_id": workflow_id,
        "cards": cards,
    }


def _default_role_card(role: str) -> dict[str, Any]:
    return {
        "display_name": role.replace("_", " ").title(),
        "profile_name": "code_safe",
        "purpose": "Handle a scoped workflow stage inside the selected workspace.",
        "capabilities": ["execute_scoped_task", "report_result"],
        "tools": ["workspace_files"],
        "allowed_stages": [],
        "safety_rules": ["write production DCO state", "store secrets", "write outside workspace"],
        "handoff_contract": {"reads": [], "writes": []},
    }


def _agent_role(owner: str, stage: str) -> str:
    if stage == "improve":
        return "supervisor"
    return ROLE_MAP.get(owner, owner.lower().replace(" ", "_"))


def _input_files_for_stage(handoff: dict[str, Any], stage: str) -> list[str]:
    base = [
        "state/GOAL.json",
        handoff["planning"]["plan_file"],
        handoff["planning"]["tasks_file"],
        handoff["context"]["artifact_index"],
        handoff["context"]["trace"],
    ]
    stage_inputs = {
        "plan": ["state/DCO_HANDOFF.json"],
        "research": ["state/PLAN.md"],
        "build": ["state/RESEARCH.md"],
        "review": ["state/RESULTS.json", "state/HANDOFF.md"],
        "improve": ["state/REVIEW.md", "state/TODO.md"],
    }
    return _unique([*base, *stage_inputs.get(stage, [])])


def _update_artifact_index(path: Path) -> None:
    artifact_index = _load_json(path)
    artifacts = artifact_index.setdefault("artifacts", [])
    existing = {
        item.get("path")
        for item in artifacts
        if isinstance(item, dict)
    }
    for rel_path in (
        "state/AGENT_CARDS.json",
        "state/DCO_VALIDATION.json",
        "state/DCO_IMPORT.json",
        "state/DCO_WORKER_TASKS.json",
        "state/DCO_AUDIT.jsonl",
    ):
        if rel_path not in existing:
            artifacts.append({"path": rel_path, "kind": "dco_import", "exists": True})
    _write_json(path, artifact_index)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DCOImportError(f"{path.name} must contain a JSON object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _append_audit(path: Path, payload: dict[str, Any]) -> None:
    event = {"at": _utc_now(), **payload}
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + json.dumps(event) + "\n", encoding="utf-8")


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique_items.append(item)
    return unique_items


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a read-only DCO worker import package.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    package = build_dco_import_package(args.workspace)
    print(json.dumps(package, indent=2))


if __name__ == "__main__":
    main()
