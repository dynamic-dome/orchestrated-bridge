from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

ROLE_REQUIRED_KEYS = {
    "researcher": {"answer", "findings", "citations", "open_questions"},
    "builder": {"changes", "logs", "test_results", "artifacts", "tasks_completed", "research_used"},
    "judge": {"scores", "overall", "fail_reasons", "blocking", "next_actions"},
}


class AdapterError(RuntimeError):
    """Raised when an external role adapter cannot produce a valid role result."""


@dataclass(frozen=True)
class AdapterSpec:
    role: str
    type: str = "local"
    command: tuple[str, ...] = ()
    timeout_seconds: float = 30
    fallback: bool = False
    max_attempts: int = 1

    def summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "type": self.type,
            "fallback": self.fallback,
        }
        if self.command:
            payload["command"] = list(self.command)
            payload["timeout_seconds"] = self.timeout_seconds
            payload["max_attempts"] = self.max_attempts
        return payload


class CommandRoleAdapter:
    def __init__(self, spec: AdapterSpec, workspace: Path) -> None:
        self.spec = spec
        self.workspace = workspace

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = self._resolved_command()
        last_error: AdapterError | None = None
        for attempt in range(1, self.spec.max_attempts + 1):
            started = perf_counter()
            try:
                completed = self._run_command(command, payload)
                result = self._parse_output(completed.stdout)
                self._validate(result)
            except AdapterError as exc:
                last_error = exc
                self._record_event(
                    command,
                    attempt,
                    "failed",
                    _duration_ms(started),
                    error=str(exc),
                )
                continue
            duration_ms = _duration_ms(started)
            self._record_event(command, attempt, "succeeded", duration_ms)
            result["adapter"] = {
                "role": self.spec.role,
                "type": "command",
                "fallback": False,
                "attempts": attempt,
                "max_attempts": self.spec.max_attempts,
                "duration_ms": duration_ms,
            }
            return result

        assert last_error is not None
        raise AdapterError(
            f"{self.spec.role} command failed after {self.spec.max_attempts} "
            f"attempt(s): {last_error}"
        ) from last_error

    def _resolved_command(self) -> list[str]:
        if not self.spec.command:
            raise AdapterError(f"{self.spec.role} command adapter has no command.")
        executable = self.spec.command[0]
        resolved = _resolve_executable(executable)
        return [resolved, *self.spec.command[1:]]

    def _run_command(self, command: list[str], payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=self.workspace,
                timeout=self.spec.timeout_seconds,
            )
        except OSError as exc:
            raise AdapterError(f"{self.spec.role} command could not start: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(
                f"{self.spec.role} command timed out after {self.spec.timeout_seconds}s."
            ) from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            detail = f": {stderr}" if stderr else ""
            raise AdapterError(
                f"{self.spec.role} command exited with {completed.returncode}{detail}"
            )
        return completed

    def _parse_output(self, stdout: str) -> dict[str, Any]:
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"{self.spec.role} command did not return valid JSON.") from exc
        if not isinstance(result, dict):
            raise AdapterError(f"{self.spec.role} command returned non-object JSON.")
        return result

    def _validate(self, result: dict[str, Any]) -> None:
        required = ROLE_REQUIRED_KEYS[self.spec.role]
        missing = sorted(required - result.keys())
        if missing:
            raise AdapterError(
                f"{self.spec.role} command result misses required keys: {', '.join(missing)}"
            )

    def _record_event(
        self,
        command: list[str],
        attempt: int,
        status: str,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "timestamp": _utc_now(),
            "role": self.spec.role,
            "type": "command",
            "attempt": attempt,
            "max_attempts": self.spec.max_attempts,
            "status": status,
            "duration_ms": duration_ms,
            "executable": Path(command[0]).name,
        }
        if error:
            event["error"] = error
        path = self.workspace / "state" / "ADAPTER_EVENTS.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")


class AdapterSet:
    def __init__(self, workspace: Path, specs: dict[str, AdapterSpec] | None = None) -> None:
        self.workspace = workspace
        self.specs = specs or {}

    def summary(self) -> dict[str, Any]:
        return {
            role: self.specs.get(role, AdapterSpec(role)).summary()
            for role in ROLE_REQUIRED_KEYS
        }

    def run(
        self,
        role: str,
        payload: dict[str, Any],
        local_call: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        spec = self.specs.get(role, AdapterSpec(role))
        if spec.type == "local":
            result = local_call()
            return _with_adapter_meta(result, role, {"type": "local"})
        if spec.type != "command":
            raise AdapterError(f"Unsupported adapter type for {role}: {spec.type}")

        try:
            return CommandRoleAdapter(spec, self.workspace).run(payload)
        except AdapterError as exc:
            if not spec.fallback:
                raise
            result = local_call()
            return _with_adapter_meta(
                result,
                role,
                {
                    "type": "local",
                    "fallback_from": "command",
                    "error": str(exc),
                },
            )


def load_adapter_specs(path: Path | None) -> dict[str, AdapterSpec]:
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AdapterError(f"Could not read adapter config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AdapterError(f"Adapter config {path} is not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise AdapterError("Adapter config must be a JSON object.")

    specs: dict[str, AdapterSpec] = {}
    for role, config in raw.items():
        if role not in ROLE_REQUIRED_KEYS:
            raise AdapterError(f"Unknown adapter role: {role}")
        if not isinstance(config, dict):
            raise AdapterError(f"Adapter config for {role} must be an object.")
        adapter_type = str(config.get("type", "local"))
        if adapter_type == "local":
            specs[role] = AdapterSpec(role=role, type="local")
            continue
        if adapter_type != "command":
            raise AdapterError(f"Unsupported adapter type for {role}: {adapter_type}")
        command = config.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) for part in command
        ):
            raise AdapterError(f"Command adapter for {role} requires a non-empty string list.")
        timeout = float(config.get("timeout_seconds", 30))
        try:
            max_attempts = int(config.get("max_attempts", 1))
        except (TypeError, ValueError) as exc:
            raise AdapterError(
                f"Command adapter for {role} requires numeric max_attempts."
            ) from exc
        if max_attempts < 1:
            raise AdapterError(f"Command adapter for {role} requires max_attempts >= 1.")
        specs[role] = AdapterSpec(
            role=role,
            type="command",
            command=tuple(command),
            timeout_seconds=timeout,
            fallback=bool(config.get("fallback", False)),
            max_attempts=max_attempts,
        )
    return specs


def _resolve_executable(executable: str) -> str:
    candidate = Path(executable)
    if candidate.is_absolute() or any(separator in executable for separator in ("\\", "/")):
        if not candidate.exists():
            raise AdapterError(f"Command executable does not exist: {executable}")
        return str(candidate)
    resolved = shutil.which(executable)
    if resolved is None:
        raise AdapterError(f"Command executable not found on PATH: {executable}")
    return resolved


def _with_adapter_meta(
    result: dict[str, Any],
    role: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    result = dict(result)
    result["adapter"] = {"role": role, **metadata}
    return result


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
