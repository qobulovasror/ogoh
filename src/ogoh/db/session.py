import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ogoh.config import get_settings

log = logging.getLogger(__name__)

# Ships inside the package rather than sitting at the repo root, so resolving it
# never depends on which directory the process happened to start in.
_MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_db() -> None:
    """Bring the schema to head.

    Migrations run at startup instead of being a deploy step somebody remembers.
    One process, one operator: the cost of forgetting is the bot waking at 9am
    against a schema the code no longer agrees with, and the cost of doing it
    here is a few milliseconds when there is nothing to apply.

    Not create_all. That silently ignores drift — it adds missing tables and
    leaves a changed column exactly as it was, so the schema and the models part
    ways without anything being said.
    """
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")
    log.debug("schema at head")


@contextmanager
def session_scope() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
