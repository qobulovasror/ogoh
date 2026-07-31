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

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ogoh.db.models import Item

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
