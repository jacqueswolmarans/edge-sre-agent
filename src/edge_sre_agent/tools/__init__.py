from __future__ import annotations

import httpx

from ..config import Settings
from .base import Tool, Toolbox, ToolError, redact, truncate

__all__ = ["Tool", "ToolError", "Toolbox", "build_toolbox", "redact", "truncate"]


def build_toolbox(settings: Settings, http: httpx.Client | None = None) -> Toolbox:
    http = http or httpx.Client(timeout=settings.http_timeout_seconds)
    tools: list[Tool] = []
    if settings.prometheus_url:
        from .prometheus import Prometheus

        tools += Prometheus(settings.prometheus_url, http).tools()
    if settings.loki_url:
        from .loki import Loki

        tools += Loki(settings.loki_url, http).tools()
    if settings.kubernetes_enabled:
        from .kubernetes import Kubernetes

        tools += Kubernetes.from_kubeconfig(
            settings.kube_context, settings.allowed_namespaces
        ).tools()
    return Toolbox(tools, settings.max_tool_output_chars)
