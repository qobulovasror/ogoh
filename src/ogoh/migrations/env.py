from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection

from ogoh.config import get_settings
from ogoh.db.models import Base
from ogoh.db.session import get_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # The application's setting wins over alembic.ini. One source of truth means
    # migrations cannot be applied to a different database than the app opens.
    return get_settings().database_url


def _is_sqlite() -> bool:
    return _url().startswith("sqlite")


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER a column or drop a constraint. Batch mode rebuilds
        # the table around the change instead. It is a no-op on Postgres, so it
        # stays on unconditionally rather than becoming a thing to remember.
        render_as_batch=_is_sqlite(),
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = get_engine()
    with connectable.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
