from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapters import AdapterSet, load_adapter_specs
from .agents import Builder, Goal, Judge, Orchestrator, Researcher

STATE_FILE_DEFAULTS = {
    "ADAPTERS.json": "{}\n",
    "ADAPTER_EVENTS.jsonl": "",
    "ARTIFACTS.json": "{\"artifacts\": []}\n",
    "DCO_HANDOFF.json": "{}\n",
    "GOAL.md": "# GOAL.md\n",
    "GOAL.json": "{}\n",
    "PLAN.md": "# PLAN.md\n",
    "TASKS.json": "{}\n",
    "RESEARCH.md": "# RESEARCH.md\n",
    "TODO.md": "# TODO.md\n",
    "REVIEW.md": "# REVIEW.md\n",
    "HANDOFF.md": "# HANDOFF.md\n",
    "LOG.md": "# LOG.md\n",
    "DECISIONS.md": "# DECISIONS.md\n",
    "RESULTS.json": "{\"iterations\": []}\n",
    "RUN_MANIFEST.json": "{}\n",
    "RUN_STATUS.json": "{}\n",
    "RUN_STATUS.md": "# RUN_STATUS.md\n",
    "TRACE.jsonl": "",
}

DCO_WORKER_RESULTS_JSON = "DCO_WORKER_RESULTS.json"
DCO_WORKER_RESULTS_MD = "DCO_WORKER_RESULTS.md"
DCO_WORKER_RESULT_SNIPPET_CHARS = 220


def save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def load_results(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"iterations": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("iterations"), list):
        return {"iterations": []}
    return payload


def load_pending_dco_worker_feedback(workspace: Path, results: dict[str, Any]) -> dict[str, Any] | None:
    path = workspace / "state" / DCO_WORKER_RESULTS_JSON
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    digest = hashlib.sha256(raw).hexdigest()
    ingests = results.get("dco_worker_result_ingests")
    if not isinstance(ingests, list):
        ingests = []
    if any(isinstance(item, dict) and item.get("sha256") == digest for item in ingests):
        return None
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return None
    focus = _worker_feedback_focus(tasks)
    if not focus:
        return None
    return {
        "sha256": digest,
        "workflow_id": payload.get("workflow_id"),
        "task_count": len(tasks),
        "focus": focus,
    }


def _worker_feedback_focus(tasks: list[Any]) -> list[str]:
    focus: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        result_text = str(task.get("result_text") or "").strip()
        if not result_text:
            continue
        role = str(task.get("agent_role") or "worker")
        stage = str(task.get("stage") or "stage")
        work_item = str(task.get("source_work_item_id") or task.get("source_job_id") or "task")
        focus.append(
            f"DCO worker {role}/{stage} {work_item}: "
            f"{_truncate_worker_feedback(result_text)}"
        )
    return focus


