from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ogoh.config import get_settings
from ogoh.db.models import Base


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(get_engine())


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
