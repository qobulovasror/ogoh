"""Verify the one-time login code the bot issued.

The bot process writes an AdminLoginCode; here, in the admin process, we read it
back. A code is single-use and short-lived: verifying it deletes the row whatever
the outcome, so a guessed or replayed code is spent on the attempt, and an expired
one is refused.
"""

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ogoh.config import Settings
from ogoh.db.models import AdminLoginCode
from ogoh.pipeline.digest import as_utc

log = logging.getLogger(__name__)

SESSION_KEY = "admin_id"


def verify_code(session: Session, code: str, admin_id: int) -> int | None:
    """Return the admin id if the code is valid, else None. Always burns the code.

    Deleting before the checks is deliberate: a wrong-id or expired code must not
    survive to be tried again, and there is exactly one legitimate caller racing
    for it.
    """
    row = session.get(AdminLoginCode, code.strip())
    if row is None:
        return None

    session.delete(row)
    session.flush()

    if not admin_id or row.telegram_id != admin_id:
        return None
    if as_utc(row.expires_at) < datetime.now(UTC):
        return None
    return row.telegram_id


def session_secret(settings: Settings) -> str:
    """The key that signs the login cookie.

    An explicit secret if set; otherwise derived from the bot token, which is
    already secret and already required to run anything. The last-resort constant
    only ever applies when neither exists, i.e. in tests.
    """
    if settings.admin_session_secret:
        return settings.admin_session_secret
    if settings.telegram_bot_token:
        return hashlib.sha256(settings.telegram_bot_token.encode()).hexdigest()
    return "ogoh-admin-insecure-dev-secret"
