from __future__ import annotations

import os
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from orchestrated_loop import orchestrate
from orchestrated_loop.adapters import AdapterError, load_adapter_specs
from orchestrated_loop.dco_import import DCOImportError, build_dco_import_package
from orchestrated_loop.final_report import FinalReportError, build_final_report
from orchestrated_loop.dco_validate import validate_dco_handoff
from orchestrated_loop.loop import build_parser
from orchestrated_loop.run_status import build_run_status

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_orchestrate_writes_state_files(tmp_path):
    results = orchestrate(tmp_path, max_iter=2, target=0.85)

    assert results["iterations"]
    assert (tmp_path / "state" / "PLAN.md").exists()
    assert (tmp_path / "state" / "LOG.md").exists()
    assert (tmp_path / "state" / "RESULTS.json").exists()
    assert (tmp_path / "state" / "RUN_STATUS.md").exists()
    assert (tmp_path / "eval" / "round-1.json").exists()
    status = json.loads((tmp_path / "state" / "RUN_STATUS.json").read_text(encoding="utf-8"))
    assert status["workflow_id"] == results["run"]["run_id"]
    assert status["operator"]["recommended_action"] in {
        "accept_run",
        "run_next_iteration",
        "review_adapter_events",
    }


def test_results_json_contains_judge_score(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99)

    payload = json.loads((tmp_path / "state" / "RESULTS.json").read_text(encoding="utf-8"))
    judge = payload["iterations"][0]["judge"]

    assert judge["overall"] >= 0.85
    assert judge["blocking"] is False


def test_builder_uses_isolated_workspace(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.85)

    assert (tmp_path / "src" / "sample_glossary.md").exists()
    assert not (tmp_path.parent / "src" / "sample_glossary.md").exists()


def test_orchestrate_creates_workspace_directory(tmp_path):
    workspace = tmp_path / "new-workspace"

    orchestrate(workspace, max_iter=1, target=0.85, goal="Build a new agent workspace.")

    assert (workspace / "state" / "RESULTS.json").exists()
    assert (workspace / "state" / "TRACE.jsonl").exists()


def test_orchestrate_continues_existing_results(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99)
    orchestrate(tmp_path, max_iter=2, target=0.99)

    payload = json.loads((tmp_path / "state" / "RESULTS.json").read_text(encoding="utf-8"))

    assert len(payload["iterations"]) == 2
    assert payload["iterations"][1]["plan"]["iteration"] == 2
    assert (tmp_path / "eval" / "round-1.json").exists()
    assert (tmp_path / "eval" / "round-2.json").exists()


def test_orchestrate_uses_goal_contract_and_decomposes_work(tmp_path):
    goal = (
        "Build a productive agent system that plans, decomposes, implements, "
        "researches, reviews, and improves against one orchestrator goal."
    )

    results = orchestrate(tmp_path, max_iter=1, target=0.99, goal=goal)
    first = results["iterations"][0]

    assert first["goal"]["objective"] == goal
    assert [task["stage"] for task in first["plan"]["tasks"]] == [
        "plan",
        "research",
        "build",
        "review",
        "improve",
    ]
    assert all(task["owner"] for task in first["plan"]["tasks"])
    assert (tmp_path / "state" / "GOAL.json").exists()
    assert (tmp_path / "state" / "TASKS.json").exists()
    assert (tmp_path / "state" / "TRACE.jsonl").exists()


