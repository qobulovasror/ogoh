"""Which stories go to which person, and when.

Everything here is deterministic: tag overlap, an importance floor, a clock. The
embedding-scored interest profile the plan describes is a later phase — starting
with rules means that when someone asks "why did I get this?", the answer is a
row you can point at rather than a cosine.
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ogoh.db.models import Delivery, User
from ogoh.pipeline.digest import DigestEntry, top_entries

log = logging.getLogger(__name__)

DIGEST_MODES = ("instant", "daily", "weekly", "off")

# instant interrupts someone's day, so it only ever carries a launch or a change
# to limits — never a merely interesting story.
INSTANT_MIN_IMPORTANCE = 8

# How far back each mode looks. Weekly reaches past seven days so a story landing
# an hour before the cutoff still makes the following week's edition.
_WINDOW_HOURS = {"instant": 6, "daily": 48, "weekly": 24 * 8}


def pending_for_user(session: Session, user: User, limit: int = 10) -> list[DigestEntry]:
    threshold = user.min_importance
    if user.digest_mode == "instant":
        threshold = max(threshold, INSTANT_MIN_IMPORTANCE)

    entries = top_entries(
        session,
        min_importance=threshold,
        limit=limit * 4,
        within_hours=_WINDOW_HOURS.get(user.digest_mode, 48),
    )

    topics = {topic.tag for topic in user.topics}
    delivered = set(
        session.scalars(select(Delivery.cluster_id).where(Delivery.user_id == user.id))
    )

    matched: list[DigestEntry] = []
    for entry in entries:
        cluster = entry.item.cluster_id or entry.item.id
        if cluster in delivered:
            continue
        # An empty topic set means "hasn't picked yet", not "wants nothing".
        # Sending everything beats sending silence to someone who never ran
        # /topics and would just conclude the bot is broken.
        if topics and not topics.intersection(entry.enrichment.tags):
            continue
        matched.append(entry)
        if len(matched) >= limit:
            break

    return matched


def is_due(user: User, now: datetime) -> bool:
    if not user.is_active or user.digest_mode == "off":
        return False
    if user.digest_mode == "instant":
        return True  # importance does the gating in pending_for_user

    local = now.astimezone(_zone(user.timezone))
    if local.hour != user.digest_hour:
        return False
    if user.digest_mode == "weekly" and local.weekday() != 0:
        return False

    last = as_utc(user.last_digest_at)
    if last is None:
        return True

    # The scheduler fires every 20 minutes, so the due hour comes round three
    # times. Without this gap check the reader gets three digests each morning.
    gap = timedelta(days=6) if user.digest_mode == "weekly" else timedelta(hours=23)
    return now - last >= gap


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite has no timestamptz.

    DateTime(timezone=True) round-trips through it as a naive value, and
    subtracting a naive datetime from an aware one raises TypeError. Postgres
    returns these aware, so this has to cope with both.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("user timezone %r is not a known zone; using UTC", name)
        return ZoneInfo("UTC")
