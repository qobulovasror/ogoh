"""The recurring job: refresh the news, then hand each person what they are owed."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select

from ogoh.bot.keyboards import feedback_keyboard
from ogoh.config import get_settings
from ogoh.db.models import Delivery, User
from ogoh.db.session import session_scope
from ogoh.llm.gemini import GeminiProvider
from ogoh.pipeline.dedupe import assign_clusters
from ogoh.pipeline.digest import render_telegram
from ogoh.pipeline.enrich import enrich_pending
from ogoh.pipeline.extract import extract_pending
from ogoh.pipeline.ingest import ingest_all
from ogoh.pipeline.match import is_due, pending_for_user

log = logging.getLogger(__name__)

# Telegram allows about 30 messages a second across a bot. Nowhere near binding at
# this size, but a fleet of fifty sends in a tight loop is exactly the shape that
# earns a 429, and honouring a small gap costs nothing.
_SEND_GAP_SECONDS = 0.05


@dataclass(slots=True)
class PipelineStats:
    new_items: int = 0
    stories: int = 0
    extracted: int = 0
    enriched: int = 0


def run_pipeline(*, enrich_limit: int | None = None, skip_llm: bool = False) -> PipelineStats:
    """Refresh: ingest, cluster, enrich. Blocking — call it off the event loop.

    The one definition of the sequence. The bot's tick and the one-shot CLI both
    come through here so the two cannot drift apart.
    """
    settings = get_settings()
    stats = PipelineStats()

    provider = (
        GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
        if settings.gemini_api_key and not skip_llm
        else None
    )

    with session_scope() as session:
        ingested = ingest_all(session)
        stats.new_items = ingested.new
        log.info("ingest: %d new, %d already seen", ingested.new, ingested.duplicate)
        if ingested.failed_sources:
            log.error("sources that failed: %s", ", ".join(ingested.failed_sources))
        if ingested.empty_sources:
            log.warning("sources that returned nothing: %s", ", ".join(ingested.empty_sources))

        deduped = assign_clusters(session, provider)
        stats.stories = deduped.clustered
        log.info(
            "dedupe: %d stories, %d folded in (%d judged, %d of those merged)",
            deduped.clustered,
            deduped.merged + deduped.merged_by_model,
            deduped.adjudicated,
            deduped.merged_by_model,
        )

        extracted = extract_pending(session)
        stats.extracted = extracted.improved
        if extracted.attempted:
            log.info(
                "extract: %d fetched, %d improved, %d unavailable",
                extracted.attempted,
                extracted.improved,
                extracted.failed,
            )

        if provider is None:
            if not skip_llm:
                log.error("GEMINI_API_KEY is not set — skipping enrichment")
            return stats

        enriched = enrich_pending(
            session, provider, batch_size=settings.enrich_batch_size, limit=enrich_limit
        )
        stats.enriched = enriched.enriched
        log.info(
            "enrich: %d items over %d calls, %d skipped",
            enriched.enriched,
            enriched.batches,
            enriched.skipped,
        )

    return stats


async def deliver_due_digests(bot: Bot) -> int:
    now = datetime.now(UTC)
    limit = get_settings().digest_limit
    sent = 0

    with session_scope() as session:
        users = session.scalars(select(User).where(User.is_active.is_(True))).all()

        for user in users:
            if not is_due(user, now):
                continue

            entries = pending_for_user(session, user, limit=limit)
            if not entries:
                continue

            if not await _send(bot, session, user, entries):
                continue

            # Recorded only once the send has landed. The other order drops a
            # digest on the floor every time Telegram hiccups; this one at worst
            # repeats one, and a repeat is the cheaper mistake.
            for entry in entries:
                session.add(
                    Delivery(
                        user_id=user.id,
                        cluster_id=entry.item.cluster_id or entry.item.id,
                        sent_at=now,
                    )
                )
            user.last_digest_at = now
            sent += 1
            await asyncio.sleep(_SEND_GAP_SECONDS)

    return sent


async def _send(bot: Bot, session, user: User, entries: list) -> bool:
    try:
        await bot.send_message(
            user.telegram_id,
            render_telegram(entries, lang=user.lang),
            reply_markup=feedback_keyboard(entries),
            link_preview_options={"is_disabled": True},
        )
        return True
    except TelegramForbiddenError:
        # They blocked the bot or deleted the chat. Telegram will reject every
        # future send too, so stop trying rather than logging this forever.
        log.info("user %d blocked the bot — deactivating", user.telegram_id)
        user.is_active = False
        return False
    except TelegramRetryAfter as exc:
        log.warning("rate limited, retry after %ss — leaving user %d for the next run",
                    exc.retry_after, user.telegram_id)
        return False
    except Exception:
        log.exception("failed to send digest to user %d", user.telegram_id)
        return False