def test_review_gaps_feed_next_iteration(tmp_path):
    results = orchestrate(
        tmp_path,
        max_iter=2,
        target=0.99,
        goal="Build a target-driven agent orchestration kernel.",
    )

    first_actions = results["iterations"][0]["judge"]["next_actions"]

    assert len(results["iterations"]) == 2
    assert first_actions
    assert results["iterations"][1]["plan"]["improvement_focus"] == first_actions

    trace = [
        json.loads(line)
        for line in (tmp_path / "state" / "TRACE.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["stage"] == "review" for event in trace)
    assert any(event["stage"] == "improve" for event in trace)


def test_dco_worker_results_feed_next_iteration_once(tmp_path):
    orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a worker-feedback-aware agent system.",
    )
    state = tmp_path / "state"
    (state / "DCO_WORKER_RESULTS.json").write_text(
        json.dumps(
            {
                "version": 1,
                "workflow_id": "run-worker-feedback",
                "completed_count": 2,
                "tasks": [
                    {
                        "source_work_item_id": "I1-01",
                        "stage": "plan",
                        "agent_role": "planner",
                        "title": "Plan the work",
                        "result_text": "Planner found that queue handoff needs a closed feedback loop.",
                    },
                    {
                        "source_work_item_id": "I1-02",
                        "stage": "research",
                        "agent_role": "researcher",
                        "title": "Research missing context",
                        "result_text": "Researcher confirmed completed worker outputs must feed the next iteration.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (state / "DCO_WORKER_RESULTS.md").write_text(
        "# DCO Worker Results\n\nPlanner found that queue handoff needs a closed feedback loop.\n",
        encoding="utf-8",
    )

    second = orchestrate(tmp_path, max_iter=2, target=0.99)
    third = orchestrate(tmp_path, max_iter=3, target=0.99)

    second_plan = second["iterations"][1]["plan"]
    third_plan = third["iterations"][2]["plan"]
    artifacts = json.loads((state / "ARTIFACTS.json").read_text(encoding="utf-8"))
    persisted = json.loads((state / "RESULTS.json").read_text(encoding="utf-8"))

    assert any("DCO worker planner/plan I1-01" in item for item in second_plan["improvement_focus"])
    assert any("closed feedback loop" in item for item in second_plan["improvement_focus"])
    assert not any("DCO worker planner/plan I1-01" in item for item in third_plan["improvement_focus"])
    assert persisted["dco_worker_result_ingests"][0]["iteration"] == 2
    assert len(persisted["dco_worker_result_ingests"]) == 1
    assert any(item["path"] == "state/DCO_WORKER_RESULTS.json" for item in artifacts["artifacts"])
    assert any(item["path"] == "state/DCO_WORKER_RESULTS.md" for item in artifacts["artifacts"])


def test_builder_only_marks_build_stage_completed(tmp_path):
    results = orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a target-driven agent orchestration kernel.",
    )

    completed = results["iterations"][0]["build"]["tasks_completed"]

    assert "I1-03" in completed
    assert "I1-04" not in completed


def test_researcher_command_adapter_is_used(tmp_path):
    script = tmp_path / "research_adapter.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "json.dump({\n"
        "  'answer': 'command research for ' + payload['goal']['objective'],\n"
        "  'findings': [{'topic': 'adapter', 'detail': payload['role']}],\n"
        "  'citations': [{'source': 'command-adapter', 'loc': 'stdout'}],\n"
        "  'open_questions': []\n"
        "}, sys.stdout)\n",
        encoding="utf-8",
    )
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "researcher": {
                    "type": "command",
                    "command": [sys.executable, str(script)],
                    "timeout_seconds": 5,
                }
            }
        ),
        encoding="utf-8",
    )

    results = orchestrate(
        tmp_path / "workspace",
        max_iter=1,
        target=0.99,
        goal="Build a productive adapter-enabled agent system.",
        adapter_config=config,
    )
    research = results["iterations"][0]["research"]

    assert research["answer"].startswith("command research for Build a productive")
    assert research["adapter"]["type"] == "command"
    assert (tmp_path / "workspace" / "state" / "ADAPTERS.json").exists()


def test_command_adapter_can_fallback_to_local_role(tmp_path):
    script = tmp_path / "failing_adapter.py"
    script.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "researcher": {
                    "type": "command",
                    "command": [sys.executable, str(script)],
                    "fallback": True,
                }
            }
        ),
        encoding="utf-8",
    )

    results = orchestrate(
        tmp_path / "workspace",
        max_iter=1,
        target=0.99,
        goal="Build a productive fallback-capable agent system.",
        adapter_config=config,
    )
    research = results["iterations"][0]["research"]

    assert research["adapter"]["type"] == "local"
    assert research["adapter"]["fallback_from"] == "command"
    assert "deterministic local orchestration kernel" in research["answer"]


