import logging
import re
import time
from datetime import UTC, datetime

import feedparser

from ogoh.sources.base import RawItem

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# One retry when a feed comes back with nothing, so that a blip does not get
# reported as a dead source. "This source returned nothing" is the alert that
# catches a feed going quietly to sleep — DeepMind's has been empty for months —
# and an alert that fires spuriously is one everybody learns to scroll past.
#
# It costs a pause only when a source is already empty, which should never be
# the normal case.
_RETRIES = 1
_RETRY_PAUSE_SECONDS = 3.0


class RssSource:
    """Reads any RSS or Atom feed. feedparser normalises the two for us."""

    kind = "rss"

    def __init__(self, name: str, url: str, trust_tier: int = 2) -> None:
        self.name = name
        self.url = url
        self.trust_tier = trust_tier

    def fetch(self) -> list[RawItem]:
        feed = feedparser.parse(self.url)

        for attempt in range(_RETRIES):
            if feed.entries:
                break
            log.debug("%s: no entries, retrying in %ss", self.name, _RETRY_PAUSE_SECONDS)
            time.sleep(_RETRY_PAUSE_SECONDS * (attempt + 1))
            feed = feedparser.parse(self.url)

        # feedparser sets bozo on malformed XML but still parses what it can, so a
        # bozo feed with entries is worth keeping. Only the entry count decides.
        if feed.bozo and not feed.entries:
            raise RuntimeError(f"{self.name}: unparseable feed ({feed.bozo_exception})")

        items = []
        for entry in feed.entries:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            items.append(
                RawItem(
                    url=link,
                    title=_clean(title),
                    published_at=_published(entry),
                    author=entry.get("author"),
                    text=_body(entry),
                )
            )
        return items


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=UTC)
    return None


def _body(entry) -> str | None:
    content = entry.get("content")
    if content:
        return _clean(content[0].get("value", ""))
    for key in ("summary", "description"):
        if entry.get(key):
            return _clean(entry[key])
    return None


def _clean(html: str) -> str:
    """Feeds ship HTML in text fields. The model only needs the prose."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()
