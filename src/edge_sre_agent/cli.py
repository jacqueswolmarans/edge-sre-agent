from __future__ import annotations

import argparse
import sys

from .agent import Agent, OpenAIChat, Step, describe_steps
from .config import Settings
from .tools import build_toolbox


def build_agent(settings: Settings) -> Agent:
    toolbox = build_toolbox(settings)
    if not toolbox:
        sys.exit("No backends configured. Set PROMETHEUS_URL, LOKI_URL or KUBERNETES_ENABLED=true.")
    chat = OpenAIChat(settings.llm_model, settings.llm_base_url, settings.llm_api_key)
    return Agent(chat, toolbox, settings.max_steps)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="edge-sre-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="Ask a one-off question from the terminal")
    ask.add_argument("question", nargs="+")
    ask.add_argument("-v", "--verbose", action="store_true", help="Print each tool call")
    sub.add_parser("slack", help="Run the Slack bot (Socket Mode)")
    sub.add_parser("tools", help="List the tools enabled by the current config")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.command == "tools":
        print("\n".join(build_toolbox(settings).names) or "(none configured)")
    elif args.command == "ask":
        agent = build_agent(settings)

        def show(step: Step) -> None:
            if args.verbose:
                print(f"  -> {step.tool} {step.arguments}", file=sys.stderr)

        result = agent.run(" ".join(args.question), on_step=show)
        print(result.answer)
        if args.verbose and result.steps:
            print("\n" + describe_steps(result.steps), file=sys.stderr)
    elif args.command == "slack":
        from .slack_app import run

        run(build_agent(settings))


if __name__ == "__main__":
    main()
