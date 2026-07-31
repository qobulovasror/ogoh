"""Shared shapes for the agent loop.

The model returns one AgentAction per step; the runner executes it and feeds the
result back. Keeping the action flat and small keeps each step's output cheap.
"""

from dataclasses import dataclass, field
from typing import Protocol

ACTIONS = ("search_corpus", "web_search", "fetch_page", "ask_user", "final_answer")


@dataclass(slots=True)
class AgentAction:
    action: str
    # What `text` means depends on `action`: the query to run, the question to
    # ask, or the answer to give.
    text: str = ""
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Turn:
    role: str  # "user" | "assistant" | "tool"
    content: str


@dataclass(slots=True)
class AgentReply:
    kind: str  # "answer" | "question"
    text: str
    sources: list[str] = field(default_factory=list)


class AgentBrain(Protocol):
    """Whatever decides the next step. GeminiProvider in production, a fake in tests."""

    model: str

    def agent_step(self, system: str, transcript: str) -> AgentAction:
        ...
