"""Record one agent exchange for later review in the admin panel."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ogoh.db.models import AgentMessage

_MAX_LEN = 4_000


def log_exchange(session: Session, user_id: int, question: str, answer: str) -> None:
    now = datetime.now(UTC)
    session.add(
        AgentMessage(user_id=user_id, role="user", content=question[:_MAX_LEN], created_at=now)
    )
    session.add(
        AgentMessage(user_id=user_id, role="assistant", content=answer[:_MAX_LEN], created_at=now)
    )
    session.flush()
