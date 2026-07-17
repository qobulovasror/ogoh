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

    # Set this when the URL alone does not tell two items apart. A changelog page
    # addresses each entry by anchor (…/release-notes/api#july-10-2026), and
    # canonicalisation drops fragments — rightly, since for an article a fragment
    # is noise — so every entry on that page would otherwise hash to one identity
    # and the source would yield exactly one item, forever. When uid is set,
    # ingest keys off it instead of the URL.
    uid: str | None = None


@runtime_checkable
class SourceFetcher(Protocol):
    """Adding a source means adding one file that satisfies this. Nothing else moves."""

    name: str
    kind: str
    url: str
    trust_tier: int

    def fetch(self) -> list[RawItem]: ...