def test_command_adapter_retries_transient_failure_and_records_events(tmp_path):
    script = tmp_path / "flaky_research_adapter.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "counter = pathlib.Path('attempts.txt')\n"
        "attempt = int(counter.read_text(encoding='utf-8')) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(attempt), encoding='utf-8')\n"
        "payload = json.loads(sys.stdin.read())\n"
        "if attempt == 1:\n"
        "    print('temporary adapter outage', file=sys.stderr)\n"
        "    sys.exit(9)\n"
        "json.dump({\n"
        "  'answer': 'retried research for ' + payload['goal']['objective'],\n"
        "  'findings': [{'topic': 'retry', 'detail': str(attempt)}],\n"
        "  'citations': [{'source': 'flaky-adapter', 'loc': 'attempt-2'}],\n"
        "  'open_questions': []\n"
        "}, sys.stdout)\n",
        encoding="utf-8",
    )
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "researcher": {
                    "type": "command",
                    "command": [sys.executable, str(script)],
                    "timeout_seconds": 5,
                    "max_attempts": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    results = orchestrate(
        tmp_path / "workspace",
        max_iter=1,
        target=0.99,
        goal="Build a retry-capable productive agent system.",
        adapter_config=config,
    )
    research = results["iterations"][0]["research"]
    events = [
        json.loads(line)
        for line in (tmp_path / "workspace" / "state" / "ADAPTER_EVENTS.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    artifacts = json.loads(
        (tmp_path / "workspace" / "state" / "ARTIFACTS.json").read_text(encoding="utf-8")
    )

    assert research["answer"].startswith("retried research for Build a retry-capable")
    assert research["adapter"]["attempts"] == 2
    assert research["adapter"]["max_attempts"] == 2
    assert [event["status"] for event in events] == ["failed", "succeeded"]
    assert [event["attempt"] for event in events] == [1, 2]
    assert all(event["role"] == "researcher" for event in events)
    assert any(item["path"] == "state/ADAPTER_EVENTS.jsonl" for item in artifacts["artifacts"])


def test_command_adapter_config_rejects_invalid_max_attempts(tmp_path):
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "researcher": {
                    "type": "command",
                    "command": [sys.executable, "-c", "print('ok')"],
                    "max_attempts": "twice",
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        load_adapter_specs(config)
    except AdapterError as exc:
        assert "max_attempts" in str(exc)
    else:
        raise AssertionError("Expected AdapterError for non-numeric max_attempts")


def test_cli_parser_accepts_goal_and_goal_file(tmp_path):
    goal_file = tmp_path / "goal.txt"
    goal_file.write_text("Build an orchestrated agent system.", encoding="utf-8")

    parser = build_parser()
    direct = parser.parse_args(["--workspace", str(tmp_path), "--goal", "Ship the loop."])
    from_file = parser.parse_args(["--workspace", str(tmp_path), "--goal-file", str(goal_file)])

    assert direct.goal == "Ship the loop."
    assert from_file.goal_file == goal_file


def test_cli_parser_accepts_adapter_config(tmp_path):
    config = tmp_path / "adapters.json"

    parser = build_parser()
    parsed = parser.parse_args(["--workspace", str(tmp_path), "--adapter-config", str(config)])

    assert parsed.adapter_config == config


def test_run_manifest_tracks_goal_status_and_artifacts(tmp_path):
    results = orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a manifest-backed agent orchestration run.",
    )

    manifest = json.loads((tmp_path / "state" / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    artifacts = json.loads((tmp_path / "state" / "ARTIFACTS.json").read_text(encoding="utf-8"))

    assert results["run"]["run_id"] == manifest["run_id"]
    assert manifest["status"] == "needs_improvement"
    assert manifest["goal"]["objective"] == "Build a manifest-backed agent orchestration run."
    assert manifest["iterations"][0]["status"] == "needs_improvement"
    assert manifest["iterations"][0]["overall"] == results["iterations"][0]["judge"]["overall"]
    assert any(item["path"] == "state/RESULTS.json" for item in artifacts["artifacts"])
    assert any(item["kind"] == "deliverable" for item in artifacts["artifacts"])


def test_run_id_is_stable_across_resume(tmp_path):
    first = orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a resumable run.",
    )
    second = orchestrate(tmp_path, max_iter=2, target=0.99)

    manifest = json.loads((tmp_path / "state" / "RUN_MANIFEST.json").read_text(encoding="utf-8"))

    assert first["run"]["run_id"] == second["run"]["run_id"]
    assert manifest["run_id"] == first["run"]["run_id"]
    assert len(manifest["iterations"]) == 2


def test_openai_researcher_provider_adapter_runs_via_command(tmp_path, monkeypatch):
    server = RecordingOpenAIServer()
    server.start()
    try:
        src_path = str(PROJECT_ROOT / "src")
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        monkeypatch.setenv(
            "PYTHONPATH",
            src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath,
        )
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("ORCHESTRATED_LOOP_OPENAI_MODEL", "test-model")
        monkeypatch.setenv("ORCHESTRATED_LOOP_OPENAI_ENDPOINT", server.url)

        config = tmp_path / "adapters.json"
        config.write_text(
            json.dumps(
                {
                    "researcher": {
                        "type": "command",
                        "command": [
                            sys.executable,
                            "-m",
                            "orchestrated_loop.provider_adapters.openai_researcher",
                        ],
                        "timeout_seconds": 10,
                    }
                }
            ),
            encoding="utf-8",
        )

        results = orchestrate(
            tmp_path / "workspace",
            max_iter=1,
            target=0.99,
            goal="Build a provider-backed agent system.",
            adapter_config=config,
        )
    finally:
        server.stop()

    research = results["iterations"][0]["research"]
    request = server.requests[0]
    body = json.loads(request["body"])

    assert research["adapter"]["type"] == "command"
    assert research["provider"]["name"] == "openai"
    assert research["answer"] == "Provider-backed research answer."
    assert request["headers"]["authorization"] == "Bearer test-key"
    assert body["model"] == "test-model"
    assert body["input"][0]["role"] == "developer"


def test_claude_code_builder_provider_adapter_runs_via_command(tmp_path, monkeypatch):
    fake_cli = tmp_path / "fake_claude.py"
    fake_cli.write_text(
        "import json, pathlib, sys\n"
        "prompt = sys.stdin.read()\n"
        "pathlib.Path('claude_prompt.txt').write_text(prompt, encoding='utf-8')\n"
        "result = {\n"
        "  'changes': [{'file': 'deliverables/claude-builder.md', 'diff': '+ claude builder output'}],\n"
        "  'logs': 'Claude Code fake builder ran.',\n"
        "  'test_results': {'passed': 2, 'failed': 0, 'details': ['fake cli ok', 'contract ok']},\n"
        "  'artifacts': ['deliverables/claude-builder.md'],\n"
        "  'tasks_completed': ['I1-03'],\n"
        "  'research_used': 'fake research context'\n"
        "}\n"
        "json.dump({'result': json.dumps(result)}, sys.stdout)\n",
        encoding="utf-8",
    )
    src_path = str(PROJECT_ROOT / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath,
    )
    monkeypatch.setenv(
        "ORCHESTRATED_LOOP_CLAUDE_COMMAND",
        json.dumps([sys.executable, str(fake_cli)]),
    )
    monkeypatch.setenv("ORCHESTRATED_LOOP_CLAUDE_MODEL", "test-claude-model")
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "builder": {
                    "type": "command",
                    "command": [
                        sys.executable,
                        "-m",
                        "orchestrated_loop.provider_adapters.claude_code_role",
                    ],
                    "timeout_seconds": 10,
                }
            }
        ),
        encoding="utf-8",
    )

    results = orchestrate(
        tmp_path / "workspace",
        max_iter=1,
        target=0.99,
        goal="Build a Claude-Code-backed agent system.",
        adapter_config=config,
    )

    build = results["iterations"][0]["build"]
    prompt = (tmp_path / "workspace" / "claude_prompt.txt").read_text(encoding="utf-8")

    assert build["adapter"]["type"] == "command"
    assert build["provider"]["name"] == "claude-code"
    assert build["provider"]["model"] == "test-claude-model"
    assert build["logs"] == "Claude Code fake builder ran."
    assert "role: builder" in prompt
    assert "Return only a JSON object" in prompt
    assert "Build a Claude-Code-backed agent system." in prompt


