"""Build a consolidated run-status snapshot from a workspace's state JSON files."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_run_status(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    state = workspace / "state"
    manifest = _load_json_object(state / "RUN_MANIFEST.json")
    results = _load_json_object(state / "RESULTS.json")
    adapters = _load_json_object(state / "ADAPTERS.json")
    handoff = _load_json_object(state / "DCO_HANDOFF.json")
    validation = _load_json_object(state / "DCO_VALIDATION.json")
    import_package = _load_json_object(state / "DCO_IMPORT.json")
    worker_tasks = _load_json_object(state / "DCO_WORKER_TASKS.json")
    adapter_events = _load_jsonl(state / "ADAPTER_EVENTS.jsonl")

    latest = _latest_iteration(results)
    judge = latest.get("judge", {})
    status_state = str(manifest.get("status") or "initialized")
    decision = str(handoff.get("status", {}).get("decision") or _decision_for_state(status_state))
    adapter_summary = _adapter_summary(adapters, adapter_events, latest)
    dco_summary = _dco_summary(handoff, validation, import_package, worker_tasks, decision)
    status = {
        "version": 1,
        "generated_at": _utc_now(),
        "workspace": str(workspace),
        "workflow_id": manifest.get("run_id") or handoff.get("workflow_id"),
        "goal": {
            "objective": manifest.get("goal", {}).get("objective")
            or results.get("goal", {}).get("objective", ""),
            "success_criteria": manifest.get("goal", {}).get("success_criteria", []),
        },
        "status": {
            "state": status_state,
            "decision": decision,
            "iteration_count": manifest.get("iteration_count", len(results.get("iterations", []))),
        },
        "review": {
            "last_overall": judge.get("overall"),
            "blocking": judge.get("blocking"),
            "next_actions": judge.get("next_actions", []),
        },
        "adapters": adapter_summary,
        "dco": dco_summary,
        "operator": {
            "recommended_action": _recommended_action(status_state, adapter_summary, dco_summary),
        },
    }
    state.mkdir(parents=True, exist_ok=True)
    _write_json(state / "RUN_STATUS.json", status)
    (state / "RUN_STATUS.md").write_text(_status_markdown(status), encoding="utf-8")
    _update_artifact_index(state / "ARTIFACTS.json")
    return status


def _latest_iteration(results: dict[str, Any]) -> dict[str, Any]:
    iterations = results.get("iterations", [])
    if isinstance(iterations, list) and iterations and isinstance(iterations[-1], dict):
        return iterations[-1]
    return {}


def _adapter_summary(
    adapters: dict[str, Any],
    events: list[dict[str, Any]],
    latest: dict[str, Any],
) -> dict[str, Any]:
    failed = [event for event in events if event.get("status") == "failed"]
    succeeded = [event for event in events if event.get("status") == "succeeded"]
    fallback_roles = _fallback_roles(latest)
    health = "ok"
    if fallback_roles or failed:
        health = "degraded"
    if failed and not succeeded and not fallback_roles:
        health = "failed"
    return {
        "health": health,
        "configured": adapters,
        "total_attempts": len(events),
        "succeeded_attempts": len(succeeded),
        "failed_attempts": len(failed),
        "fallback_roles": fallback_roles,
        "last_events": events[-5:],
    }


def _fallback_roles(latest: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for role_key in ("research", "build", "judge"):
        result = latest.get(role_key, {})
        if not isinstance(result, dict):
            continue
        adapter = result.get("adapter", {})
        if isinstance(adapter, dict) and adapter.get("fallback_from"):
            roles.append(str(adapter.get("role") or role_key))
    return roles


def _dco_summary(
    handoff: dict[str, Any],
    validation: dict[str, Any],
    import_package: dict[str, Any],
    worker_tasks: dict[str, Any],
    decision: str,
) -> dict[str, Any]:
    task_count = import_package.get("task_count")
    if task_count is None:
        tasks = worker_tasks.get("tasks", [])
        task_count = len(tasks) if isinstance(tasks, list) else 0
    validation_valid = validation.get("valid")
    import_exists = bool(import_package)
    queue_ready = (
        decision == "retry"
        and validation_valid is True
        and import_exists
        and int(task_count or 0) > 0
    )
    return {
        "handoff_exists": bool(handoff),
        "validation_valid": validation_valid,
        "import_package_exists": import_exists,
        "worker_task_count": int(task_count or 0),
        "queue_ready": queue_ready,
    }


def _recommended_action(
    state: str,
    adapter_summary: dict[str, Any],
    dco_summary: dict[str, Any],
) -> str:
    if state == "blocked":
        return "inspect_blocker"
    if adapter_summary["health"] == "failed":
        return "fix_adapter"
    if state == "complete":
        return "accept_run"
    if dco_summary["queue_ready"]:
        return "queue_dco_workers"
    if adapter_summary["health"] == "degraded":
        return "review_adapter_events"
    return "run_next_iteration"


def _status_markdown(status: dict[str, Any]) -> str:
    next_actions = status["review"].get("next_actions") or []
    return (
        "# RUN_STATUS.md\n\n"
        f"Workflow: {status.get('workflow_id')}\n\n"
        f"Goal: {status['goal'].get('objective')}\n\n"
        f"State: {status['status'].get('state')}\n\n"
        f"Decision: {status['status'].get('decision')}\n\n"
        f"Last overall: {status['review'].get('last_overall')}\n\n"
        f"Adapter health: {status['adapters'].get('health')}\n\n"
        f"DCO queue ready: {status['dco'].get('queue_ready')}\n\n"
        f"Recommended action: {status['operator'].get('recommended_action')}\n\n"
        "Next actions:\n"
        + ("\n".join(f"- {item}" for item in next_actions) if next_actions else "- none")
        + "\n"
    )


def _update_artifact_index(path: Path) -> None:
    artifact_index = _load_json_object(path)
    artifacts = artifact_index.setdefault("artifacts", [])
    existing = {
        item.get("path")
        for item in artifacts
        if isinstance(item, dict)
    }
    for rel_path in ("state/RUN_STATUS.json", "state/RUN_STATUS.md"):
        if rel_path not in existing:
            artifacts.append({"path": rel_path, "kind": "state", "exists": True})
    _write_json(path, artifact_index)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _decision_for_state(state: str) -> str:
    if state == "complete":
        return "accept"
    if state == "blocked":
        return "blocked"
    return "retry"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an operator run status summary.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(build_run_status(args.workspace), indent=2))


if __name__ == "__main__":
    main()
