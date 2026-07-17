"""Level-2 dedupe: fold near-identical headlines into one cluster.

Level 1 — the canonical URL hash in ingest — catches the same URL arriving twice.
This catches the same story republished under a near-identical headline.

On the threshold. Measured over a live sample of 99 items, true and false
duplicate pairs sit only 0.17 apart:

    0.67  "xai-org/grok-build, now open source" / "Grok Build is open source"
          -> the same story, two sources
    0.50  "How sales teams use ChatGPT Work" / "How data science teams use
          ChatGPT Work" -> different articles in one series

A mid-range threshold would be a coin flip on any other day's distribution, so
this merges only what is near-certain and accepts the misses. The asymmetry
decides it: a false merge silently deletes a story the reader never learns was
published, while a false split only shows them the same thing twice. Semantic
pairs like the grok-build one need embeddings — that is P2's job, not a threshold
tuned against one afternoon's news.

Simhash, which the plan originally called for, is the wrong tool here. It earns
its keep on long documents and on corpora big enough to need LSH banding. These
are headlines — a handful of tokens — and one run compares ~100 new items against
a couple of hundred recent ones. Brute-force set overlap is both more accurate on
short strings and completely free at this size.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.config import get_settings
from ogoh.db.models import Item

log = logging.getLogger(__name__)

THRESHOLD = 0.85

# Versions stay whole: splitting "4.1.1" into digits made it identical to "4.0"
# once stop-word filtering removed the parts, merging three distinct releases.
_TOKEN = re.compile(r"[a-z]+|[0-9]+(?:\.[0-9]+)*")

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
        "have", "how", "in", "is", "it", "its", "new", "now", "of", "on", "or",
        "the", "to", "use", "with",
    }
)


@dataclass(slots=True)
class DedupeStats:
    clustered: int = 0
    merged: int = 0


def assign_clusters(session: Session, within_hours: int | None = None) -> DedupeStats:
    """Cluster every stored item, not just the ones today's digest would show.

    The window defaults to everything ingest keeps. Tying it to a narrower span —
    48h, say, to match a daily digest — leaves older items with a NULL cluster,
    and then a weekly subscriber gets served the duplicates that were never
    compared. The comparison is set overlap over a few hundred items; making it
    exhaustive costs nothing and removes the whole class of window-mismatch bugs.
    """
    hours = within_hours if within_hours is not None else get_settings().max_age_days * 24
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    published = func.coalesce(Item.published_at, Item.fetched_at)

    # Oldest first, so the earliest publisher of a story becomes its canonical
    # item and later republishers fold into it.
    candidates = session.scalars(
        select(Item).where(published >= cutoff).order_by(published.asc(), Item.id.asc())
    ).all()

    stats = DedupeStats()
    seen: list[tuple[frozenset[str], int]] = []

    for item in candidates:
        tokens = title_tokens(item.title)

        # Items clustered on an earlier run keep their assignment and stay
        # matchable, so a rerun published tomorrow still finds today's story.
        if item.cluster_id is not None:
            if tokens:
                seen.append((tokens, item.cluster_id))
            continue

        if not tokens:
            item.cluster_id = item.id
            continue

        match = _closest(tokens, seen)
        if match is None:
            item.cluster_id = item.id
            seen.append((tokens, item.id))
            stats.clustered += 1
        else:
            item.cluster_id = match
            stats.merged += 1
            log.info("dedupe: %r folded into cluster %d", item.title, match)

    session.flush()
    return stats


def _closest(tokens: frozenset[str], seen: list[tuple[frozenset[str], int]]) -> int | None:
    for other_tokens, cluster_id in seen:
        if jaccard(tokens, other_tokens) >= THRESHOLD:
            return cluster_id
    return None


def title_tokens(title: str) -> frozenset[str]:
    # NFKD folds typographic variants apart that render identically. The same
    # headline reached us as "Introducing GPT-Live" from one source and
    # "Introducing GPT‑Live" — U+2011, a non-breaking hyphen — from another.
    folded = unicodedata.normalize("NFKD", title)
    folded = folded.replace("‑", "-").replace("‐", "-")
    return frozenset(t for t in _TOKEN.findall(folded.lower()) if t not in _STOPWORDS)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
