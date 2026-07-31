"""The per-user, per-day question budget.

In the database, not memory, so it holds across a restart and is shared between
the bot and any other process. A day with no row is a day with zero spent.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ogoh.db.models import AgentUsage


def remaining(session: Session, user_id: int, limit: int) -> int:
    today = datetime.now(UTC).date()
    row = session.get(AgentUsage, (user_id, today))
    used = row.count if row else 0
    return max(0, limit - used)


def spend(session: Session, user_id: int) -> int:
    """Count one question against today's budget. Returns the new total."""
    today = datetime.now(UTC).date()
    row = session.get(AgentUsage, (user_id, today))
    if row is None:
        row = AgentUsage(user_id=user_id, day=today, count=0)
        session.add(row)
    row.count += 1
    session.flush()
    return row.count
