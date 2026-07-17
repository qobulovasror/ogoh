"""One-shot runner, for checking the pipeline without standing the bot up.

    uv run ogoh --dry-run    # fetch and cluster only, no LLM calls
    uv run ogoh              # ... enrich too, print the digest
    uv run ogoh --send       # ... and send it to TELEGRAM_CHAT_ID

The digest here is one shared list, not per-person: this is a diagnostic. Real
delivery is `ogoh-bot`, which matches each subscriber's topics and records what
it sent.
"""

import argparse
import logging
import sys

from ogoh.config import get_settings
from ogoh.db.session import init_db, session_scope
from ogoh.notify.telegram import send_message
from ogoh.pipeline.digest import render_console, render_telegram, top_entries
from ogoh.worker import run_pipeline

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

    if not args.dry_run and not settings.gemini_api_key:
        log.error("GEMINI_API_KEY is not set — get one at https://aistudio.google.com/apikey")
        return 1

    run_pipeline(enrich_limit=args.limit, skip_llm=args.dry_run)

    if args.dry_run:
        log.info("dry run — stopped before the LLM step")
        return 0

    threshold = args.min_importance if args.min_importance is not None else settings.min_importance

    with session_scope() as session:
        entries = top_entries(session, min_importance=threshold, limit=settings.digest_limit)

        print()
        print(render_console(entries))

        if not args.send:
            return 0

        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            log.error("--send needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
            return 1

        send_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            render_telegram(entries),
        )
        log.info("sent %d items to Telegram", len(entries))

    return 0


if __name__ == "__main__":
    sys.exit(main())
