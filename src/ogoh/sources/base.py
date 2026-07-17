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

    # Assert this only when `text` is genuinely the entire item and fetching
    # `url` could not improve on it. Feeds cannot know — the RSS spec's own
    # signal is useless here, since Simon Willison puts full posts in <summary>
    # while Ars Technica truncates inside <content> — so only a source that
    # assembled the text itself should claim it.
    text_is_complete: bool = False


@runtime_checkable
class SourceFetcher(Protocol):
    """Adding a source means adding one file that satisfies this. Nothing else moves."""

    name: str
    kind: str
    url: str
    trust_tier: int

    def fetch(self) -> list[RawItem]: ...
