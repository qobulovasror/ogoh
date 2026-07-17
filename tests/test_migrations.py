"""The migration chain, run for real against a file database.

Migrations are what production executes at startup, so a broken one should fail
here rather than at nine in the morning on a VPS. This suite is specifically
where the "Cannot add a NOT NULL column with default value NULL" class of
mistake gets caught — a column with a Python-side default and no server_default
applies cleanly to an empty table and dies on a populated one, so upgrading
through the chain with rows in place is the only thing that finds it.
"""

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from ogoh.db.session import _MIGRATIONS

EXPECTED_TABLES = {
    "sources",
    "items",
    "item_enrichment",
    "users",
    "user_topics",
    "deliveries",
}


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def db_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path / 'chain.db'}"
    # env.py builds its engine from settings, so the setting is what has to move.
    monkeypatch.setenv("DATABASE_URL", url)
    from ogoh.config import get_settings
    from ogoh.db.session import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield url
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_empty_database_upgrades_to_head(db_url):
    command.upgrade(_config(db_url), "head")

    tables = set(inspect(create_engine(db_url)).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_the_chain_is_linear(db_url):
    # Two heads means two migrations claim the same parent, and whichever ran
    # first wins silently.
    heads = ScriptDirectory.from_config(_config(db_url)).get_heads()
    assert len(heads) == 1, f"migration chain has forked: {heads}"


def test_every_revision_applies_one_at_a_time(db_url):
    config = _config(db_url)
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions("base", "heads"))

    # Oldest first, one step at a time. Going straight to head would hide a
    # middle revision that only works when the one after it repairs its mess.
    for _ in revisions:
        command.upgrade(config, "+1")

    tables = set(inspect(create_engine(db_url)).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_migrations_apply_to_a_database_that_holds_rows(db_url):
    """The case that actually broke.

    Adding a NOT NULL column works fine against an empty table and fails against
    one with rows in it, because there is nothing to put in them. Upgrading to
    the first revision, inserting, then continuing is the only shape that finds
    that — and it is exactly the shape of a real deployment.
    """
    config = _config(db_url)
    script = ScriptDirectory.from_config(config)
    revisions = [rev.revision for rev in script.walk_revisions("base", "heads")][::-1]

    command.upgrade(config, revisions[0])

    engine = create_engine(db_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sources (name, kind, url, enabled, trust_tier) "
                "VALUES ('Seed', 'rss', 'https://seed.test/feed', 1, 2)"
            )
        )
        for i in range(3):
            connection.execute(
                text(
                    "INSERT INTO items "
                    "(source_id, url, canonical_url, url_hash, title, fetched_at) "
                    "VALUES (1, :url, :url, :hash, :title, :fetched)"
                ),
                {
                    "url": f"https://seed.test/{i}",
                    "hash": f"hash{i}",
                    "title": f"Seed {i}",
                    "fetched": datetime.now(UTC).isoformat(),
                },
            )

    for revision in revisions[1:]:
        command.upgrade(config, revision)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM items")).scalar() == 3


def test_changelog_rows_are_protected_from_extraction_by_the_backfill(db_url):
    """Rows stored before text_complete existed take the default, false.

    For changelog items that is wrong and destructive: their URL is the whole
    release notes page, so extraction would swap one day's entry for every entry
    on it. Ingest only writes the flag on insert, so nothing else corrects them.
    """
    config = _config(db_url)
    script = ScriptDirectory.from_config(config)
    revisions = [rev.revision for rev in script.walk_revisions("base", "heads")][::-1]

    command.upgrade(config, revisions[0])

    engine = create_engine(db_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sources (name, kind, url, enabled, trust_tier) VALUES "
                "('Claude Platform release notes', 'changelog', 'https://docs.test/notes', 1, 1),"
                "('Some Feed', 'rss', 'https://feed.test/rss', 1, 2)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO items (source_id, url, canonical_url, url_hash, title, fetched_at) "
                "VALUES (1, 'https://docs.test/notes#july-10', 'https://docs.test/notes', "
                "'h1', 'Release notes', :t), "
                "(2, 'https://feed.test/a', 'https://feed.test/a', 'h2', 'An article', :t)"
            ),
            {"t": datetime.now(UTC).isoformat()},
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(
                    "SELECT s.kind, i.text_complete FROM items i "
                    "JOIN sources s ON s.id = i.source_id"
                )
            ).all()
        )

    assert rows["changelog"] == 1
    assert rows["rss"] == 0
