from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_OBJECTIVE = "Build a Markdown glossary extractor prototype."


def workspace_path(path: Path, workspace: Path) -> str:
    return path.relative_to(workspace).as_posix()


@dataclass(frozen=True)
class Goal:
    objective: str
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str | None = None) -> "Goal":
        objective = (text or DEFAULT_OBJECTIVE).strip() or DEFAULT_OBJECTIVE
        return cls(
            objective=objective,
            success_criteria=[
                "A plan exists before implementation starts.",
                "The goal is decomposed into owned work items.",
                "Research findings are recorded with source handles.",
                "Review produces a score and explicit next actions.",
                "The next iteration uses review gaps as improvement focus.",
            ],
            constraints=[
                "Keep all writes inside the selected workspace.",
                "Use deterministic local behavior unless a real adapter is configured.",
                "Do not store secrets or production data in artifacts.",
            ],
            deliverables=[
                "state/PLAN.md",
                "state/TASKS.json",
                "state/RESEARCH.md",
                "state/REVIEW.md",
                "state/HANDOFF.md",
                "state/TRACE.jsonl",
            ],
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Goal":
        if not isinstance(payload, dict):
            return cls.from_text()
        return cls(
            objective=str(payload.get("objective") or DEFAULT_OBJECTIVE),
            success_criteria=[str(item) for item in payload.get("success_criteria", [])],
            constraints=[str(item) for item in payload.get("constraints", [])],
            deliverables=[str(item) for item in payload.get("deliverables", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "success_criteria": self.success_criteria,
            "constraints": self.constraints,
            "deliverables": self.deliverables,
        }


@dataclass(frozen=True)
class WorkItem:
    id: str
    stage: str
    title: str
    owner: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "title": self.title,
            "owner": self.owner,
            "description": self.description,
            "depends_on": self.depends_on,
            "status": self.status,
        }


@dataclass(frozen=True)
class Plan:
    iteration: int
    task: str
    questions: list[str]
    criteria: dict[str, float]
    acceptance_tests: list[str]
    tasks: list[WorkItem]
    improvement_focus: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "task": self.task,
            "questions": self.questions,
            "criteria": self.criteria,
            "acceptance_tests": self.acceptance_tests,
            "tasks": [task.to_dict() for task in self.tasks],
            "improvement_focus": self.improvement_focus,
        }


class Orchestrator:
    def make_plan(
        self,
        results: dict[str, Any],
        goal: Goal | None = None,
        external_focus: list[str] | None = None,
    ) -> Plan:
        goal = goal or Goal.from_text()
        iteration = len(results.get("iterations", [])) + 1
        previous = results.get("iterations", [])[-1:] or [{}]
        previous_judge = previous[0].get("judge", {})
        improvement_focus = [
            str(item) for item in previous_judge.get("next_actions", []) if str(item).strip()
        ]
        if external_focus:
            improvement_focus.extend(str(item) for item in external_focus if str(item).strip())
        focus = "establish baseline" if not improvement_focus else "close review gaps"

        return Plan(
            iteration=iteration,
            task=f"{goal.objective} ({focus}, iteration {iteration}).",
            questions=[
                "Which context is required before implementation starts?",
                "Which constraints can block a safe implementation?",
                "Which acceptance evidence should the review inspect?",
            ],
            criteria={
                "planning": 0.2,
                "research": 0.2,
                "implementation": 0.3,
                "review": 0.2,
                "operability": 0.1,
            },
            acceptance_tests=[
                *goal.success_criteria,
                "TRACE.jsonl contains stage events for the iteration.",
                "HANDOFF.md summarizes the current state for the next agent.",
            ],
            tasks=self._work_items(iteration, goal, improvement_focus),
            improvement_focus=improvement_focus,
        )

    def _work_items(self, iteration: int, goal: Goal, gaps: list[str]) -> list[WorkItem]:
        prefix = f"I{iteration}"
        gap_text = "; ".join(gaps) if gaps else "No prior review gaps."
        return [
            WorkItem(
                id=f"{prefix}-01",
                stage="plan",
                title="Turn goal into an execution plan",
                owner="Orchestrator",
                description=f"Clarify objective and acceptance checks for: {goal.objective}",
            ),
            WorkItem(
                id=f"{prefix}-02",
                stage="research",
                title="Collect context and source handles",
                owner="Researcher",
                description="Answer planning questions and record citations or local source handles.",
                depends_on=[f"{prefix}-01"],
            ),
            WorkItem(
                id=f"{prefix}-03",
                stage="build",
                title="Produce the iteration deliverable",
                owner="Builder",
                description="Create deterministic artifacts inside the workspace.",
                depends_on=[f"{prefix}-02"],
            ),
            WorkItem(
                id=f"{prefix}-04",
                stage="review",
                title="Score deliverable against the goal",
                owner="Judge",
                description="Evaluate criteria, blocking status, and concrete next actions.",
                depends_on=[f"{prefix}-03"],
            ),
            WorkItem(
                id=f"{prefix}-05",
                stage="improve",
                title="Feed review gaps into the next round",
                owner="Orchestrator",
                description=gap_text,
                depends_on=[f"{prefix}-04"],
            ),
        ]


class Researcher:
    def ask(self, questions: list[str], goal: Goal | None = None) -> dict[str, Any]:
        goal = goal or Goal.from_text()
        return {
            "answer": (
                "Start with a deterministic local orchestration kernel. Keep real "
                "model, NotebookLM, Claude Code, or DCO adapters behind explicit "
                "role contracts so the loop stays testable."
            ),
            "findings": [
                {
                    "topic": "goal",
                    "detail": goal.objective,
                },
                {
                    "topic": "control-loop",
                    "detail": "Plan, research, build, review, and improve are separate stages.",
                },
            ],
            "citations": [
                {"source": "goal-contract", "loc": "objective"},
                {"source": "local-orchestrator", "loc": "role-contracts"},
            ],
            "open_questions": [question for question in questions if "external" in question.lower()],
        }


class Builder:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def run(self, plan: Plan, research: dict[str, Any], goal: Goal | None = None) -> dict[str, Any]:
        goal = goal or Goal.from_text()
        src = self.workspace / "src"
        tests = self.workspace / "tests"
        deliverables = self.workspace / "deliverables"
        src.mkdir(exist_ok=True)
        tests.mkdir(exist_ok=True)
        deliverables.mkdir(exist_ok=True)

        artifacts = []
        changes = []

        if "glossary" in goal.objective.lower():
            sample = src / "sample_glossary.md"
            sample.write_text(
                "# API\n\nApplication Programming Interface.\n\n"
                "# DCO\n\nDynamic Central Orchestrator.\n",
                encoding="utf-8",
            )
            sample_path = workspace_path(sample, self.workspace)
            artifacts.append(sample_path)
            changes.append(
                {
                    "file": sample_path,
                    "diff": "+ # API / # DCO sample glossary input",
                }
            )

        packet = deliverables / f"iteration-{plan.iteration}-goal-packet.md"
        packet.write_text(self._render_packet(plan, research, goal), encoding="utf-8")
        packet_path = workspace_path(packet, self.workspace)
        artifacts.append(packet_path)
        changes.append(
            {
                "file": packet_path,
                "diff": "+ target-driven execution packet",
            }
        )

        return {
            "changes": changes,
            "logs": f"Builder produced iteration {plan.iteration} artifacts for: {goal.objective}",
            "test_results": {
                "passed": len(plan.acceptance_tests),
                "failed": 0,
                "details": plan.acceptance_tests,
            },
            "artifacts": artifacts,
            "tasks_completed": [task.id for task in plan.tasks if task.stage == "build"],
            "research_used": research["answer"],
        }

    def _render_packet(self, plan: Plan, research: dict[str, Any], goal: Goal) -> str:
        tasks = "\n".join(
            f"- [{task.stage}] {task.id} {task.title} ({task.owner})" for task in plan.tasks
        )
        findings = "\n".join(
            f"- {item['topic']}: {item['detail']}" for item in research.get("findings", [])
        )
        criteria = "\n".join(f"- {name}: {weight}" for name, weight in plan.criteria.items())
        return (
            f"# Iteration {plan.iteration} Goal Packet\n\n"
            f"## Objective\n\n{goal.objective}\n\n"
            f"## Improvement Focus\n\n"
            + ("\n".join(f"- {item}" for item in plan.improvement_focus) or "- Baseline round")
            + "\n\n"
            f"## Work Items\n\n{tasks}\n\n"
            f"## Research Findings\n\n{findings}\n\n"
            f"## Criteria\n\n{criteria}\n"
        )


class Judge:
    def score(
        self,
        criteria: dict[str, float],
        build: dict[str, Any],
        plan: Plan | None = None,
        research: dict[str, Any] | None = None,
        goal: Goal | None = None,
    ) -> dict[str, Any]:
        failed = build["test_results"]["failed"]
        docs_present = any(path.endswith(".md") for path in build["artifacts"])
        has_tasks = bool(plan and plan.tasks)
        has_research = bool(research and research.get("citations"))
        score_bank = {
            "planning": 1.0 if has_tasks else 0.4,
            "research": 0.9 if has_research else 0.4,
            "implementation": 0.92 if failed == 0 and build["artifacts"] else 0.3,
            "review": 0.88 if build["test_results"]["details"] else 0.5,
            "operability": 0.86 if docs_present else 0.3,
            "functional": 1.0 if failed == 0 else 0.4,
            "robustness": 0.9 if failed == 0 else 0.5,
            "docs": 0.85 if docs_present else 0.2,
        }
        scores = {name: score_bank.get(name, 0.75) for name in criteria}
        total_weight = sum(criteria.values()) or 1.0
        overall = round(
            sum(scores[name] * criteria[name] for name in criteria) / total_weight,
            3,
        )
        next_actions = self._next_actions(scores)
        blocking = failed > 0 or not build["artifacts"]

        return {
            "scores": scores,
            "overall": overall,
            "fail_reasons": [] if not blocking else ["Build artifacts or tests failed."],
            "blocking": blocking,
            "next_actions": next_actions,
        }

    def _next_actions(self, scores: dict[str, float]) -> list[str]:
        actions = {
            "research": "Attach stronger source evidence before expanding implementation.",
            "implementation": "Add executable adapter hooks or richer implementation artifacts.",
            "review": "Tighten review evidence and make pass/fail reasons more specific.",
            "operability": "Improve handoff and trace detail for unattended continuation.",
        }
        return [actions[name] for name, score in scores.items() if name in actions and score < 0.95]
