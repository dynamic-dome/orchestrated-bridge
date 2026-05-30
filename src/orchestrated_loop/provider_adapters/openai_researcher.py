from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5"

DEVELOPER_PROMPT = """
You are the Researcher role in a local orchestrated agent loop.
Return only a JSON object with these keys:
- answer: string
- findings: array of objects with topic and detail strings
- citations: array of objects with source and loc strings
- open_questions: array of strings

Focus on the provided goal, plan, questions, and review context. Do not include
Markdown fences or prose outside the JSON object.
""".strip()


class OpenAIResearcherError(RuntimeError):
    pass


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        result = run(payload)
    except Exception as exc:
        print(f"openai_researcher failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result), end="")


def run(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIResearcherError("OPENAI_API_KEY is required for the OpenAI researcher.")

    endpoint = os.environ.get("ORCHESTRATED_LOOP_OPENAI_ENDPOINT", DEFAULT_ENDPOINT)
    model = os.environ.get("ORCHESTRATED_LOOP_OPENAI_MODEL", DEFAULT_MODEL)
    timeout = float(os.environ.get("ORCHESTRATED_LOOP_OPENAI_TIMEOUT", "60"))

    request_payload = build_request_payload(payload, model)
    response_payload = post_response(endpoint, api_key, request_payload, timeout)
    text = extract_response_text(response_payload)
    result = research_result_from_text(text, response_payload)
    result["provider"] = {
        "name": "openai",
        "model": model,
        "endpoint": endpoint,
        "response_id": response_payload.get("id"),
    }
    return result


def build_request_payload(payload: dict[str, Any], model: str) -> dict[str, Any]:
    user_context = {
        "goal": payload.get("goal", {}),
        "plan": payload.get("plan", {}),
        "questions": payload.get("questions", []),
        "workspace": payload.get("workspace"),
    }
    return {
        "model": model,
        "input": [
            {"role": "developer", "content": DEVELOPER_PROMPT},
            {"role": "user", "content": json.dumps(user_context, ensure_ascii=True)},
        ],
    }


def post_response(
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenAIResearcherError(f"OpenAI API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIResearcherError(f"OpenAI API request failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenAIResearcherError("OpenAI API response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise OpenAIResearcherError("OpenAI API response was not a JSON object.")
    return parsed


def extract_response_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    raise OpenAIResearcherError("OpenAI API response did not contain text output.")


def research_result_from_text(text: str, response: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {
            "answer": text,
            "findings": [
                {
                    "topic": "openai-response",
                    "detail": "Provider returned non-JSON text; adapter wrapped it as answer.",
                }
            ],
            "citations": [{"source": "openai-response", "loc": str(response.get("id", "unknown"))}],
            "open_questions": [],
        }
    if not isinstance(parsed, dict):
        raise OpenAIResearcherError("OpenAI researcher content was not a JSON object.")

    result = {
        "answer": str(parsed.get("answer", "")),
        "findings": _list_of_dicts(parsed.get("findings"), ["topic", "detail"]),
        "citations": _list_of_dicts(parsed.get("citations"), ["source", "loc"]),
        "open_questions": [str(item) for item in parsed.get("open_questions", [])],
    }
    if not result["answer"]:
        raise OpenAIResearcherError("OpenAI researcher result did not include answer.")
    if not result["citations"]:
        result["citations"] = [{"source": "openai-response", "loc": str(response.get("id", "unknown"))}]
    return result


def _list_of_dicts(value: Any, keys: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        items.append({key: str(entry.get(key, "")) for key in keys})
    return items


if __name__ == "__main__":
    main()
