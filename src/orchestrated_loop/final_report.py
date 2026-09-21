from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FinalReportError(RuntimeError):
    """Raised when a workspace is not ready for a final acceptance report."""


def build_final_report(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    state = workspace / "state"
    manifest = _load_json_object(state / "RUN_MANIFEST.json")
    results = _load_json_object(state / "RESULTS.json")
    run_status = _load_json_object(state / "RUN_STATUS.json")
    artifacts = _load_json_object(state / "ARTIFACTS.json")
    worker_results = _load_json_object(state / "DCO_WORKER_RESULTS.json")

    operator = run_status.get("operator") if isinstance(run_status.get("operator"), dict) else {}
    status = run_status.get("status") if isinstance(run_status.get("status"), dict) else {}
    recommended_action = str(operator.get("recommended_action") or "")
    decision = str(status.get("decision") or "")
    if recommended_action != "accept_run" and decision != "accept":
        raise FinalReportError("final report requires RUN_STATUS recommended_action=accept_run")

    review = run_status.get("review") if isinstance(run_status.get("review"), dict) else {}
    goal = run_status.get("goal") if isinstance(run_status.get("goal"), dict) else {}
    artifact_items = artifacts.get("artifacts") if isinstance(artifacts.get("artifacts"), list) else []
    worker_tasks = worker_results.get("tasks") if isinstance(worker_results.get("tasks"), list) else []
    report = {
        "version": 1,
        "accepted": True,
        "accepted_at": _utc_now(),
        "workspace": str(workspace),
        "workflow_id": run_status.get("workflow_id") or manifest.get("run_id"),
        "goal": {
            "objective": goal.get("objective") or results.get("goal", {}).get("objective", ""),
            "success_criteria": goal.get("success_criteria", []),
        },
        "status": {
            "state": status.get("state"),
            "decision": decision or "accept",
            "recommended_action": recommended_action or "accept_run",
            "iteration_count": status.get("iteration_count"),
        },
        "review": {
            "last_overall": review.get("last_overall"),
            "blocking": review.get("blocking"),
            "next_actions": review.get("next_actions", []),
        },
        "evidence": {
            "artifact_count": len([item for item in artifact_items if isinstance(item, dict)]),
            "worker_result_count": len(worker_tasks),
            "files": [
                "state/RUN_MANIFEST.json",
                "state/RESULTS.json",
                "state/RUN_STATUS.json",
                "state/ARTIFACTS.json",
            ],
        },
        "side_effects": ["state/FINAL_REPORT.json", "state/FINAL_REPORT.md"],
    }

    state.mkdir(parents=True, exist_ok=True)
    _write_json(state / "FINAL_REPORT.json", report)
    (state / "FINAL_REPORT.md").write_text(_markdown(report), encoding="utf-8")
    _update_artifact_index(state / "ARTIFACTS.json")
    return report


def _markdown(report: dict[str, Any]) -> str:
    evidence = report.get("evidence", {})
    review = report.get("review", {})
    status = report.get("status", {})
    files = evidence.get("files") if isinstance(evidence.get("files"), list) else []
    return (
        "# FINAL_REPORT.md\n\n"
        f"Workflow: {report.get('workflow_id')}\n\n"
        f"Goal: {report.get('goal', {}).get('objective')}\n\n"
        f"Accepted: {str(report.get('accepted') is True).lower()}\n\n"
        f"State: {status.get('state')}\n\n"
        f"Decision: {status.get('decision')}\n\n"
        f"Recommended action: {status.get('recommended_action')}\n\n"
        f"Last overall: {review.get('last_overall')}\n\n"
        f"Worker results: {evidence.get('worker_result_count', 0)}\n\n"
        "Evidence files:\n"
        + ("\n".join(f"- {item}" for item in files) if files else "- none")
        + "\n"
    )


def _update_artifact_index(path: Path) -> None:
    artifact_index = _load_json_object(path)
    artifacts = artifact_index.setdefault("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
        artifact_index["artifacts"] = artifacts
    existing = {
        item.get("path")
        for item in artifacts
        if isinstance(item, dict)
    }
    for rel_path in ("state/FINAL_REPORT.json", "state/FINAL_REPORT.md"):
        if rel_path not in existing:
            artifacts.append({"path": rel_path, "kind": "final_report", "exists": True})
    _write_json(path, artifact_index)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the final acceptance report for a run.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(build_final_report(args.workspace), indent=2))


if __name__ == "__main__":
    main()
