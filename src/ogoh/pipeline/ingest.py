import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ogoh.config import get_settings
from ogoh.db.models import Item, Source
from ogoh.pipeline.normalize import canonicalize_url, url_hash
from ogoh.sources.base import RawItem, SourceFetcher
from ogoh.sources.registry import FETCHERS

log = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 20_000


@dataclass(slots=True)
class IngestStats:
    new: int = 0
    duplicate: int = 0
    too_old: int = 0
    failed_sources: list[str] = field(default_factory=list)
    empty_sources: list[str] = field(default_factory=list)


def ingest_all(session: Session, fetchers: tuple[SourceFetcher, ...] = FETCHERS) -> IngestStats:
    stats = IngestStats()
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().max_age_days)

    for fetcher in fetchers:
        source = _upsert_source(session, fetcher)
        if not source.enabled:
            continue

        try:
            raw_items = fetcher.fetch()
        except Exception:
            # One bad feed must not take the run down — the other four still have news.
            log.exception("source %r failed to fetch", fetcher.name)
            stats.failed_sources.append(fetcher.name)
            continue

        if not raw_items:
            # The failure that hides: a source stops returning anything, nothing
            # raises, and news simply stops arriving from it. Say it out loud.
            log.warning("source %r returned 0 items — feed may have moved or broken", fetcher.name)
            stats.empty_sources.append(fetcher.name)

        for raw in raw_items:
            if _is_stale(raw, cutoff):
                stats.too_old += 1
                continue
            if _store(session, source, raw):
                stats.new += 1
            else:
                stats.duplicate += 1

        source.last_fetched_at = datetime.now(UTC)
        session.flush()

    return stats


def _is_stale(raw: RawItem, cutoff: datetime) -> bool:
    # An item with no date at all is kept: undated entries are rare, and dropping
    # them would silently lose whole feeds that just don't set the field.
    return raw.published_at is not None and raw.published_at < cutoff


def _upsert_source(session: Session, fetcher: SourceFetcher) -> Source:
    source = session.scalar(select(Source).where(Source.name == fetcher.name))
    if source is None:
        source = Source(
            name=fetcher.name,
            kind=fetcher.kind,
            url=fetcher.url,
            trust_tier=fetcher.trust_tier,
        )
        session.add(source)
        session.flush()
    return source


def _store(session: Session, source: Source, raw: RawItem) -> bool:
    """Insert the item. Returns False when we have already seen it."""
    canonical = canonicalize_url(raw.url)

    # A source that declares a uid is telling us its URLs do not distinguish its
    # items; namespace it per source so two sources can't collide on a bare uid.
    identity = f"{source.id}:{raw.uid}" if raw.uid else canonical
    digest = url_hash(identity)

    if session.scalar(select(Item.id).where(Item.url_hash == digest)) is not None:
        return False

    session.add(
        Item(
            source_id=source.id,
            url=raw.url,
            canonical_url=canonical,
            url_hash=digest,
            title=raw.title[:512],
            author=raw.author[:256] if raw.author else None,
            published_at=raw.published_at,
            raw_text=raw.text[:_MAX_TEXT_CHARS] if raw.text else None,
            fetched_at=datetime.now(UTC),
        )
    )
    # Flush now so a feed that lists the same URL twice in one pass hits the
    # check above on the second occurrence rather than the UNIQUE constraint.
    session.flush()
    return True
