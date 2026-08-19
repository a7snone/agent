"""A minimal tool-use agent built on the Anthropic Messages API.

Run it interactively:
    python agent.py

Extend it by adding tools in tools.py — nothing here needs to change when
you add a new tool.
"""

from __future__ import annotations

import os
import sys

from anthropic import Anthropic

from tools import TOOLS, TOOL_FUNCTIONS

MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-5")
SYSTEM_PROMPT = (
    "You are a helpful agent with access to a small set of tools. "
    "Use tools when they help answer the user accurately; otherwise answer directly. "
    "Be concise."
)
MAX_TOOL_ITERATIONS = 10


class Agent:
    def __init__(self, client: Anthropic | None = None):
        self.client = client or Anthropic()
        self.messages: list[dict] = []

    def _run_tool(self, name: str, tool_input: dict) -> str:
        func = TOOL_FUNCTIONS.get(name)
        if func is None:
            return f"Error: unknown tool '{name}'"
        try:
            return str(func(**tool_input))
        except Exception as exc:
            return f"Error running tool '{name}': {exc}"

    def send(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return "".join(block.text for block in response.content if block.type == "text")

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = self._run_tool(block.name, block.input)
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
            self.messages.append({"role": "user", "content": tool_results})

        return "Stopped: reached the maximum number of tool-use iterations."


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set the ANTHROPIC_API_KEY environment variable first (see .env.example).")
        sys.exit(1)

    agent = Agent()
    print(f"Agent ready (model: {MODEL}). Type 'exit' to quit.")
    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_text.lower() in {"exit", "quit"}:
            break
        if not user_text:
            continue
        reply = agent.send(user_text)
        print(f"\nAgent: {reply}")


if __name__ == "__main__":
    main()
