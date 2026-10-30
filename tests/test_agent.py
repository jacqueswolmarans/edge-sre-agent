from types import SimpleNamespace as NS

from edge_sre_agent.agent import Agent, describe_steps
from edge_sre_agent.tools import Tool, Toolbox


def call(id_, name, arguments):
    return NS(id=id_, function=NS(name=name, arguments=arguments))


class ScriptedChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def toolbox():
    return Toolbox(
        [
            Tool(
                "alerts",
                "firing alerts",
                {"type": "object", "properties": {}},
                lambda: [{"name": "NodeDown", "instance": "site-12"}],
            ),
            Tool(
                "echo",
                "echo",
                {"type": "object", "properties": {"text": {"type": "string"}}},
                lambda text: text,
            ),
        ]
    )


def test_runs_tools_then_answers():
    chat = ScriptedChat(
        [
            NS(content=None, tool_calls=[call("1", "alerts", "{}")]),
            NS(content="*Summary* site-12 is down.", tool_calls=None),
        ]
    )
    result = Agent(chat, toolbox()).run("what's broken?")

    assert result.answer == "*Summary* site-12 is down."
    assert [s.tool for s in result.steps] == ["alerts"]
    assert "NodeDown" in result.steps[0].output
    tool_message = chat.calls[1]["messages"][-1]
    assert tool_message == {"role": "tool", "tool_call_id": "1", "content": result.steps[0].output}


def test_history_is_included():
    chat = ScriptedChat([NS(content="ok", tool_calls=None)])
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    Agent(chat, toolbox()).run("follow up", history=history)

    roles = [m["role"] for m in chat.calls[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_step_limit_forces_answer_without_tools():
    looping = NS(content=None, tool_calls=[call("x", "echo", '{"text": "hi"}')])
    chat = ScriptedChat([looping, looping, NS(content="partial answer", tool_calls=None)])
    result = Agent(chat, toolbox(), max_steps=2).run("loop")

    assert result.hit_step_limit
    assert result.answer == "partial answer"
    assert chat.calls[-1]["tools"] == []


def test_bad_tool_calls_are_reported_to_model():
    chat = ScriptedChat(
        [
            NS(content=None, tool_calls=[call("1", "nope", "{}"), call("2", "echo", "not json")]),
            NS(content="done", tool_calls=None),
        ]
    )
    result = Agent(chat, toolbox()).run("q")

    assert result.steps[0].output.startswith("error: unknown tool")
    assert result.steps[1].output.startswith("error:")
    assert "-> error" in describe_steps(result.steps)
