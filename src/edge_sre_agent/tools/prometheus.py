from __future__ import annotations

import time
from typing import Any

import httpx

from .base import Tool, ToolError

MAX_SERIES = 50


def _parse_duration(value: str) -> int:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    value = value.strip()
    if not value or value[-1] not in units or not value[:-1].isdigit():
        raise ToolError(f"invalid duration {value!r}, use e.g. 30m, 6h, 2d")
    return int(value[:-1]) * units[value[-1]]


class Prometheus:
    def __init__(self, base_url: str, client: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self._client.get(f"{self._base_url}{path}", params=params)
        body = response.json() if response.content else {}
        if response.status_code >= 400 or body.get("status") != "success":
            raise ToolError(f"prometheus: {body.get('error') or response.text[:300]}")
        return body["data"]

    def query(self, query: str) -> dict[str, Any]:
        data = self._get("/api/v1/query", {"query": query})
        series = (
            [
                {"labels": item.get("metric", {}), "value": item.get("value", [None, None])[1]}
                for item in data.get("result", [])
            ]
            if data.get("resultType") == "vector"
            else data.get("result")
        )
        return _cap(series)

    def query_range(self, query: str, since: str = "1h", step: str = "5m") -> dict[str, Any]:
        end = time.time()
        data = self._get(
            "/api/v1/query_range",
            {"query": query, "start": end - _parse_duration(since), "end": end, "step": step},
        )
        series = []
        for item in data.get("result", []):
            values = [
                float(v) for _, v in item.get("values", []) if v not in ("NaN", "+Inf", "-Inf")
            ]
            summary = (
                {"min": min(values), "max": max(values), "last": values[-1], "points": len(values)}
                if values
                else {"points": 0}
            )
            series.append({"labels": item.get("metric", {}), **summary})
        return _cap(series)

    def alerts(self) -> list[dict[str, Any]]:
        data = self._get("/api/v1/alerts", {})
        return [
            {
                "name": alert.get("labels", {}).get("alertname"),
                "state": alert.get("state"),
                "since": alert.get("activeAt"),
                "labels": alert.get("labels", {}),
                "summary": alert.get("annotations", {}).get("summary"),
            }
            for alert in data.get("alerts", [])
        ]

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "prometheus_alerts",
                "List alerts currently pending or firing in Prometheus. Start here.",
                {"type": "object", "properties": {}},
                self.alerts,
            ),
            Tool(
                "prometheus_query",
                "Run an instant PromQL query and return the current value of each series.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "PromQL expression"}},
                    "required": ["query"],
                },
                self.query,
            ),
            Tool(
                "prometheus_query_range",
                "Run a PromQL query over a window. Returns min, max and last value per series.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "since": {"type": "string", "description": "Window, e.g. 30m, 6h, 2d"},
                        "step": {"type": "string", "description": "Resolution, e.g. 1m, 5m"},
                    },
                    "required": ["query"],
                },
                self.query_range,
            ),
        ]


def _cap(series: Any) -> dict[str, Any]:
    if not isinstance(series, list):
        return {"result": series}
    return {"series_total": len(series), "series": series[:MAX_SERIES]}