def test_claude_code_output_parser_accepts_current_event_stream_result():
    from orchestrated_loop.provider_adapters.claude_code_role import parse_claude_output

    role_result = {
        "changes": [{"file": "deliverables/live-builder.md", "diff": "+ live output"}],
        "logs": "Claude Code event stream builder ran.",
        "test_results": {"passed": 1, "failed": 0, "details": ["event stream ok"]},
        "artifacts": ["deliverables/live-builder.md"],
        "tasks_completed": ["I1-03"],
        "research_used": "event stream research",
    }
    stdout = json.dumps(
        [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}},
            {"type": "result", "result": json.dumps(role_result)},
        ]
    )

    parsed = parse_claude_output(stdout, "builder")

    assert parsed["logs"] == "Claude Code event stream builder ran."
    assert parsed["tasks_completed"] == ["I1-03"]


def test_claude_code_output_parser_ignores_bom_and_trailing_hook_noise():
    from orchestrated_loop.provider_adapters.claude_code_role import parse_claude_output

    role_result = {
        "scores": {"goal_alignment": 0.91},
        "overall": 0.91,
        "fail_reasons": [],
        "blocking": False,
        "next_actions": [],
    }
    stdout = (
        "\ufeff"
        + json.dumps([{"type": "result", "result": json.dumps(role_result)}])
        + "\nPrompt stop hooks are not yet supported outside REPL\n"
    )

    parsed = parse_claude_output(stdout, "judge")

    assert parsed["overall"] == 0.91
    assert parsed["blocking"] is False


