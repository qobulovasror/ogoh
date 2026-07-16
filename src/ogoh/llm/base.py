from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class EnrichInput:
    index: int
    source: str
    title: str
    text: str


@dataclass(slots=True)
class Verdict:
    index: int
    importance: int
    summary: str
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


class LLMProvider(Protocol):
    """Free tiers change their terms; providers get swapped. Keep that a config edit."""

    model: str

    def classify_batch(self, items: list[EnrichInput]) -> list[Verdict]:
        """One verdict per item, matched back by index.

        May return fewer verdicts than items — callers must not assume alignment
        by position.
        """
        ...
