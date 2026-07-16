import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ogoh.db.models import Item, ItemEnrichment
from ogoh.llm.base import EnrichInput, LLMProvider
from ogoh.taxonomy import TAG_KEYS

log = logging.getLogger(__name__)


@dataclass(slots=True)
class EnrichStats:
    enriched: int = 0
    batches: int = 0
    skipped: int = 0


def enrich_pending(
    session: Session,
    provider: LLMProvider,
    batch_size: int,
    limit: int | None = None,
) -> EnrichStats:
    pending = _pending(session, limit)
    stats = EnrichStats()

    for batch in _chunks(pending, batch_size):
        inputs = [
            EnrichInput(
                index=position,
                source=item.source.name,
                title=item.title,
                text=item.raw_text or "",
            )
            for position, item in enumerate(batch)
        ]

        try:
            verdicts = provider.classify_batch(inputs)
        except Exception:
            # Leave the batch unenriched; the next run picks it up again.
            log.exception("classify failed for a batch of %d items", len(batch))
            stats.skipped += len(batch)
            continue

        stats.batches += 1
        by_index = {verdict.index: verdict for verdict in verdicts}

        for position, item in enumerate(batch):
            verdict = by_index.get(position)
            if verdict is None:
                # The model dropped one. Never fall back to positional matching:
                # a short list would silently attach the wrong summary to an item.
                log.warning("no verdict returned for item %d (%r)", item.id, item.title)
                stats.skipped += 1
                continue

            tags = [tag for tag in verdict.tags if tag in TAG_KEYS]
            invented = set(verdict.tags) - TAG_KEYS
            if invented:
                log.warning("item %d: dropped tags outside taxonomy: %s", item.id, sorted(invented))

            session.add(
                ItemEnrichment(
                    item_id=item.id,
                    tags=tags,
                    entities=verdict.entities[:5],
                    importance=verdict.importance,
                    summary=verdict.summary,
                    model_used=provider.model,
                    enriched_at=datetime.now(UTC),
                )
            )
            stats.enriched += 1

        session.flush()

    return stats


def _pending(session: Session, limit: int | None) -> Sequence[Item]:
    stmt = (
        select(Item)
        .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(ItemEnrichment.item_id.is_(None))
        .order_by(Item.published_at.desc().nullslast(), Item.id.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return session.scalars(stmt).all()


def _chunks(items: Sequence[Item], size: int) -> Iterator[Sequence[Item]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
