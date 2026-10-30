"""Slack front end. Mention the bot in a channel or DM it; it replies in thread."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from .agent import Agent, describe_steps

log = logging.getLogger(__name__)
MENTION = re.compile(r"<@[A-Z0-9]+>")
MAX_HISTORY = 10


def thread_history(client: Any, channel: str, thread_ts: str, bot_user: str, current_ts: str):
    """Earlier messages in the thread, so follow-up questions keep their context."""
    replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=50)["messages"]
    history = []
    for message in replies:
        if message.get("ts") == current_ts or not message.get("text"):
            continue
        role = "assistant" if message.get("user") == bot_user or message.get("bot_id") else "user"
        history.append({"role": role, "content": MENTION.sub("", message["text"]).strip()})
    return history[-MAX_HISTORY:]


def build_app(agent: Agent):
    from slack_bolt import App

    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    bot_user = app.client.auth_test()["user_id"]

    def handle(event: dict[str, Any], client: Any) -> None:
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        question = MENTION.sub("", event.get("text", "")).strip()
        if not question:
            return
        history = []
        if event.get("thread_ts"):
            history = thread_history(client, channel, thread_ts, bot_user, event["ts"])
        placeholder = client.chat_postMessage(
            channel=channel, thread_ts=thread_ts, text=":mag: Investigating..."
        )
        try:
            result = agent.run(question, history=history)
            text = result.answer or "I couldn't come up with an answer."
            if result.steps:
                text += f"\n\n_Checked {len(result.steps)} things:_\n{describe_steps(result.steps)}"
        except Exception:
            log.exception("agent run failed")
            text = ":warning: Something went wrong while investigating. Check the bot logs."
        client.chat_update(channel=channel, ts=placeholder["ts"], text=text)

    @app.event("app_mention")
    def on_mention(event, client):
        handle(event, client)

    @app.event("message")
    def on_dm(event, client):
        if (
            event.get("channel_type") == "im"
            and not event.get("bot_id")
            and not event.get("subtype")
        ):
            handle(event, client)

    return app


def run(agent: Agent) -> None:
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    SocketModeHandler(build_app(agent), os.environ["SLACK_APP_TOKEN"]).start()
