"""A short-lived answer cache, keyed by the question.

General web Q&A repeats itself, and every miss is a paid search plus an LLM call.
A repeat inside the TTL becomes a free lookup. The TTL is enforced here, in code,
so it can be tuned without a migration.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ogoh.db.models import AgentQueryCache
from ogoh.pipeline.digest import as_utc


def _key(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


def get_cached(session: Session, query: str, ttl_hours: int) -> str | None:
    if ttl_hours <= 0:
        return None
    row = session.get(AgentQueryCache, _key(query))
    if row is None:
        return None
    if as_utc(row.created_at) < datetime.now(UTC) - timedelta(hours=ttl_hours):
        return None
    return row.payload


def put_cached(session: Session, query: str, payload: str) -> None:
    key = _key(query)
    now = datetime.now(UTC)
    row = session.get(AgentQueryCache, key)
    if row is None:
        session.add(AgentQueryCache(query_hash=key, payload=payload, created_at=now))
    else:
        row.payload = payload
        row.created_at = now
    session.flush()
