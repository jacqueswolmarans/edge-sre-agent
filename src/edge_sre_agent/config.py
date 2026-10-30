from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    prometheus_url: str | None = None
    loki_url: str | None = None
    kubernetes_enabled: bool = False
    kube_context: str | None = None
    allowed_namespaces: list[str] = field(default_factory=list)
    max_steps: int = 8
    max_tool_output_chars: int = 6000
    http_timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            llm_model=env.get("LLM_MODEL", cls.llm_model),
            llm_base_url=env.get("LLM_BASE_URL") or None,
            llm_api_key=env.get("LLM_API_KEY") or env.get("OPENAI_API_KEY") or None,
            prometheus_url=env.get("PROMETHEUS_URL") or None,
            loki_url=env.get("LOKI_URL") or None,
            kubernetes_enabled=env.get("KUBERNETES_ENABLED", "false").lower()
            in {"1", "true", "yes"},
            kube_context=env.get("KUBE_CONTEXT") or None,
            allowed_namespaces=_list(env.get("ALLOWED_NAMESPACES")),
            max_steps=int(env.get("MAX_STEPS", cls.max_steps)),
            max_tool_output_chars=int(env.get("MAX_TOOL_OUTPUT_CHARS", cls.max_tool_output_chars)),
            http_timeout_seconds=float(env.get("HTTP_TIMEOUT_SECONDS", cls.http_timeout_seconds)),
        )
