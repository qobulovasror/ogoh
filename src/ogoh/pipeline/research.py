"""The deep dive: the day's biggest story, with what led up to it.

The plan wanted this built on Gemini's google_search grounding. That is not
available here — a free-tier key answers 429 to the very first grounded call
while an ordinary call on the same key succeeds, so the allowance the docs
describe belongs to projects with billing enabled, not to the no-card tier this
runs on. Measured, not assumed.

So the research reads our own corpus instead, which turns out to suit the job
better than a web search would. We already hold the full text of every article
across twelve sources, clustered by story, going back a fortnight, with the
organisations and products each one names. A general search would return the same
launch posts we already have, ranked by a stranger; what a reader actually cannot
assemble is the history — the four earlier items that explain why today's
announcement matters. That is here, and nowhere else.

One call a day. The summary says what happened; this says what it means.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.db.models import ClusterResearch, Item, ItemEnrichment
from ogoh.llm.base import LLMProvider, ResearchInput, ResearchSource

log = logging.getLogger(__name__)

# Only a story worth the extra call. Anything below this is a summary's work.
MIN_IMPORTANCE = 8

# The story's own coverage, then the run-up. Both capped: the prompt has to stay
# a prompt, and the fifth outlet's rewrite adds nothing the first four did not.
MAX_COVERAGE = 4
MAX_BACKGROUND = 6
_TEXT_PER_SOURCE = 3_000
_BACKGROUND_DAYS = 30


@dataclass(slots=True)
class ResearchStats:
    written: int = 0
    skipped: int = 0


def research_top_stories(
    session: Session,
    provider: LLMProvider,
    limit: int = 1,
    # Matches the daily digest window. A shorter one writes up a story that has
    # aged past the digest by the time it is due, and the write-up is never seen.
    within_hours: int = 48,
) -> ResearchStats:
    stats = ResearchStats()

    # Over-fetch, then skip what is already written. Asking for exactly `limit`
    # candidates means the same top story is picked every run and the second and
    # third biggest of the day are never reached at all.
    for cluster_id in _todays_biggest(session, limit * 4, within_hours):
        if stats.written >= limit:
            break
        if session.get(ClusterResearch, cluster_id) is not None:
            continue

        payload = _gather(session, cluster_id)
        if payload is None:
            stats.skipped += 1
            continue

        try:
            result = provider.research(payload)
        except Exception:
            log.exception("research: could not write up cluster %d", cluster_id)
            stats.skipped += 1
            continue

        session.add(
            ClusterResearch(
                cluster_id=cluster_id,
                body=result.body,
                body_uz=result.body_uz or None,
                model_used=provider.model,
                created_at=datetime.now(UTC),
            )
        )
        stats.written += 1
        log.info("research: wrote up cluster %d (%s)", cluster_id, payload.headline)

    session.flush()
    return stats


def _todays_biggest(session: Session, limit: int, within_hours: int) -> list[int]:
    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    published = func.coalesce(Item.published_at, Item.fetched_at)
    cluster = func.coalesce(Item.cluster_id, Item.id)

    rows = session.execute(
        select(cluster, func.max(ItemEnrichment.importance).label("top"))
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(published >= cutoff)
        .where(ItemEnrichment.importance >= MIN_IMPORTANCE)
        .group_by(cluster)
        .order_by(func.max(ItemEnrichment.importance).desc())
        .limit(limit)
    ).all()
    return [row[0] for row in rows]


def _gather(session: Session, cluster_id: int) -> ResearchInput | None:
    """Everything we hold about this story, plus the run-up to it."""
    members = session.scalars(
        select(Item)
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(func.coalesce(Item.cluster_id, Item.id) == cluster_id)
        .order_by(Item.source.has(), ItemEnrichment.importance.desc())
    ).all()
    if not members:
        return None

    lead = members[0]
    lead_enrichment = session.get(ItemEnrichment, lead.id)
    if lead_enrichment is None:
        return None

    entities = set(lead_enrichment.entities or [])

    coverage = [
        ResearchSource(source=item.source.name, title=item.title, text=_clip(item.raw_text))
        for item in members[:MAX_COVERAGE]
    ]

    return ResearchInput(
        headline=lead.title,
        entities=sorted(entities),
        coverage=coverage,
        background=_background(session, cluster_id, entities),
    )


def _background(
    session: Session, cluster_id: int, entities: set[str]
) -> list[ResearchSource]:
    """Earlier stories about the same organisations and products.

    This is the part a web search could not assemble: what these people shipped
    and said in the weeks before today, from the same corpus, already read.
    """
    if not entities:
        return []

    cutoff = datetime.now(UTC) - timedelta(days=_BACKGROUND_DAYS)
    published = func.coalesce(Item.published_at, Item.fetched_at)

    rows = session.execute(
        select(Item, ItemEnrichment)
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(func.coalesce(Item.cluster_id, Item.id) != cluster_id)
        .where(published >= cutoff)
        .order_by(published.desc())
        .limit(200)
    ).all()

    # Entity overlap in Python: `entities` is a JSON column, and the portable
    # containment query across SQLite and Postgres is not worth writing for a
    # couple of hundred rows.
    matched = []
    for item, enrichment in rows:
        if entities.intersection(enrichment.entities or []):
            matched.append(
                ResearchSource(
                    source=item.source.name,
                    title=item.title,
                    text=enrichment.summary,
                    published=item.published_at.date().isoformat() if item.published_at else "",
                )
            )
        if len(matched) >= MAX_BACKGROUND:
            break
    return matched


def _clip(text: str | None) -> str:
    if not text:
        return ""
    return text[:_TEXT_PER_SOURCE]
