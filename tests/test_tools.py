import json

import httpx
import pytest

from edge_sre_agent.config import Settings
from edge_sre_agent.tools import Tool, Toolbox, ToolError, build_toolbox, redact, truncate
from edge_sre_agent.tools.loki import Loki
from edge_sre_agent.tools.prometheus import Prometheus, _parse_duration


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_redacts_common_secrets():
    text = (
        "password=hunter2 token: abc123 Authorization: Bearer eyJhbGci.x.y "
        "AKIAABCDEFGHIJKLMNOP xoxb-123-456-abc"
    )
    out = redact(text)
    for secret in ("hunter2", "abc123", "eyJhbGci", "AKIAABCDEFGHIJKLMNOP", "xoxb-123"):
        assert secret not in out
    assert "password=[REDACTED]" in out


def test_truncate():
    assert truncate("abc", 10) == "abc"
    assert truncate("a" * 20, 5).startswith("aaaaa\n... [truncated 15 chars]")


def test_toolbox_redacts_and_truncates_output():
    box = Toolbox(
        [Tool("leak", "", {}, lambda: "secret=topsecret " + "x" * 100)], max_output_chars=40
    )
    out = box.call("leak", "{}")
    assert "topsecret" not in out
    assert "[truncated" in out


def test_toolbox_reports_bad_arguments():
    box = Toolbox([Tool("t", "", {}, lambda name: name)])
    assert box.call("t", '{"wrong": 1}').startswith("error:")
    assert box.call("t", "[1]") == "error: arguments must be a JSON object"


@pytest.mark.parametrize(
    "value,seconds", [("30s", 30), ("15m", 900), ("6h", 21600), ("2d", 172800)]
)
def test_parse_duration(value, seconds):
    assert _parse_duration(value) == seconds


def test_parse_duration_rejects_garbage():
    with pytest.raises(ToolError):
        _parse_duration("soon")


def test_prometheus_query_and_alerts():
    def handler(request):
        if request.url.path == "/api/v1/query":
            assert request.url.params["query"] == "up == 0"
            data = {
                "resultType": "vector",
                "result": [{"metric": {"instance": "site-12"}, "value": [1, "0"]}],
            }
        else:
            data = {
                "alerts": [
                    {
                        "labels": {"alertname": "NodeDown", "instance": "site-12"},
                        "state": "firing",
                        "activeAt": "2026-01-01T00:00:00Z",
                        "annotations": {"summary": "Node is down"},
                    }
                ]
            }
        return httpx.Response(200, json={"status": "success", "data": data})

    prom = Prometheus("http://prom/", client(handler))
    assert prom.query("up == 0") == {
        "series_total": 1,
        "series": [{"labels": {"instance": "site-12"}, "value": "0"}],
    }
    assert prom.alerts()[0]["name"] == "NodeDown"


def test_prometheus_query_range_summarises():
    def handler(request):
        result = [
            {"metric": {"job": "gpu"}, "values": [[1, "50"], [2, "NaN"], [3, "91"], [4, "80"]]}
        ]
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": "matrix", "result": result}}
        )

    out = Prometheus("http://prom", client(handler)).query_range("gpu_temp", since="1h")
    assert out["series"][0] == {
        "labels": {"job": "gpu"},
        "min": 50,
        "max": 91,
        "last": 80,
        "points": 3,
    }


def test_prometheus_error_is_tool_error():
    prom = Prometheus(
        "http://prom",
        client(lambda r: httpx.Response(400, json={"status": "error", "error": "parse error"})),
    )
    with pytest.raises(ToolError, match="parse error"):
        prom.query("up{")


def test_loki_returns_newest_first_and_caps_limit():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        result = [
            {"stream": {"pod": "api-1"}, "values": [["100", "old"], ["300", "newest"]]},
            {"stream": {"job": "edge"}, "values": [["200", "middle"]]},
        ]
        return httpx.Response(200, json={"data": {"result": result}})

    out = Loki("http://loki", client(handler)).query('{app="api"}', limit=10_000)
    assert seen["limit"] == "200"
    assert out["lines"] == ["[api-1] newest", "[edge] middle", "[api-1] old"]


def test_build_toolbox_only_enables_configured_backends():
    assert not build_toolbox(Settings())
    box = build_toolbox(Settings(prometheus_url="http://prom"), http=client(lambda r: None))
    assert box.names == ["prometheus_alerts", "prometheus_query", "prometheus_query_range"]
    assert json.dumps(box.schemas())
