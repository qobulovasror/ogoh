"""P0 runner: ingest -> enrich -> digest -> (optionally) Telegram.

    uv run ogoh              # fetch, enrich, print
    uv run ogoh --send       # ... and send it to yourself
    uv run ogoh --dry-run    # fetch only, no LLM calls
"""

import argparse
import logging
import sys

from ogoh.config import get_settings
from ogoh.db.session import init_db, session_scope
from ogoh.llm.gemini import GeminiProvider
from ogoh.pipeline.digest import render_console, render_telegram, top_items
from ogoh.pipeline.enrich import enrich_pending
from ogoh.pipeline.ingest import ingest_all
from ogoh.notify.telegram import send_message

log = logging.getLogger("ogoh")


def main() -> int:
    parser = argparse.ArgumentParser(prog="ogoh")
    parser.add_argument("--send", action="store_true", help="send the digest to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="ingest only, no LLM calls")
    parser.add_argument("--limit", type=int, default=None, help="cap items enriched this run")
    parser.add_argument("--min-importance", type=int, default=None, help="override the threshold")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    settings = get_settings()
    init_db()

    with session_scope() as session:
        ingested = ingest_all(session)
        log.info("ingest: %d new, %d already seen", ingested.new, ingested.duplicate)
        if ingested.failed_sources:
            log.error("sources that failed: %s", ", ".join(ingested.failed_sources))
        if ingested.empty_sources:
            log.warning("sources that returned nothing: %s", ", ".join(ingested.empty_sources))

        if args.dry_run:
            log.info("dry run — stopping before the LLM step")
            return 0

        if not settings.gemini_api_key:
            log.error("GEMINI_API_KEY is not set — get one at https://aistudio.google.com/apikey")
            return 1

        provider = GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
        enriched = enrich_pending(
            session,
            provider,
            batch_size=settings.enrich_batch_size,
            limit=args.limit,
        )
        log.info(
            "enrich: %d items over %d LLM calls, %d skipped",
            enriched.enriched,
            enriched.batches,
            enriched.skipped,
        )

        threshold = (
            args.min_importance if args.min_importance is not None else settings.min_importance
        )
        rows = top_items(session, min_importance=threshold, limit=settings.digest_limit)

        print()
        print(render_console(rows))

        if not args.send:
            return 0

        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            log.error("--send needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
            return 1

        send_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            render_telegram(rows),
        )
        log.info("sent %d items to Telegram", len(rows))

    return 0


if __name__ == "__main__":
    sys.exit(main())
