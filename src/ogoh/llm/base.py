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


@dataclass(slots=True)
class PairInput:
    index: int
    left_title: str
    right_title: str


@dataclass(slots=True)
class PairVerdict:
    index: int
    same_event: bool
    reason: str = ""


class LLMProvider(Protocol):
    """Free tiers change their terms; providers get swapped. Keep that a config edit."""

    model: str

    def classify_batch(self, items: list[EnrichInput]) -> list[Verdict]:
        """One verdict per item, matched back by index.

        May return fewer verdicts than items — callers must not assume alignment
        by position.
        """
        ...

    def judge_pairs(self, pairs: list[PairInput]) -> list[PairVerdict]:
        """Did these two headlines report the same event, or two different ones?

        Same index contract as classify_batch: match by index, never by position.
        """
        ...
