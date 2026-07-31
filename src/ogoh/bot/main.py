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

from ogoh import logsetup
from ogoh.bot.agent_handlers import agent_router
from ogoh.bot.handlers import router
from ogoh.config import get_settings
from ogoh.db.session import init_db
from ogoh.worker import deliver_due_digests, run_pipeline

log = logging.getLogger("ogoh.bot")

_INTERVAL_MINUTES = 20


async def _tick(bot: Bot) -> None:
    # Two try blocks, not one: collecting news and handing it over are separate
    # concerns, and sharing a failure meant that a bad feed or an exhausted LLM
    # quota also withheld the stories already sitting enriched in the database.
    # Readers got silence at nine in the morning over something that had nothing
    # to do with them.
    #
    # Swallowing at all, in both: a raising job gets dropped by APScheduler, so
    # letting one through would end the bot's news for good.
    try:
        await asyncio.to_thread(run_pipeline)
    except Exception:
        log.exception("pipeline failed")

    try:
        sent = await deliver_due_digests(bot)
        if sent:
            log.info("delivered %d digests", sent)
    except Exception:
        log.exception("delivery failed")


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
    # Default MemoryStorage backs the agent FSM — fine at this size; a restart
    # just drops any open /ask conversation, which is recoverable by asking again.
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    dispatcher.include_router(agent_router)

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
    logsetup.configure()
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(run())
