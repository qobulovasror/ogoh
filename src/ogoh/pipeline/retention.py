"""Drop the bulky article text once an item is too old to ever be shown again.

raw_text is the one large column — up to 20k characters an item — and its whole
job is done the moment enrichment reads it: the summary, tags and entities are
derived and kept. Past every digest window (the widest is weekly, reaching eight
days) the text can neither be shown nor re-summarised, so holding it is pure
storage. Everything that makes an item searchable or countable stays; only the
prose goes.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, update
from sqlalchemy.orm import Session

from ogoh.db.models import AgentMessage, AgentQueryCache, AgentUsage, Item

log = logging.getLogger(__name__)


def prune_raw_text(session: Session, older_than_days: int) -> int:
    """Null raw_text on items older than the cutoff. Returns how many were pruned.

    text_extracted_at is stamped at the same time so the extractor treats the
    item as settled — without it, an item whose feed text was thick (and so was
    never extracted) would look thin again the moment its text went to NULL and
    get queued for a pointless refetch.
    """
    if older_than_days <= 0:
        return 0

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=older_than_days)

    result = session.execute(
        update(Item)
        .where(Item.fetched_at < cutoff)
        .where(Item.raw_text.is_not(None))
        .values(raw_text=None, text_extracted_at=func.coalesce(Item.text_extracted_at, now))
    )
    pruned = result.rowcount or 0
    if pruned:
        log.info("retention: pruned raw_text from %d old items", pruned)
    return pruned


def prune_agent_data(session: Session, retention_days: int, cache_ttl_hours: int) -> int:
    """Drop stale agent rows: old transcript and usage, and expired cache entries.

    The agent tables grow one row per question — small, but unbounded without
    this. The cache is cleared by its own TTL (expired rows are dead weight the
    read path already ignores); the transcript log and daily usage counters by the
    retention window. Returns the total rows deleted.
    """
    now = datetime.now(UTC)
    total = 0

    if cache_ttl_hours > 0:
        expired = session.execute(
            delete(AgentQueryCache).where(
                AgentQueryCache.created_at < now - timedelta(hours=cache_ttl_hours)
            )
        )
        total += expired.rowcount or 0

    if retention_days > 0:
        old_messages = session.execute(
            delete(AgentMessage).where(
                AgentMessage.created_at < now - timedelta(days=retention_days)
            )
        )
        total += old_messages.rowcount or 0

        old_usage = session.execute(
            delete(AgentUsage).where(AgentUsage.day < (now - timedelta(days=retention_days)).date())
        )
        total += old_usage.rowcount or 0

    if total:
        log.info("retention: pruned %d stale agent rows", total)
    return total