def test_claude_code_output_parser_extracts_json_from_result_prose():
    from orchestrated_loop.provider_adapters.claude_code_role import parse_claude_output

    stdout = json.dumps(
        [
            {
                "type": "result",
                "result": (
                    "Workspace verified. Returning the builder contract JSON.\n\n"
                    "{\n"
                    '  "changes": [{"file": "builder_smoke.txt", "diff": "+ ok"}],\n'
                    '  "logs": "Builder role adapter invoked.",\n'
                    '  "test_results": {"passed": 1, "failed": 0, "details": "ok"},\n'
                    '  "artifacts": ["builder_smoke.txt"],\n'
                    '  "tasks_completed": ["I1-03"],\n'
                    '  "research_used": "Adapter smoke only."\n'
                    "}"
                ),
            }
        ]
    )

    parsed = parse_claude_output(stdout, "builder")

    assert parsed["logs"] == "Builder role adapter invoked."
    assert parsed["artifacts"] == ["builder_smoke.txt"]


def test_claude_code_provider_adapter_can_fallback_when_cli_missing(tmp_path, monkeypatch):
    src_path = str(PROJECT_ROOT / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath,
    )
    monkeypatch.setenv("ORCHESTRATED_LOOP_CLAUDE_CMD", str(tmp_path / "missing-claude.exe"))
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "builder": {
                    "type": "command",
                    "command": [
                        sys.executable,
                        "-m",
                        "orchestrated_loop.provider_adapters.claude_code_role",
                    ],
                    "timeout_seconds": 10,
                    "fallback": True,
                }
            }
        ),
        encoding="utf-8",
    )

    results = orchestrate(
        tmp_path / "workspace",
        max_iter=1,
        target=0.99,
        goal="Build a fallback-capable Claude Code adapter.",
        adapter_config=config,
    )

    build = results["iterations"][0]["build"]

    assert build["adapter"]["type"] == "local"
    assert build["adapter"]["fallback_from"] == "command"
    assert "Claude Code command executable does not exist" in build["adapter"]["error"]
    assert build["logs"].startswith("Builder produced iteration 1 artifacts")


