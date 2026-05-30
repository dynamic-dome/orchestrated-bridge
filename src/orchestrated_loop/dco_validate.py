from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_STATES = {"initialized", "needs_improvement", "complete", "blocked"}
ALLOWED_DECISIONS = {"accept", "retry", "blocked"}
REQUIRED_STAGES = ["plan", "research", "build", "review", "improve"]


def validate_dco_handoff(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    state = workspace / "state"
    handoff_path = state / "DCO_HANDOFF.json"
    manifest_path = state / "RUN_MANIFEST.json"
    artifacts_path = state / "ARTIFACTS.json"

    issues: list[dict[str, str]] = []
    handoff = _load_json_object(handoff_path, issues, "handoff")
    manifest = _load_json_object(manifest_path, issues, "manifest")
    artifacts = _load_json_object(artifacts_path, issues, "artifact_index")

    if handoff:
        _validate_handoff_shape(handoff, workspace, issues)
        _validate_handoff_against_manifest(handoff, manifest, issues)
        _validate_referenced_files(workspace, handoff, artifacts, issues)

    report = {
        "valid": not any(issue["severity"] == "error" for issue in issues),
        "checked_at": _utc_now(),
        "workflow_id": handoff.get("workflow_id") if handoff else None,
        "state": handoff.get("status", {}).get("state") if handoff else None,
        "decision": handoff.get("status", {}).get("decision") if handoff else None,
        "issues": issues,
        "summary": {
            "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
            "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
        },
    }
    (state).mkdir(parents=True, exist_ok=True)
    (state / "DCO_VALIDATION.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _load_json_object(path: Path, issues: list[dict[str, str]], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _issue(issues, "error", f"missing_{label}", f"Missing {path.name}.", str(path))
        return {}
    except json.JSONDecodeError as exc:
        _issue(issues, "error", f"invalid_{label}_json", str(exc), str(path))
        return {}
    if not isinstance(payload, dict):
        _issue(issues, "error", f"invalid_{label}_shape", f"{path.name} must be a JSON object.", str(path))
        return {}
    return payload


def _validate_handoff_shape(
    handoff: dict[str, Any],
    workspace: Path,
    issues: list[dict[str, str]],
) -> None:
    if handoff.get("version") != 1:
        _issue(issues, "error", "invalid_version", "DCO handoff version must be 1.", "version")
    if not handoff.get("workflow_id"):
        _issue(issues, "error", "missing_workflow_id", "workflow_id is required.", "workflow_id")

    intent = _child(handoff, "intent", issues)
    if not intent.get("goal"):
        _issue(issues, "error", "missing_goal", "intent.goal is required.", "intent.goal")

    context = _child(handoff, "context", issues)
    if context.get("target_workspace") != str(workspace):
        _issue(
            issues,
            "error",
            "workspace_mismatch",
            "context.target_workspace must match the validated workspace.",
            "context.target_workspace",
        )

    planning = _child(handoff, "planning", issues)
    if planning.get("required") is not True:
        _issue(issues, "error", "planning_not_required", "planning.required must be true.", "planning.required")

    delegation = _child(handoff, "delegation", issues)
    work_items = delegation.get("work_items", [])
    if not isinstance(work_items, list) or not work_items:
        _issue(issues, "error", "missing_work_items", "delegation.work_items must be non-empty.", "delegation.work_items")
    else:
        stages = [item.get("stage") for item in work_items if isinstance(item, dict)]
        if stages[: len(REQUIRED_STAGES)] != REQUIRED_STAGES:
            _issue(
                issues,
                "error",
                "invalid_work_item_stages",
                "work items must begin with plan, research, build, review, improve.",
                "delegation.work_items",
            )
        for index, item in enumerate(work_items):
            if not isinstance(item, dict):
                _issue(issues, "error", "invalid_work_item", "work item must be an object.", f"delegation.work_items[{index}]")
                continue
            for field in ("id", "stage", "owner", "title"):
                if not item.get(field):
                    _issue(issues, "error", f"missing_work_item_{field}", f"work item needs {field}.", f"delegation.work_items[{index}].{field}")

    verification = _child(handoff, "verification", issues)
    if not verification.get("required_checks"):
        _issue(issues, "error", "missing_required_checks", "verification.required_checks must be non-empty.", "verification.required_checks")
    if verification.get("blocking") is True and handoff.get("status", {}).get("state") != "blocked":
        _issue(issues, "error", "blocking_state_mismatch", "blocking handoff must have blocked status.", "verification.blocking")

    safety = _child(handoff, "safety", issues)
    if safety.get("mutates_dco") is not False:
        _issue(issues, "error", "dco_mutation_enabled", "safety.mutates_dco must be false for read-only import.", "safety.mutates_dco")
    if safety.get("secrets_required") is not False:
        _issue(issues, "error", "secrets_required", "safety.secrets_required must be false.", "safety.secrets_required")

    status = _child(handoff, "status", issues)
    if status.get("state") not in ALLOWED_STATES:
        _issue(issues, "error", "invalid_status_state", "status.state is invalid.", "status.state")
    if status.get("decision") not in ALLOWED_DECISIONS:
        _issue(issues, "error", "invalid_status_decision", "status.decision is invalid.", "status.decision")
    expected_decision = _decision_for_state(str(status.get("state")))
    if status.get("decision") != expected_decision:
        _issue(issues, "error", "decision_state_mismatch", "status.decision does not match status.state.", "status.decision")


def _validate_handoff_against_manifest(
    handoff: dict[str, Any],
    manifest: dict[str, Any],
    issues: list[dict[str, str]],
) -> None:
    if not manifest:
        return
    if handoff.get("workflow_id") != manifest.get("run_id"):
        _issue(issues, "error", "run_id_mismatch", "workflow_id must match manifest.run_id.", "workflow_id")
    status = handoff.get("status", {})
    if status.get("state") != manifest.get("status"):
        _issue(issues, "error", "status_mismatch", "handoff status must match run manifest.", "status.state")
    if status.get("iteration_count") != manifest.get("iteration_count"):
        _issue(issues, "error", "iteration_count_mismatch", "handoff iteration_count must match manifest.", "status.iteration_count")


def _validate_referenced_files(
    workspace: Path,
    handoff: dict[str, Any],
    artifacts: dict[str, Any],
    issues: list[dict[str, str]],
) -> None:
    referenced = [
        handoff.get("planning", {}).get("plan_file"),
        handoff.get("planning", {}).get("tasks_file"),
        handoff.get("context", {}).get("artifact_index"),
        handoff.get("context", {}).get("trace"),
        handoff.get("verification", {}).get("review_file"),
        handoff.get("verification", {}).get("results_file"),
        *handoff.get("verification", {}).get("eval_files", []),
    ]
    for rel_path in referenced:
        if isinstance(rel_path, str) and rel_path and not (workspace / rel_path).exists():
            _issue(issues, "error", "missing_referenced_file", f"Referenced file is missing: {rel_path}", rel_path)

    artifact_paths = {
        item.get("path")
        for item in artifacts.get("artifacts", [])
        if isinstance(item, dict)
    }
    for required in ("state/DCO_HANDOFF.json", "state/RUN_MANIFEST.json", "state/RESULTS.json"):
        if required not in artifact_paths:
            _issue(issues, "warning", "artifact_index_missing_entry", f"Artifact index misses {required}.", required)


def _child(parent: dict[str, Any], key: str, issues: list[dict[str, str]]) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        _issue(issues, "error", f"missing_{key}", f"{key} object is required.", key)
        return {}
    return value


def _decision_for_state(state: str) -> str:
    if state == "complete":
        return "accept"
    if state == "blocked":
        return "blocked"
    return "retry"


def _issue(
    issues: list[dict[str, str]],
    severity: str,
    code: str,
    message: str,
    path: str,
) -> None:
    issues.append({"severity": severity, "code": code, "message": message, "path": path})


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a DCO_HANDOFF.json export.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = validate_dco_handoff(args.workspace)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
