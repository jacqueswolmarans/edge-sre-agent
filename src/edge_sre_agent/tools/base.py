from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b"
        r"(\s*[:=]\s*)((?:bearer|basic)\s+\S+|\S+)"
    ),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:xox[abposr]|xapp)-[A-Za-z0-9-]+"),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} chars]"


class ToolError(Exception):
    """Raised for expected failures the model should see and recover from."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Toolbox:
    def __init__(self, tools: list[Tool], max_output_chars: int = 6000) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._max_output_chars = max_output_chars

    def __bool__(self) -> bool:
        return bool(self._tools)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def call(self, name: str, raw_arguments: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool {name!r}. Available: {', '.join(self.names)}"
        try:
            arguments = json.loads(raw_arguments or "{}")
            if not isinstance(arguments, dict):
                raise ToolError("arguments must be a JSON object")
            result = tool.handler(**arguments)
        except (ToolError, TypeError, ValueError) as exc:
            return f"error: {exc}"
        except Exception as exc:  # noqa: BLE001 - surface backend failures to the model
            return f"error: {type(exc).__name__}: {exc}"
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        return truncate(redact(text), self._max_output_chars)