def test_dco_handoff_exports_workflow_contract(tmp_path):
    results = orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a DCO-importable agent workflow.",
    )

    handoff = json.loads((tmp_path / "state" / "DCO_HANDOFF.json").read_text(encoding="utf-8"))

    assert handoff["version"] == 1
    assert handoff["workflow_id"] == results["run"]["run_id"]
    assert handoff["intent"]["goal"] == "Build a DCO-importable agent workflow."
    assert handoff["context"]["target_workspace"] == str(tmp_path)
    assert handoff["planning"]["plan_file"] == "state/PLAN.md"
    assert [item["stage"] for item in handoff["delegation"]["work_items"]] == [
        "plan",
        "research",
        "build",
        "review",
        "improve",
    ]
    assert handoff["verification"]["review_file"] == "state/REVIEW.md"
    assert handoff["status"]["state"] == "needs_improvement"
    assert handoff["memory"]["repo_docs_updated"] is True
    assert handoff["safety"]["mutates_dco"] is False


def test_dco_handoff_tracks_resume_iterations(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99, goal="Build resumable DCO handoff.")
    results = orchestrate(tmp_path, max_iter=2, target=0.99)

    handoff = json.loads((tmp_path / "state" / "DCO_HANDOFF.json").read_text(encoding="utf-8"))

    assert handoff["workflow_id"] == results["run"]["run_id"]
    assert handoff["status"]["iteration_count"] == 2
    assert len(handoff["verification"]["eval_files"]) == 2


def test_dco_handoff_validator_accepts_current_export(tmp_path):
    results = orchestrate(
        tmp_path,
        max_iter=2,
        target=0.99,
        goal="Build a validated DCO handoff.",
    )

    report = validate_dco_handoff(tmp_path)

    assert report["valid"] is True
    assert report["workflow_id"] == results["run"]["run_id"]
    assert report["decision"] == "retry"
    assert report["issues"] == []
    assert (tmp_path / "state" / "DCO_VALIDATION.json").exists()


def test_dco_handoff_validator_accepts_equivalent_absolute_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orchestrate(
        Path("workspace"),
        max_iter=1,
        target=0.99,
        goal="Build a path-normalized DCO handoff.",
    )

    report = validate_dco_handoff((tmp_path / "workspace").resolve())

    assert report["valid"] is True
    assert report["issues"] == []


def test_dco_handoff_validator_rejects_mutating_dco(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99, goal="Build a safe DCO handoff.")
    handoff_path = tmp_path / "state" / "DCO_HANDOFF.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["safety"]["mutates_dco"] = True
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    report = validate_dco_handoff(tmp_path)

    assert report["valid"] is False
    assert any(issue["code"] == "dco_mutation_enabled" for issue in report["issues"])


def test_dco_handoff_validator_rejects_missing_work_items(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99, goal="Build a complete DCO handoff.")
    handoff_path = tmp_path / "state" / "DCO_HANDOFF.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["delegation"]["work_items"] = []
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    report = validate_dco_handoff(tmp_path)

    assert report["valid"] is False
    assert any(issue["code"] == "missing_work_items" for issue in report["issues"])


