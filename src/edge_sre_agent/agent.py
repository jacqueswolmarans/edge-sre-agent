from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .tools import Toolbox

SYSTEM_PROMPT = """\
You are an on-call SRE assistant for a fleet of Kubernetes clusters, some running in the
cloud and some on small servers at remote sites.

How to work:
- Investigate before answering. Start broad (firing alerts, unhealthy pods, node status),
  then narrow down with metrics and logs.
- You only have read-only tools. Never claim you changed anything. Suggest commands for a
  human to run instead.
- Cite the evidence you used: the query, the pod, the log line.
- If a tool returns an error, adjust and try again, or say what you could not check.
- Keep the final answer short and suited to Slack:
  *Summary* - one or two sentences.
  *Evidence* - up to five bullets.
  *Next steps* - up to three bullets.
"""


class ChatClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any: ...


@dataclass
class Step:
    tool: str
    arguments: str
    output: str


@dataclass
class Result:
    answer: str
    steps: list[Step] = field(default_factory=list)
    hit_step_limit: bool = False


class OpenAIChat:
    """Any OpenAI-compatible endpoint: OpenAI, Azure, Ollama, vLLM, Gemini, OpenRouter."""

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None) -> None:
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        self._model = model

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": 0}
        if tools:
            kwargs["tools"] = tools
        return self._client.chat.completions.create(**kwargs).choices[0].message


class Agent:
    def __init__(self, chat: ChatClient, toolbox: Toolbox, max_steps: int = 8) -> None:
        self._chat = chat
        self._toolbox = toolbox
        self._max_steps = max_steps

    def run(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        on_step: Callable[[Step], None] | None = None,
    ) -> Result:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += history or []
        messages.append({"role": "user", "content": question})
        steps: list[Step] = []

        for _ in range(self._max_steps):
            reply = self._chat.complete(messages, self._toolbox.schemas())
            tool_calls = list(getattr(reply, "tool_calls", None) or [])
            if not tool_calls:
                return Result(answer=(reply.content or "").strip(), steps=steps)

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                output = self._toolbox.call(call.function.name, call.function.arguments)
                step = Step(call.function.name, call.function.arguments, output)
                steps.append(step)
                if on_step:
                    on_step(step)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

        messages.append(
            {
                "role": "user",
                "content": "Step limit reached. Answer now with what you have, and say what "
                "you could not check.",
            }
        )
        reply = self._chat.complete(messages, [])
        return Result(answer=(reply.content or "").strip(), steps=steps, hit_step_limit=True)


def describe_steps(steps: list[Step]) -> str:
    lines = []
    for step in steps:
        try:
            args = json.loads(step.arguments or "{}")
        except ValueError:
            args = step.arguments
        detail = ", ".join(f"{k}={v}" for k, v in args.items()) if isinstance(args, dict) else args
        status = "error" if step.output.startswith("error:") else "ok"
        lines.append(f"- `{step.tool}`({detail}) -> {status}")
    return "\n".join(lines)
