"""Full article text, for items whose feed only handed over a teaser.

Why this exists, measured across 169 stored items: 86 carried under 400
characters, and Hugging Face's feed carries no text field at all — title and
link, nothing else — so those items reached the model with a headline to judge
and nothing more. Fetching the page turns that 0 into ~15,000 characters.

trafilatura rather than a parser of our own: telling article prose apart from
navigation, cookie banners and related-links rails is the whole difficulty here,
and it is the one thing trafilatura is for.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import trafilatura
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.db.models import Item

log = logging.getLogger(__name__)

# Under this, whatever the feed gave reads as a teaser rather than the piece.
# Ars Technica averages ~1000 and is borderline; everything below it — OpenAI at
# 144, TechCrunch at 162, Hacker News at 186 — is plainly a lead.
THIN_TEXT_CHARS = 1_000

_MAX_TEXT_CHARS = 20_000
_WORKERS = 6
_TIMEOUT = 20.0

# The conventional bot format — what Googlebot and friends send. It names us, our
# version and where to complain, which is the opposite of a disguise; it simply
# has the shape servers parse. openai.com answers 403 to a bare "Ogoh/0.1" and
# 200 to this, which reads as a CDN filter on unfamiliar syntax rather than a
# policy about who we are. Sites that mean to refuse bots still refuse us —
# techdirt.com 403s this too — and that answer is respected: the item keeps its
# feed lead and we move on.
_USER_AGENT = "Mozilla/5.0 (compatible; Ogoh/0.1; +https://github.com/qobulovasror/ogoh)"


@dataclass(slots=True)
class ExtractStats:
    attempted: int = 0
    improved: int = 0
    failed: int = 0


def extract_pending(session: Session, limit: int | None = None) -> ExtractStats:
    items = _thin_items(session, limit)
    stats = ExtractStats()
    if not items:
        return stats

    urls = [item.url for item in items]
    # Only URLs cross into the threads; the ORM objects are touched on the way
    # back out, on this thread, where the session actually lives.
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        texts = list(pool.map(_fetch_text, urls))

    now = datetime.now(UTC)
    for item, text in zip(items, texts, strict=True):
        stats.attempted += 1
        # Stamped whether or not it worked: a paywall does not get better on the
        # next run, and retrying it every twenty minutes is just noise.
        item.text_extracted_at = now

        if text is None:
            stats.failed += 1
            continue

        # Only take the fetch when it beats what we already had. trafilatura can
        # come back with a nav rail or a consent notice, and overwriting a real
        # lead with that would be a downgrade nobody would notice.
        if len(text) > len(item.raw_text or ""):
            item.raw_text = text[:_MAX_TEXT_CHARS]
            stats.improved += 1

    session.flush()
    return stats


def _thin_items(session: Session, limit: int | None) -> list[Item]:
    stmt = (
        select(Item)
        .where(Item.text_extracted_at.is_(None))
        .where(Item.text_complete.is_(False))
        .where(func.coalesce(func.length(Item.raw_text), 0) < THIN_TEXT_CHARS)
        .order_by(Item.published_at.desc().nullslast(), Item.id.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def _fetch_text(url: str) -> str | None:
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if response.is_error:
            log.debug("extract: %s returned %d", url, response.status_code)
            return None
        return trafilatura.extract(response.text) or None
    except Exception as exc:
        # One unreachable host must not take the batch down; the item keeps its
        # feed lead, which is what it had a moment ago anyway.
        log.debug("extract: %s failed (%s)", url, type(exc).__name__)
        return None