def test_dco_import_package_exports_worker_backlog(tmp_path):
    results = orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a DCO-importable worker backlog.",
    )

    package = build_dco_import_package(tmp_path)
    backlog = json.loads((tmp_path / "state" / "DCO_WORKER_TASKS.json").read_text(encoding="utf-8"))
    agent_cards = json.loads((tmp_path / "state" / "AGENT_CARDS.json").read_text(encoding="utf-8"))
    artifacts = json.loads((tmp_path / "state" / "ARTIFACTS.json").read_text(encoding="utf-8"))

    assert package["workflow_id"] == results["run"]["run_id"]
    assert package["safety"]["mutates_dco"] is False
    assert package["task_count"] == 5
    assert package["task_queue"] == "state/DCO_WORKER_TASKS.json"
    assert package["agent_cards"] == "state/AGENT_CARDS.json"
    assert (tmp_path / "state" / "DCO_IMPORT.json").exists()
    assert (tmp_path / "state" / "DCO_AUDIT.jsonl").exists()
    assert agent_cards["workflow_id"] == results["run"]["run_id"]
    assert [card["role"] for card in agent_cards["cards"]] == [
        "planner",
        "researcher",
        "implementer",
        "verifier",
        "supervisor",
    ]
    planner = agent_cards["cards"][0]
    assert planner["profile_name"] == "code_safe"
    assert "decompose_goal" in planner["capabilities"]
    assert "write production DCO state" in planner["safety_rules"]
    assert backlog["workflow_id"] == results["run"]["run_id"]
    assert backlog["import_mode"] == "read_only"
    assert [task["stage"] for task in backlog["tasks"]] == [
        "plan",
        "research",
        "build",
        "review",
        "improve",
    ]
    assert [task["agent_role"] for task in backlog["tasks"]] == [
        "planner",
        "researcher",
        "implementer",
        "verifier",
        "supervisor",
    ]
    assert all(task["status"] == "queued" for task in backlog["tasks"])
    assert all(task["agent_card_ref"].startswith("state/AGENT_CARDS.json#") for task in backlog["tasks"])
    assert all(task["input_contract"]["required_files"] for task in backlog["tasks"])
    assert all(task["output_contract"]["required_files"] for task in backlog["tasks"])
    assert any(item["path"] == "state/AGENT_CARDS.json" for item in artifacts["artifacts"])
    assert any(item["path"] == "state/DCO_IMPORT.json" for item in artifacts["artifacts"])
    assert any(item["path"] == "state/DCO_WORKER_TASKS.json" for item in artifacts["artifacts"])


def test_dco_import_package_rejects_invalid_handoff_without_backlog(tmp_path):
    orchestrate(tmp_path, max_iter=1, target=0.99, goal="Build a safe DCO import package.")
    handoff_path = tmp_path / "state" / "DCO_HANDOFF.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["safety"]["mutates_dco"] = True
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    try:
        build_dco_import_package(tmp_path)
    except DCOImportError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("Expected DCOImportError")

    assert not (tmp_path / "state" / "DCO_WORKER_TASKS.json").exists()


