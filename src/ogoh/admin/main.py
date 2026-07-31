"""Run the admin panel with uvicorn.

Separate process from the bot, same database. Refuses to start if no admin id is
configured — the panel would otherwise stand up with a login nobody can pass.
"""

import logging

import uvicorn

from ogoh import logsetup
from ogoh.admin.app import create_app
from ogoh.config import get_settings
from ogoh.db.session import init_db

log = logging.getLogger("ogoh.admin")


def run() -> int:
    logsetup.configure()
    settings = get_settings()
    if not settings.admin_telegram_id:
        log.error("ADMIN_TELEGRAM_ID is not set — the panel would refuse every login")
        return 1

    init_db()
    app = create_app(settings)
    log.info("admin panel on http://%s:%d", settings.admin_host, settings.admin_port)
    uvicorn.run(app, host=settings.admin_host, port=settings.admin_port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
