from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from orchestrated_loop.adapters import ROLE_REQUIRED_KEYS

DEFAULT_TIMEOUT_SECONDS = 300.0

ROLE_CONTRACTS = {
    "researcher": """
Return a JSON object with:
- answer: string
- findings: array of objects with topic and detail strings
- citations: array of objects with source and loc strings
- open_questions: array of strings
""".strip(),
    "builder": """
Return a JSON object with:
- changes: array of objects with file and diff strings
- logs: string
- test_results: object with passed, failed, and details
- artifacts: array of workspace-relative paths
- tasks_completed: array of work item ids
- research_used: string
""".strip(),
    "judge": """
Return a JSON object with:
- scores: object mapping criterion names to numeric scores
- overall: number
- fail_reasons: array of strings
- blocking: boolean
- next_actions: array of strings
""".strip(),
}


class ClaudeCodeRoleError(RuntimeError):
    pass


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        result = run(payload)
    except Exception as exc:
        print(f"claude_code_role failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result), end="")


def run(payload: dict[str, Any]) -> dict[str, Any]:
    role = str(payload.get("role") or "")
    if role not in ROLE_REQUIRED_KEYS:
        raise ClaudeCodeRoleError(f"Unsupported role for Claude Code adapter: {role}")

    workspace = Path(str(payload.get("workspace") or ".")).resolve()
    if not workspace.exists():
        raise ClaudeCodeRoleError(f"Workspace does not exist: {workspace}")

    model = os.environ.get("ORCHESTRATED_LOOP_CLAUDE_MODEL", "").strip()
    timeout = float(os.environ.get("ORCHESTRATED_LOOP_CLAUDE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    command = build_claude_command(model)
    prompt = build_prompt(payload)
    completed = run_claude(command, prompt, workspace, timeout)
    result = parse_claude_output(completed.stdout, role)
    result["provider"] = {
        "name": "claude-code",
        "model": model or "default",
        "response_format": "json",
    }
    return result


def build_claude_command(model: str = "") -> list[str]:
    command = resolve_claude_command_base()
    command.extend(["-p", "--print", "--output-format", "json"])
    if model:
        command.extend(["--model", model])
    return command


def resolve_claude_command_base() -> list[str]:
    command_json = os.environ.get("ORCHESTRATED_LOOP_CLAUDE_COMMAND", "").strip()
    if command_json:
        try:
            raw = json.loads(command_json)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeRoleError("ORCHESTRATED_LOOP_CLAUDE_COMMAND must be a JSON array.") from exc
        if not isinstance(raw, list) or not raw or not all(isinstance(part, str) for part in raw):
            raise ClaudeCodeRoleError("ORCHESTRATED_LOOP_CLAUDE_COMMAND must be a non-empty string array.")
        return [_resolve_executable(raw[0]), *raw[1:]]

    executable = os.environ.get("ORCHESTRATED_LOOP_CLAUDE_CMD", "claude").strip() or "claude"
    return [_resolve_executable(executable)]


def _resolve_executable(executable: str) -> str:
    candidate = Path(executable)
    if candidate.is_absolute() or any(separator in executable for separator in ("\\", "/")):
        if not candidate.exists():
            raise ClaudeCodeRoleError(f"Claude Code command executable does not exist: {executable}")
        return str(candidate)
    resolved = shutil.which(executable)
    if resolved is None:
        raise ClaudeCodeRoleError(f"Claude Code command executable not found on PATH: {executable}")
    return resolved


def build_prompt(payload: dict[str, Any]) -> str:
    role = str(payload["role"])
    context = json.dumps(payload, indent=2, ensure_ascii=True)
    return (
        "You are a Claude Code role adapter inside a local orchestrated agent loop.\n"
        f"role: {role}\n\n"
        "Return only a JSON object. Do not include Markdown fences or prose outside JSON.\n"
        "Keep any writes inside the provided workspace path. Do not expose secrets.\n\n"
        f"{ROLE_CONTRACTS[role]}\n\n"
        "Input payload:\n"
        f"{context}\n"
    )


def run_claude(
    command: list[str],
    prompt: str,
    workspace: Path,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_DISABLE_HOOKS", "1")
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=workspace,
            timeout=timeout,
            encoding="utf-8",
            env=env,
        )
    except OSError as exc:
        raise ClaudeCodeRoleError(f"Claude Code command could not start: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCodeRoleError(f"Claude Code command timed out after {timeout}s.") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise ClaudeCodeRoleError(f"Claude Code command exited with {completed.returncode}{suffix}")
    return completed


def parse_claude_output(stdout: str, role: str) -> dict[str, Any]:
    parsed = decode_claude_json(stdout)

    if isinstance(parsed, dict) and ROLE_REQUIRED_KEYS[role].issubset(parsed.keys()):
        return validate_role_result(parsed, role)
    if isinstance(parsed, dict) and isinstance(parsed.get("result"), str):
        return parse_role_json_text(parsed["result"], role)
    if isinstance(parsed, list):
        return parse_event_stream_result(parsed, role)
    raise ClaudeCodeRoleError("Claude Code JSON did not contain a role result or result text.")


def decode_claude_json(stdout: str) -> Any:
    raw = stdout.lstrip("\ufeff \t\r\n")
    if not raw:
        raise ClaudeCodeRoleError("Claude Code command returned empty stdout.")
    try:
        parsed, _end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as exc:
        raise ClaudeCodeRoleError("Claude Code stdout was not valid JSON.") from exc
    return parsed


def parse_event_stream_result(events: list[Any], role: str) -> dict[str, Any]:
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if ROLE_REQUIRED_KEYS[role].issubset(event.keys()):
            return validate_role_result(event, role)
        result = event.get("result")
        if isinstance(result, str):
            return parse_role_json_text(result, role)
        if isinstance(result, dict):
            return validate_role_result(result, role)
    raise ClaudeCodeRoleError("Claude Code event stream did not contain a role result.")


def parse_role_json_text(text: str, role: str) -> dict[str, Any]:
    parsed = extract_role_json_object(text, role)
    if not isinstance(parsed, dict):
        raise ClaudeCodeRoleError("Claude Code result text did not decode to a JSON object.")
    return validate_role_result(parsed, role)


def extract_role_json_object(text: str, role: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ROLE_REQUIRED_KEYS[role].issubset(parsed.keys()):
            return parsed
    raise ClaudeCodeRoleError("Claude Code result text was not valid role JSON.")


def validate_role_result(result: dict[str, Any], role: str) -> dict[str, Any]:
    missing = sorted(ROLE_REQUIRED_KEYS[role] - result.keys())
    if missing:
        raise ClaudeCodeRoleError(
            f"Claude Code {role} result misses required keys: {', '.join(missing)}"
        )
    return dict(result)


if __name__ == "__main__":
    main()