def test_run_status_summarizes_operator_decision_and_adapter_health(tmp_path):
    script = tmp_path / "research_adapter.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "json.dump({\n"
        "  'answer': 'operator-visible research for ' + payload['goal']['objective'],\n"
        "  'findings': [{'topic': 'status', 'detail': 'adapter event should be summarized'}],\n"
        "  'citations': [{'source': 'status-adapter', 'loc': 'stdout'}],\n"
        "  'open_questions': []\n"
        "}, sys.stdout)\n",
        encoding="utf-8",
    )
    config = tmp_path / "adapters.json"
    config.write_text(
        json.dumps(
            {
                "researcher": {
                    "type": "command",
                    "command": [sys.executable, str(script)],
                    "timeout_seconds": 5,
                    "max_attempts": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    results = orchestrate(
        tmp_path / "workspace",
        max_iter=1,
        target=0.99,
        goal="Build an operator-visible productive agent system.",
        adapter_config=config,
    )
    package = build_dco_import_package(tmp_path / "workspace")

    status = build_run_status(tmp_path / "workspace")
    artifacts = json.loads(
        (tmp_path / "workspace" / "state" / "ARTIFACTS.json").read_text(encoding="utf-8")
    )

    assert status["workflow_id"] == results["run"]["run_id"]
    assert status["goal"]["objective"] == "Build an operator-visible productive agent system."
    assert status["status"]["state"] == "needs_improvement"
    assert status["review"]["last_overall"] == results["iterations"][0]["judge"]["overall"]
    assert status["adapters"]["health"] == "ok"
    assert status["adapters"]["total_attempts"] == 1
    assert status["adapters"]["failed_attempts"] == 0
    assert status["adapters"]["fallback_roles"] == []
    assert status["dco"]["validation_valid"] is True
    assert status["dco"]["import_package_exists"] is True
    assert status["dco"]["worker_task_count"] == package["task_count"] == 5
    assert status["operator"]["recommended_action"] == "queue_dco_workers"
    assert (tmp_path / "workspace" / "state" / "RUN_STATUS.json").exists()
    assert (tmp_path / "workspace" / "state" / "RUN_STATUS.md").exists()
    assert any(item["path"] == "state/RUN_STATUS.json" for item in artifacts["artifacts"])
    assert any(item["path"] == "state/RUN_STATUS.md" for item in artifacts["artifacts"])


def test_run_status_accepts_complete_run_instead_of_queueing_workers(tmp_path):
    orchestrate(
        tmp_path,
        max_iter=1,
        target=0.85,
        goal="Build a complete operator-visible agent system.",
    )
    build_dco_import_package(tmp_path)

    status = build_run_status(tmp_path)

    assert status["status"]["state"] == "complete"
    assert status["status"]["decision"] == "accept"
    assert status["dco"]["queue_ready"] is False
    assert status["operator"]["recommended_action"] == "accept_run"


def test_final_report_accepts_complete_run_with_evidence(tmp_path):
    orchestrate(
        tmp_path,
        max_iter=1,
        target=0.85,
        goal="Build an accepted productive agent system.",
    )
    (tmp_path / "state" / "DCO_WORKER_RESULTS.json").write_text(
        json.dumps(
            {
                "version": 1,
                "workflow_id": "run-final",
                "completed_count": 1,
                "tasks": [
                    {
                        "source_work_item_id": "I1-04",
                        "stage": "review",
                        "agent_role": "verifier",
                        "result_text": "Review accepted the run against the goal.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    build_dco_import_package(tmp_path)
    build_run_status(tmp_path)

    report = build_final_report(tmp_path)
    artifacts = json.loads((tmp_path / "state" / "ARTIFACTS.json").read_text(encoding="utf-8"))
    report_file = json.loads((tmp_path / "state" / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    report_md = (tmp_path / "state" / "FINAL_REPORT.md").read_text(encoding="utf-8")

    assert report["accepted"] is True
    assert report["workflow_id"] == report_file["workflow_id"]
    assert report["goal"]["objective"] == "Build an accepted productive agent system."
    assert report["status"]["recommended_action"] == "accept_run"
    assert report["review"]["last_overall"] >= 0.85
    assert report["evidence"]["worker_result_count"] == 1
    assert report["evidence"]["artifact_count"] >= 1
    assert "Build an accepted productive agent system." in report_md
    assert "Accepted: true" in report_md
    assert any(item["path"] == "state/FINAL_REPORT.json" for item in artifacts["artifacts"])
    assert any(item["path"] == "state/FINAL_REPORT.md" for item in artifacts["artifacts"])


def test_final_report_rejects_non_accepted_run(tmp_path):
    orchestrate(
        tmp_path,
        max_iter=1,
        target=0.99,
        goal="Build a not-yet-accepted productive agent system.",
    )
    build_dco_import_package(tmp_path)
    build_run_status(tmp_path)

    try:
        build_final_report(tmp_path)
    except FinalReportError as exc:
        assert "accept_run" in str(exc)
    else:
        raise AssertionError("Expected FinalReportError")


class RecordingOpenAIServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = HTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        host, port = self._server.server_address
        self.url = f"http://{host}:{port}/v1/responses"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                requests.append(
                    {
                        "path": self.path,
                        "headers": {key.lower(): value for key, value in self.headers.items()},
                        "body": body,
                    }
                )
                response = {
                    "id": "resp_test",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "answer": "Provider-backed research answer.",
                                            "findings": [
                                                {
                                                    "topic": "provider",
                                                    "detail": "OpenAI fake endpoint returned JSON.",
                                                }
                                            ],
                                            "citations": [
                                                {"source": "openai-response", "loc": "resp_test"}
                                            ],
                                            "open_questions": [],
                                        }
                                    ),
                                }
                            ],
                        }
                    ],
                }
                payload = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler
