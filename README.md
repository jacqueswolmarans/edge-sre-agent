# edge-sre-agent

An on-call sidekick for Kubernetes fleets. Ask it a question in Slack, and it checks
Prometheus, Loki and your clusters, then answers in thread with the evidence it used.

```
you:   @sre what's going on with site-07?
agent: :mag: Investigating...

       *Summary* site-07 stopped reporting 14 minutes ago and its log shipper is
       throwing TLS handshake errors. Looks like an expired client cert, not a
       hardware fault.

       *Evidence*
       - Alert `TargetDown` firing for job=edge-site-07 since 09:12
       - `up{job="edge-site-07"}` = 0, was 1 for the previous 6h
       - 38 log lines matching "x509: certificate has expired" in the last 15m

       *Next steps*
       - Check the cert expiry on the site's shipper
       - Re-issue and restart the shipper pod

       _Checked 4 things:_
       - `prometheus_alerts`() -> ok
       - `prometheus_query_range`(query=up{job="edge-site-07"}, since=6h) -> ok
       - `loki_labels`() -> ok
       - `loki_query`(query={job="edge-site-07"} |= "error", since=15m) -> ok
```

Built for fleets where some clusters live in the cloud and others sit on small boxes at
remote sites. Works just as well with a single cluster.

## Why it is safe to point at production

- **Read-only.** There are no tools that change anything. The agent suggests commands for
  a human to run.
- **No secrets.** There is no tool for Secrets or ConfigMaps. Tool output is scrubbed for
  common credential patterns (passwords, bearer tokens, AWS keys, Slack tokens) before the
  model sees it.
- **Bounded.** Namespace allowlist, capped log lines, capped series, capped output size,
  and a step limit per question.
- **Least privilege.** The [RBAC manifest](deploy/rbac.yaml) grants `get`/`list` on nodes,
  pods, pod logs and events, and nothing else.
- **Transparent.** Every answer lists the tool calls it made.

## Tools

| Backend | Tools |
| --- | --- |
| Prometheus | `prometheus_alerts`, `prometheus_query`, `prometheus_query_range` |
| Loki | `loki_labels`, `loki_query` |
| Kubernetes | `k8s_nodes`, `k8s_unhealthy_pods`, `k8s_events`, `k8s_pod_logs` |

Each backend is enabled only when configured. Adding a tool is a small class with a
`tools()` method; see [`tools/loki.py`](src/edge_sre_agent/tools/loki.py).

## Try it in two minutes

The demo stack runs Prometheus, Loki, a deliberately broken "edge site" and a noisy app,
so there is something to investigate. It needs Docker and an API key for any
OpenAI-compatible model.

```bash
cp .env.example .env    # add LLM_API_KEY, or point LLM_BASE_URL at Ollama
docker compose -f demo/compose.yaml up -d --build
docker compose -f demo/compose.yaml run --rm agent ask -v "Anything broken right now?"
```

Give the alert a minute to fire on first start.

## Run against your own stack

```bash
uv sync
export LLM_API_KEY=...
export PROMETHEUS_URL=http://prometheus:9090
export LOKI_URL=http://loki:3100
export KUBERNETES_ENABLED=true           # uses in-cluster config or ~/.kube/config
export ALLOWED_NAMESPACES=default,monitoring

uv run edge-sre-agent tools              # what's enabled
uv run edge-sre-agent ask -v "why is the api pod restarting?"
```

### Model

Any OpenAI-compatible chat API with tool calling works.

| Provider | `LLM_BASE_URL` | `LLM_MODEL` |
| --- | --- | --- |
| OpenAI | (unset) | `gpt-4o-mini` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:14b` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| OpenRouter | `https://openrouter.ai/api/v1` | any tool-capable model |

Running a local model keeps logs and metrics inside your network.

### Slack

1. Create an app from [`deploy/slack-manifest.yaml`](deploy/slack-manifest.yaml).
2. Generate an app-level token with `connections:write` (`SLACK_APP_TOKEN`, `xapp-...`).
3. Install it to your workspace and copy the bot token (`SLACK_BOT_TOKEN`, `xoxb-...`).
4. `uv run edge-sre-agent slack`

It uses Socket Mode, so it needs no public URL or inbound firewall rule. Mention it in a
channel or DM it. Follow-ups in the same thread keep their context.

### Kubernetes

[`deploy/`](deploy) has a read-only ServiceAccount and a Deployment. Build the image with
the included `Dockerfile` and put your tokens in a Secret called `edge-sre-agent`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_MODEL` | `gpt-4o-mini` | Model name |
| `LLM_BASE_URL` | OpenAI | OpenAI-compatible endpoint |
| `LLM_API_KEY` | | API key (falls back to `OPENAI_API_KEY`) |
| `PROMETHEUS_URL` | | Enables Prometheus tools |
| `LOKI_URL` | | Enables Loki tools |
| `KUBERNETES_ENABLED` | `false` | Enables Kubernetes tools |
| `KUBE_CONTEXT` | current | kubeconfig context when running outside a cluster |
| `ALLOWED_NAMESPACES` | all | Comma-separated namespace allowlist |
| `MAX_STEPS` | `8` | Tool-calling rounds per question |
| `MAX_TOOL_OUTPUT_CHARS` | `6000` | Truncation limit per tool result |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | | Slack mode only |

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Ideas

- Tailscale tool: which sites are offline on the tailnet
- Argo CD tool: out-of-sync or degraded apps
- Post a first-pass triage automatically when an Alertmanager alert fires

## Licence

MIT
