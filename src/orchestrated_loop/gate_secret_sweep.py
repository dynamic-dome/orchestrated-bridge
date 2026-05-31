"""Pure secret detection gate for tool inputs."""

from __future__ import annotations

import re
from collections.abc import Iterator


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-.{20,}"), "anthropic api key"),
    (re.compile(r"sk-(?!ant-)[A-Za-z0-9]{20,}"), "openai-style api key"),
    (re.compile(r"gh[opsr]_.{20,}"), "github token"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "aws access key id"),
    (re.compile(r"-----BEGIN[\s\S]*PRIVATE KEY-----"), "private key block"),
    (
        re.compile(
            r"(?im)^\s*(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*\S{12,}\s*$"
        ),
        "secret assignment",
    ),
)


def _iter_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def secret_sweep_violation(tool_input: dict) -> str | None:
    """Return a short reason if tool_input would write or expose a secret.

    Walks all string values in nested dicts and lists. Non-string scalar values
    are ignored.
    """

    for value in _iter_strings(tool_input):
        for pattern, reason in _SECRET_PATTERNS:
            if pattern.search(value):
                return reason
    return None
