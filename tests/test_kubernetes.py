from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from edge_sre_agent.tools import ToolError
from edge_sre_agent.tools.kubernetes import Kubernetes

NOW = datetime.now(UTC)


def pod(ns, name, phase="Running", ready=True, restarts=0, waiting=None):
    state = NS(waiting=NS(reason=waiting) if waiting else None)
    status = NS(name="main", ready=ready, restart_count=restarts, state=state)
    return NS(
        metadata=NS(namespace=ns, name=name, creation_timestamp=NOW - timedelta(hours=2)),
        status=NS(phase=phase, container_statuses=[status]),
        spec=NS(node_name="node-a"),
    )


class FakeCore:
    def __init__(self):
        self.pods = [
            pod("app", "healthy"),
            pod("app", "crashy", ready=False, restarts=7, waiting="CrashLoopBackOff"),
            pod("app", "pending", phase="Pending", ready=False),
            pod("kube-system", "flaky", restarts=4),
            pod("secret-ns", "hidden", phase="Failed", ready=False),
            pod("app", "finished-job", phase="Succeeded", ready=False),
        ]
        self.log_calls = []

    def list_pod_for_all_namespaces(self):
        return NS(items=self.pods)

    def list_namespaced_pod(self, namespace):
        return NS(items=[p for p in self.pods if p.metadata.namespace == namespace])

    def list_node(self):
        conditions = [NS(type="Ready", status="False"), NS(type="DiskPressure", status="True")]
        node = NS(
            metadata=NS(name="node-a", creation_timestamp=NOW - timedelta(days=3)),
            status=NS(conditions=conditions, node_info=NS(kubelet_version="v1.30.4+k3s1")),
            spec=NS(unschedulable=None),
        )
        return NS(items=[node])

    def read_namespaced_pod_log(self, pod, namespace, **kwargs):
        self.log_calls.append(kwargs)
        return "boom"


def test_unhealthy_pods_filters_healthy_and_disallowed_namespaces():
    k8s = Kubernetes(FakeCore(), allowed_namespaces=["app", "kube-system"])
    names = {p["pod"] for p in k8s.unhealthy_pods()}
    assert names == {"crashy", "pending", "flaky"}


def test_namespace_allowlist_is_enforced():
    k8s = Kubernetes(FakeCore(), allowed_namespaces=["app"])
    with pytest.raises(ToolError, match="not allowed"):
        k8s.pod_logs("secret-ns", "hidden")
    with pytest.raises(ToolError):
        k8s.unhealthy_pods("kube-system")


def test_nodes_report_pressure():
    node = Kubernetes(FakeCore()).nodes()[0]
    assert node["ready"] is False
    assert node["pressure"] == ["DiskPressure"]
    assert node["age"] == "3d"


def test_pod_logs_caps_tail():
    core = FakeCore()
    assert Kubernetes(core).pod_logs("app", "crashy", tail=99999, previous=True) == "boom"
    assert core.log_calls[0] == {"tail_lines": 300, "previous": True}


def test_no_tool_can_read_secrets():
    names = [tool.name for tool in Kubernetes(FakeCore()).tools()]
    assert not any("secret" in name or "configmap" in name for name in names)
