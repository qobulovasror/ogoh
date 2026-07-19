"""Bot process: command handling plus the recurring pipeline job.

One process rather than two. At tens of users the pipeline is a few seconds of
work every twenty minutes, and a second process would buy isolation nobody needs
yet at the cost of a queue and a deployment.
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ogoh.bot.handlers import router
from ogoh.config import get_settings
from ogoh.db.session import init_db
from ogoh.worker import deliver_due_digests, run_pipeline

log = logging.getLogger("ogoh.bot")

_INTERVAL_MINUTES = 20


async def _tick(bot: Bot) -> None:
    try:
        await asyncio.to_thread(run_pipeline)
        sent = await deliver_due_digests(bot)
        if sent:
            log.info("delivered %d digests", sent)
    except Exception:
        # A raising job gets dropped by APScheduler; swallowing here keeps the
        # schedule alive so one bad fetch doesn't end the bot's news forever.
        log.exception("pipeline tick failed")


async def _run() -> int:
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN is not set — get one from @BotFather")
        return 1

    init_db()

    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _tick,
        "interval",
        minutes=_INTERVAL_MINUTES,
        args=[bot],
        id="pipeline",
        # A tick that outruns the interval must not start a second copy of
        # itself, and a tick missed while the process was down should run once,
        # not once per interval that elapsed.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    log.info("scheduler started — pipeline every %d minutes", _INTERVAL_MINUTES)

    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
    return 0


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(run())