def _truncate_worker_feedback(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= DCO_WORKER_RESULT_SNIPPET_CHARS:
        return text
    return text[:DCO_WORKER_RESULT_SNIPPET_CHARS].rstrip() + "..."


def record_dco_worker_feedback_ingest(
    results: dict[str, Any],
    feedback: dict[str, Any],
    *,
    iteration: int,
) -> None:
    ingests = results.setdefault("dco_worker_result_ingests", [])
    if not isinstance(ingests, list):
        ingests = []
        results["dco_worker_result_ingests"] = ingests
    ingests.append(
        {
            "sha256": feedback["sha256"],
            "workflow_id": feedback.get("workflow_id"),
            "task_count": feedback.get("task_count", 0),
            "iteration": iteration,
            "ingested_at": utc_now(),
        }
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_goal(path: Path, fallback: str | None = None) -> Goal:
    if fallback:
        return Goal.from_text(fallback)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Goal.from_text()
    if payload:
        return Goal.from_dict(payload)
    return Goal.from_text()


def load_run_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("run_id", f"run-{uuid4().hex[:12]}")
    payload.setdefault("created_at", utc_now())
    payload.setdefault("iterations", [])
    return payload


def append_md(path: Path, heading: str, body: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(f"{existing}\n## {heading}\n\n{body}\n".lstrip(), encoding="utf-8")


def append_trace(path: Path, iteration: int, stage: str, message: str, payload: Any = None) -> None:
    event = {
        "iteration": iteration,
        "stage": stage,
        "message": message,
        "payload": payload or {},
    }
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + json.dumps(event) + "\n", encoding="utf-8")


def ensure_state(workspace: Path) -> dict[str, Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    state = workspace / "state"
    state.mkdir(exist_ok=True)
    files = {name: state / name for name in STATE_FILE_DEFAULTS}
    for name, initial in STATE_FILE_DEFAULTS.items():
        path = files[name]
        if not path.exists():
            path.write_text(initial, encoding="utf-8")
    (workspace / "eval").mkdir(exist_ok=True)
    return files


def log_round(
    workspace: Path,
    files: dict[str, Path],
    goal: dict[str, Any],
    plan: dict[str, Any],
    research: dict[str, Any],
    build: dict[str, Any],
    judge: dict[str, Any],
) -> None:
    iteration = plan["iteration"]
    save_json(
        workspace / "eval" / f"round-{iteration}.json",
        {"goal": goal, "plan": plan, "research": research, "build": build, "judge": judge},
    )
    files["GOAL.md"].write_text(
        "# GOAL.md\n\n"
        f"Objective: {goal['objective']}\n\n"
        "Success criteria:\n"
        + "\n".join(f"- {item}" for item in goal["success_criteria"])
        + "\n\nConstraints:\n"
        + "\n".join(f"- {item}" for item in goal["constraints"])
        + "\n",
        encoding="utf-8",
    )
    files["PLAN.md"].write_text(
        "# PLAN.md\n\n"
        f"Objective: {goal['objective']}\n\n"
        f"Iteration {iteration}: {plan['task']}\n\n"
        "Work items:\n"
        + "\n".join(
            f"- [{item['stage']}] {item['id']} {item['title']} ({item['owner']})"
            for item in plan["tasks"]
        )
        + "\n\n"
        "Acceptance tests:\n"
        + "\n".join(f"- {item}" for item in plan["acceptance_tests"])
        + "\n",
        encoding="utf-8",
    )
    save_json(files["TASKS.json"], {"iteration": iteration, "tasks": plan["tasks"]})
    files["RESEARCH.md"].write_text(
        "# RESEARCH.md\n\n"
        f"{research['answer']}\n\n"
        "Findings:\n"
        + "\n".join(f"- {item['topic']}: {item['detail']}" for item in research["findings"])
        + "\n\nCitations:\n"
        + "\n".join(f"- {item['source']} ({item['loc']})" for item in research["citations"])
        + "\n",
        encoding="utf-8",
    )
    files["TODO.md"].write_text(
        "# TODO.md\n\n" + "\n".join(f"- {item}" for item in judge["next_actions"]) + "\n",
        encoding="utf-8",
    )
    files["REVIEW.md"].write_text(
        "# REVIEW.md\n\n"
        f"Overall: {judge['overall']}\n\n"
        f"Blocking: {judge['blocking']}\n\n"
        "Scores:\n"
        + "\n".join(f"- {name}: {score}" for name, score in judge["scores"].items())
        + "\n\nNext actions:\n"
        + ("\n".join(f"- {item}" for item in judge["next_actions"]) or "- none")
        + "\n",
        encoding="utf-8",
    )
    files["HANDOFF.md"].write_text(
        "# HANDOFF.md\n\n"
        f"Goal: {goal['objective']}\n\n"
        f"Current iteration: {iteration}\n\n"
        f"Overall: {judge['overall']} blocking={judge['blocking']}\n\n"
        "Artifacts:\n"
        + "\n".join(f"- {path}" for path in build["artifacts"])
        + "\n\nNext actions:\n"
        + ("\n".join(f"- {item}" for item in judge["next_actions"]) or "- none")
        + "\n",
        encoding="utf-8",
    )
    append_md(
        files["LOG.md"],
        f"Iteration {iteration}",
        f"overall={judge['overall']} blocking={judge['blocking']}\n\n{build['logs']}",
    )
    append_md(
        files["DECISIONS.md"],
        f"Iteration {iteration}",
        "Keep role adapters explicit; use deterministic local behavior until a real adapter is configured.",
    )
    append_trace(files["TRACE.jsonl"], iteration, "plan", "Plan created", {"task": plan["task"]})
    append_trace(files["TRACE.jsonl"], iteration, "research", "Research completed", research["citations"])
    append_trace(files["TRACE.jsonl"], iteration, "build", "Build completed", build["artifacts"])
    append_trace(files["TRACE.jsonl"], iteration, "review", "Review completed", judge["scores"])
    if judge["next_actions"]:
        append_trace(files["TRACE.jsonl"], iteration, "improve", "Next actions queued", judge["next_actions"])


def status_from_judge(judge: dict[str, Any], target: float) -> str:
    if judge.get("blocking"):
        return "blocked"
    if float(judge.get("overall", 0)) >= target:
        return "complete"
    return "needs_improvement"


def write_run_indexes(
    workspace: Path,
    files: dict[str, Path],
    manifest: dict[str, Any],
    goal: dict[str, Any],
    adapters: dict[str, Any],
    results: dict[str, Any],
    target: float,
    gate_mode: str = "off",
) -> dict[str, Any]:
    manifest["goal"] = goal
    manifest["adapters"] = adapters
    manifest["updated_at"] = utc_now()
    manifest["iterations"] = [
        {
            "iteration": item["plan"]["iteration"],
            "status": status_from_judge(item["judge"], target),
            "overall": item["judge"]["overall"],
            "blocking": item["judge"]["blocking"],
            "artifacts": item["build"].get("artifacts", []),
            "next_actions": item["judge"].get("next_actions", []),
        }
        for item in results["iterations"]
    ]
    manifest["status"] = (
        manifest["iterations"][-1]["status"] if manifest["iterations"] else "initialized"
    )
    manifest["iteration_count"] = len(manifest["iterations"])
    save_json(files["RUN_MANIFEST.json"], manifest)
    artifact_index = build_artifact_index(workspace, results, gate_mode)
    save_json(files["ARTIFACTS.json"], artifact_index)
    save_json(
        files["DCO_HANDOFF.json"],
        build_dco_handoff(workspace, manifest, goal, adapters, results, artifact_index, gate_mode),
    )
    results["run"] = {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "manifest": "state/RUN_MANIFEST.json",
        "artifact_index": "state/ARTIFACTS.json",
        "dco_handoff": "state/DCO_HANDOFF.json",
    }
    return results


def build_dco_handoff(
    workspace: Path,
    manifest: dict[str, Any],
    goal: dict[str, Any],
    adapters: dict[str, Any],
    results: dict[str, Any],
    artifact_index: dict[str, Any],
    gate_mode: str = "off",
) -> dict[str, Any]:
    latest = results["iterations"][-1] if results["iterations"] else {}
    plan = latest.get("plan", {})
    judge = latest.get("judge", {})
    gate_required = gate_mode in ("shadow", "enforce")
    return {
        "version": 1,
        "workflow_id": manifest["run_id"],
        "created_by": "orchestrated-loop-demo",
        "intent": {
            "goal": goal.get("objective", ""),
            "success_criteria": goal.get("success_criteria", []),
            "constraints": goal.get("constraints", []),
        },
        "context": {
            "target_workspace": str(workspace),
            "source_documents": [
                "state/GOAL.md",
                "state/PLAN.md",
                "state/RESEARCH.md",
                "state/REVIEW.md",
                "state/HANDOFF.md",
            ],
            "artifact_index": "state/ARTIFACTS.json",
            "trace": "state/TRACE.jsonl",
            "adapter_events": "state/ADAPTER_EVENTS.jsonl",
            "run_status": "state/RUN_STATUS.json",
        },
        "planning": {
            "required": True,
            "plan_file": "state/PLAN.md",
            "tasks_file": "state/TASKS.json",
            "planner_agent": "Orchestrator",
        },
        "delegation": {
            "assigned_agents": sorted(
                {item.get("owner", "") for item in plan.get("tasks", []) if item.get("owner")}
            ),
            "work_items": plan.get("tasks", []),
            "adapters": adapters,
            "allowed_changes": ["selected workspace only"],
            "forbidden_changes": ["write production DCO state", "store secrets", "write outside workspace"],
        },
        "verification": {
            "required_checks": plan.get("acceptance_tests", []),
            "review_file": "state/REVIEW.md",
            "results_file": "state/RESULTS.json",
            "eval_files": [
                f"eval/round-{item['plan']['iteration']}.json" for item in results["iterations"]
            ],
            "last_overall": judge.get("overall"),
            "blocking": judge.get("blocking"),
            "next_actions": judge.get("next_actions", []),
        },
        "memory": {
            "repo_docs_updated": True,
            "sharepoint_update_required": False,
            "vault_update_required": False,
        },
        "safety": {
            "mutates_dco": False,
            "secrets_required": False,
            "artifact_count": len(artifact_index.get("artifacts", [])),
            # Gate metadata (Phase 4). gate_required signals to the DCO importer
            # that worker tasks carry a gate_policy; the loop itself never blocks
            # a local stage — the PreToolUse hook does the actual gating.
            "gate_required": gate_required,
            "gate_mode": gate_mode,
            "gate_ledger": "state/GATE_LEDGER.jsonl" if gate_required else None,
        },
        "status": {
            "state": manifest.get("status", "initialized"),
            "decision": _dco_decision(manifest.get("status", "initialized")),
            "iteration_count": manifest.get("iteration_count", 0),
        },
    }


def _dco_decision(status: str) -> str:
    if status == "complete":
        return "accept"
    if status == "blocked":
        return "blocked"
    return "retry"


def ensure_gate_ledger(workspace: Path) -> Path:
    """Make sure state/GATE_LEDGER.jsonl exists (append-only). Touching it empty
    is enough: the gate CLI/bridge append events; the loop only guarantees the
    file is present so shadow/enforce runs carry it in the artifact index."""
    path = workspace / "state" / "GATE_LEDGER.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path


def build_artifact_index(
    workspace: Path, results: dict[str, Any], gate_mode: str = "off"
) -> dict[str, Any]:
    artifact_paths = [
        "state/ADAPTERS.json",
        "state/ADAPTER_EVENTS.jsonl",
        "state/DCO_HANDOFF.json",
        "state/GOAL.json",
        "state/PLAN.md",
        "state/TASKS.json",
        "state/RESEARCH.md",
        "state/REVIEW.md",
        "state/HANDOFF.md",
        "state/RESULTS.json",
        "state/RUN_MANIFEST.json",
        "state/RUN_STATUS.json",
        "state/RUN_STATUS.md",
        "state/TRACE.jsonl",
    ]
    for item in results["iterations"]:
        iteration = item["plan"]["iteration"]
        artifact_paths.append(f"eval/round-{iteration}.json")
        artifact_paths.extend(item["build"].get("artifacts", []))
    for optional_path in (
        f"state/{DCO_WORKER_RESULTS_JSON}",
        f"state/{DCO_WORKER_RESULTS_MD}",
    ):
        if (workspace / optional_path).exists():
            artifact_paths.append(optional_path)
    # Gate ledger is an artifact whenever gate mode is active (Phase 4).
    if gate_mode in ("shadow", "enforce"):
        artifact_paths.append("state/GATE_LEDGER.jsonl")

    artifacts = []
    seen = set()
    for path in artifact_paths:
        if path in seen:
            continue
        seen.add(path)
        kind = "deliverable" if path.startswith("deliverables/") else _artifact_kind(path)
        artifacts.append(
            {
                "path": path,
                "kind": kind,
                "exists": (workspace / path).exists(),
            }
        )
    return {"artifacts": artifacts}


def _artifact_kind(path: str) -> str:
    if path.startswith("state/"):
        return "state"
    if path.startswith("eval/"):
        return "evaluation"
    return "artifact"


def orchestrate(
    workspace: Path,
    max_iter: int = 5,
    target: float = 0.85,
    goal: str | None = None,
    adapter_config: Path | None = None,
    gate_mode: str = "off",
) -> dict[str, Any]:
    workspace = workspace.resolve()
    files = ensure_state(workspace)
    if gate_mode in ("shadow", "enforce"):
        ensure_gate_ledger(workspace)
    results = load_results(files["RESULTS.json"])
    manifest = load_run_manifest(files["RUN_MANIFEST.json"])
    goal_spec = load_goal(files["GOAL.json"], goal)
    goal_dict = goal_spec.to_dict()
    pending_worker_feedback = load_pending_dco_worker_feedback(workspace, results)
    adapters = AdapterSet(workspace, load_adapter_specs(adapter_config))
    adapter_summary = adapters.summary()
    save_json(files["GOAL.json"], goal_dict)
    save_json(files["ADAPTERS.json"], adapter_summary)
    results["goal"] = goal_dict
    results["adapters"] = adapter_summary
    results["run"] = {
        "run_id": manifest["run_id"],
        "status": manifest.get("status", "initialized"),
        "manifest": "state/RUN_MANIFEST.json",
        "artifact_index": "state/ARTIFACTS.json",
    }
    orchestrator = Orchestrator()
    researcher = Researcher()
    builder = Builder(workspace)
    judge = Judge()

    while len(results["iterations"]) < max_iter:
        worker_focus = (
            pending_worker_feedback.get("focus", [])
            if isinstance(pending_worker_feedback, dict)
            else None
        )
        plan = orchestrator.make_plan(results, goal_spec, external_focus=worker_focus)
        plan_dict = plan.to_dict()
        research = adapters.run(
            "researcher",
            {
                "role": "researcher",
                "goal": goal_dict,
                "plan": plan_dict,
                "questions": plan.questions,
                "workspace": str(workspace),
            },
            lambda: researcher.ask(plan.questions, goal_spec),
        )
        build = adapters.run(
            "builder",
            {
                "role": "builder",
                "goal": goal_dict,
                "plan": plan_dict,
                "research": research,
                "workspace": str(workspace),
            },
            lambda: builder.run(plan, research, goal_spec),
        )
        score = adapters.run(
            "judge",
            {
                "role": "judge",
                "goal": goal_dict,
                "plan": plan_dict,
                "research": research,
                "build": build,
                "criteria": plan.criteria,
                "workspace": str(workspace),
            },
            lambda: judge.score(plan.criteria, build, plan, research, goal_spec),
        )
        log_round(workspace, files, goal_dict, plan_dict, research, build, score)
        results["iterations"].append(
            {
                "goal": goal_dict,
                "plan": plan_dict,
                "research": research,
                "build": build,
                "judge": score,
            }
        )
        if pending_worker_feedback is not None:
            record_dco_worker_feedback_ingest(
                results,
                pending_worker_feedback,
                iteration=plan.iteration,
            )
            pending_worker_feedback = None
        save_json(files["RESULTS.json"], results)
        write_run_indexes(workspace, files, manifest, goal_dict, adapter_summary, results, target, gate_mode)
        if score["overall"] >= target or score["blocking"]:
            break

    write_run_indexes(workspace, files, manifest, goal_dict, adapter_summary, results, target, gate_mode)
    save_json(files["RESULTS.json"], results)
    from .run_status import build_run_status

    build_run_status(workspace)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the target-driven orchestrated loop.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--max-iter", type=int, default=5)
    parser.add_argument("--target", type=float, default=0.85)
    parser.add_argument("--adapter-config", type=Path, help="JSON role adapter config file.")
    goal_group = parser.add_mutually_exclusive_group()
    goal_group.add_argument("--goal", help="Objective to hand to the orchestrator.")
    goal_group.add_argument("--goal-file", type=Path, help="Text file containing the objective.")
    # GT4: --gate-mode is its OWN arg, NOT part of the --goal exclusive group.
    parser.add_argument(
        "--gate-mode",
        choices=["off", "shadow", "enforce"],
        default="off",
        help="Pre-tool-use gate mode. off: no gate. shadow: record but never "
        "block. enforce: gate metadata + ledger (the PreToolUse hook does the "
        "actual blocking, not the loop).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    goal = args.goal_file.read_text(encoding="utf-8") if args.goal_file else args.goal
    results = orchestrate(
        args.workspace,
        args.max_iter,
        args.target,
        goal,
        args.adapter_config,
        gate_mode=args.gate_mode,
    )
    final = results["iterations"][-1]["judge"]
    print(
        json.dumps(
            {
                "goal": results["goal"]["objective"],
                "iterations": len(results["iterations"]),
                "final": final,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
