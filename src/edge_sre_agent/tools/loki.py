from __future__ import annotations

import time
from typing import Any

import httpx

from .base import Tool, ToolError
from .prometheus import _parse_duration

MAX_LINES = 200


class Loki:
    def __init__(self, base_url: str, client: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    def query(self, query: str, since: str = "1h", limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_LINES))
        end_ns = time.time_ns()
        start_ns = end_ns - _parse_duration(since) * 1_000_000_000
        response = self._client.get(
            f"{self._base_url}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": start_ns,
                "end": end_ns,
                "limit": limit,
                "direction": "backward",
            },
        )
        if response.status_code >= 400:
            raise ToolError(f"loki: {response.text[:300]}")
        lines = []
        for stream in response.json().get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            source = labels.get("pod") or labels.get("job") or labels.get("app") or "?"
            for ts, line in stream.get("values", []):
                lines.append((int(ts), source, line))
        lines.sort(reverse=True)
        return {
            "lines_returned": len(lines[:limit]),
            "lines": [f"[{source}] {line}" for _, source, line in lines[:limit]],
        }

    def labels(self) -> list[str]:
        response = self._client.get(f"{self._base_url}/loki/api/v1/labels")
        if response.status_code >= 400:
            raise ToolError(f"loki: {response.text[:300]}")
        return response.json().get("data", [])

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "loki_labels",
                "List the label names available in Loki, to help build a LogQL selector.",
                {"type": "object", "properties": {}},
                self.labels,
            ),
            Tool(
                "loki_query",
                "Search logs with LogQL, newest first. Narrow the selector and use line "
                'filters, e.g. {namespace="app"} |= "error".',
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "LogQL query"},
                        "since": {"type": "string", "description": "Window, e.g. 15m, 2h"},
                        "limit": {"type": "integer", "description": f"Max lines (<= {MAX_LINES})"},
                    },
                    "required": ["query"],
                },
                self.query,
            ),
        ]
