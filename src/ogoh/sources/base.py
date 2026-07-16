from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class RawItem:
    """One item as the source handed it over, before any normalisation."""

    url: str
    title: str
    published_at: datetime | None = None
    author: str | None = None
    text: str | None = None


@runtime_checkable
class SourceFetcher(Protocol):
    """Adding a source means adding one file that satisfies this. Nothing else moves."""

    name: str
    kind: str
    url: str
    trust_tier: int

    def fetch(self) -> list[RawItem]: ...
