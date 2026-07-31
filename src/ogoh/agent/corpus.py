"""Answer from our own store before reaching for the web.

An AI-news question — "what's the latest Claude model", "did OpenAI change
pricing" — is usually already sitting enriched in the database, with full text and
a fortnight of history. Checking here first is free and often enough, and it is
the same corpus-over-search choice research.py already made.

Scoring is a Python loop over a few hundred recent rows: term overlap on the
title, summary and entities. At this scale that is more accurate than a portable
SQL LIKE across SQLite and Postgres, and costs nothing.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.db.models import Item, ItemEnrichment
from ogoh.pipeline.dedupe import title_tokens

_SCAN_LIMIT = 200


@dataclass(slots=True)
class CorpusHit:
    title: str
    url: str
    summary: str
    source: str
    published: str


def search_corpus(session: Session, query: str, days: int = 14, limit: int = 5) -> list[CorpusHit]:
    terms = title_tokens(query)
    if not terms:
        return []

    cutoff = datetime.now(UTC) - timedelta(days=days)
    published = func.coalesce(Item.published_at, Item.fetched_at)
    rows = session.execute(
        select(Item, ItemEnrichment)
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(published >= cutoff)
        .order_by(published.desc())
        .limit(_SCAN_LIMIT)
    ).all()

    scored: list[tuple[int, Item, ItemEnrichment]] = []
    for item, enrichment in rows:
        haystack = title_tokens(
            f"{item.title} {enrichment.summary or ''} {' '.join(enrichment.entities or [])}"
        )
        overlap = len(terms & haystack)
        if overlap:
            scored.append((overlap, item, enrichment))

    scored.sort(key=lambda row: -row[0])
    return [
        CorpusHit(
            title=item.title,
            url=item.url,
            summary=enrichment.summary,
            source=item.source.name,
            published=item.published_at.date().isoformat() if item.published_at else "",
        )
        for _, item, enrichment in scored[:limit]
    ]
