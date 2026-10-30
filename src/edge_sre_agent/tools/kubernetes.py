"""Read-only Kubernetes tools. Secrets and ConfigMap contents are never exposed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .base import Tool, ToolError

MAX_ITEMS = 100
MAX_LOG_LINES = 300


def _age(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "?"
    seconds = int((datetime.now(UTC) - timestamp).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


class Kubernetes:
    def __init__(self, core_api: Any, allowed_namespaces: list[str] | None = None) -> None:
        self._core = core_api
        self._allowed = set(allowed_namespaces or [])

    @classmethod
    def from_kubeconfig(cls, context: str | None, allowed_namespaces: list[str]) -> Kubernetes:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config(context=context)
        return cls(client.CoreV1Api(), allowed_namespaces)

    def _check(self, namespace: str) -> None:
        if self._allowed and namespace not in self._allowed:
            allowed = ", ".join(sorted(self._allowed))
            raise ToolError(f"namespace {namespace!r} is not allowed. Allowed: {allowed}")

    def nodes(self) -> list[dict[str, Any]]:
        result = []
        for node in self._core.list_node().items[:MAX_ITEMS]:
            conditions = {c.type: c.status for c in node.status.conditions or []}
            problems = [t for t, s in conditions.items() if t != "Ready" and s == "True"]
            result.append(
                {
                    "name": node.metadata.name,
                    "ready": conditions.get("Ready") == "True",
                    "pressure": problems,
                    "unschedulable": bool(node.spec.unschedulable),
                    "kubelet": node.status.node_info.kubelet_version,
                    "age": _age(node.metadata.creation_timestamp),
                }
            )
        return result

    def unhealthy_pods(self, namespace: str = "") -> list[dict[str, Any]]:
        if namespace:
            self._check(namespace)
            pods = self._core.list_namespaced_pod(namespace).items
        else:
            pods = self._core.list_pod_for_all_namespaces().items
            if self._allowed:
                pods = [p for p in pods if p.metadata.namespace in self._allowed]
        result = []
        for pod in pods:
            statuses = pod.status.container_statuses or []
            restarts = sum(s.restart_count for s in statuses)
            waiting = [s.state.waiting.reason for s in statuses if s.state and s.state.waiting]
            not_ready = [s.name for s in statuses if not s.ready]
            healthy = pod.status.phase == "Succeeded" or (
                pod.status.phase == "Running" and not waiting and not not_ready
            )
            if healthy and restarts < 3:
                continue
            result.append(
                {
                    "namespace": pod.metadata.namespace,
                    "pod": pod.metadata.name,
                    "phase": pod.status.phase,
                    "waiting": waiting,
                    "not_ready": not_ready,
                    "restarts": restarts,
                    "node": pod.spec.node_name,
                    "age": _age(pod.metadata.creation_timestamp),
                }
            )
        return result[:MAX_ITEMS]

    def events(self, namespace: str = "", warnings_only: bool = True) -> list[dict[str, Any]]:
        selector = "type=Warning" if warnings_only else None
        if namespace:
            self._check(namespace)
            items = self._core.list_namespaced_event(namespace, field_selector=selector).items
        else:
            items = self._core.list_event_for_all_namespaces(field_selector=selector).items
            if self._allowed:
                items = [e for e in items if e.metadata.namespace in self._allowed]
        items.sort(
            key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
            reverse=True,
        )
        return [
            {
                "namespace": e.metadata.namespace,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "reason": e.reason,
                "message": e.message,
                "count": e.count,
                "last_seen": _age(e.last_timestamp or e.event_time),
            }
            for e in items[:MAX_ITEMS]
        ]

    def pod_logs(
        self, namespace: str, pod: str, container: str = "", tail: int = 100, previous: bool = False
    ) -> str:
        self._check(namespace)
        tail = max(1, min(int(tail), MAX_LOG_LINES))
        kwargs: dict[str, Any] = {"tail_lines": tail, "previous": previous}
        if container:
            kwargs["container"] = container
        return self._core.read_namespaced_pod_log(pod, namespace, **kwargs) or "(no output)"

    def tools(self) -> list[Tool]:
        ns = {"type": "string", "description": "Namespace. Empty means all allowed namespaces."}
        return [
            Tool(
                "k8s_nodes",
                "List nodes with Ready status, pressure conditions and kubelet version.",
                {"type": "object", "properties": {}},
                self.nodes,
            ),
            Tool(
                "k8s_unhealthy_pods",
                "List pods that are not running cleanly: pending, crash looping, not ready "
                "or restarting a lot.",
                {"type": "object", "properties": {"namespace": ns}},
                self.unhealthy_pods,
            ),
            Tool(
                "k8s_events",
                "List recent cluster events, newest first. Warnings only by default.",
                {
                    "type": "object",
                    "properties": {"namespace": ns, "warnings_only": {"type": "boolean"}},
                },
                self.events,
            ),
            Tool(
                "k8s_pod_logs",
                "Tail a pod's logs. Set previous=true to read the last crashed container.",
                {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod": {"type": "string"},
                        "container": {"type": "string"},
                        "tail": {"type": "integer", "description": f"Lines (<= {MAX_LOG_LINES})"},
                        "previous": {"type": "boolean"},
                    },
                    "required": ["namespace", "pod"],
                },
                self.pod_logs,
            ),
        ]
