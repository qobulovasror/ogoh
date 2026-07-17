"""Shared fixtures.

The database fixture runs the real migration chain rather than create_all. Two
reasons: the migrations are what production actually executes, so a broken one
should fail here rather than at 9am on a VPS — and this suite is where the
"Cannot add a NOT NULL column with default value NULL" class of mistake gets
caught, which create_all would sail straight past.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_settings(tmp_path_factory) -> Iterator[None]:
    """Point the whole suite at a scratch database and away from any real key.

    Set before ogoh.config is imported anywhere, so the lru_cached Settings never
    sees the developer's .env. Without this a test run would read the operator's
    real GEMINI_API_KEY and, worse, their real database.
    """
    db_path = tmp_path_factory.mktemp("ogoh") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    os.environ["TELEGRAM_CHAT_ID"] = ""
    yield


@pytest.fixture
def session(_isolate_settings, tmp_path, monkeypatch) -> Iterator:
    """A scratch database, wired in as the one the whole package sees.

    A file rather than sqlite://, and patched over get_engine rather than handed
    round: worker and the bot handlers open their own sessions through
    session_scope, as code owning a transaction boundary should. A fixture that
    only yielded a session would leave those talking to a different database
    entirely, and the tests that matter most here are exactly the ones that go
    through them.

    Schema via create_all — the migration chain has its own suite, and paying for
    it in every test buys nothing.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ogoh.db import session as session_module
    from ogoh.db.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(session_module, "get_engine", lambda: engine)
    monkeypatch.setattr(session_module, "_session_factory", lambda: factory)

    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def now() -> datetime:
    """Real wall clock, not a frozen instant.

    The digest and dedupe windows call datetime.now() internally, so fixture data
    has to be positioned relative to the same clock — pinning this to a literal
    made every `age_hours` a lie and quietly pushed items outside the window
    under test. Tests that need a fixed instant (is_due) take one as an argument.
    """
    return datetime.now(UTC)


@pytest.fixture
def make_source(session):
    """Get-or-create by name: sources.name is unique, and tests that only care
    about items should not have to invent a source name each time."""
    from sqlalchemy import select

    from ogoh.db.models import Source

    def _make(name: str = "Test Source", *, kind: str = "rss", trust_tier: int = 2) -> Source:
        existing = session.scalar(select(Source).where(Source.name == name))
        if existing is not None:
            return existing
        source = Source(
            name=name,
            kind=kind,
            url=f"https://example.com/{name.replace(' ', '-').lower()}",
            trust_tier=trust_tier,
        )
        session.add(source)
        session.flush()
        return source

    return _make


@pytest.fixture
def make_item(session, make_source, now):
    from ogoh.db.models import Item
    from ogoh.pipeline.normalize import canonicalize_url, url_hash

    counter = {"n": 0}

    def _make(
        title: str = "A headline",
        *,
        source=None,
        url: str | None = None,
        published_at: datetime | None = None,
        raw_text: str = "body",
        text_complete: bool = False,
        age_hours: float = 1.0,
    ) -> Item:
        counter["n"] += 1
        source = source or make_source()
        url = url or f"https://example.com/post-{counter['n']}"
        canonical = canonicalize_url(url)
        item = Item(
            source_id=source.id,
            url=url,
            canonical_url=canonical,
            url_hash=url_hash(canonical),
            title=title,
            published_at=published_at or (now - timedelta(hours=age_hours)),
            raw_text=raw_text,
            text_complete=text_complete,
            fetched_at=now,
        )
        session.add(item)
        session.flush()
        return item

    return _make


@pytest.fixture
def make_enrichment(session, now):
    from ogoh.db.models import ItemEnrichment

    def _make(item, *, importance: int = 6, tags: list[str] | None = None) -> ItemEnrichment:
        enrichment = ItemEnrichment(
            item_id=item.id,
            tags=tags if tags is not None else ["model-release"],
            entities=[],
            importance=importance,
            summary=f"Summary of {item.title}.",
            model_used="test",
            enriched_at=now,
        )
        session.add(enrichment)
        session.flush()
        return enrichment

    return _make


@pytest.fixture
def make_user(session, now):
    from ogoh.db.models import User, UserTopic

    counter = {"n": 0}

    def _make(
        *,
        topics: list[str] | None = None,
        digest_mode: str = "daily",
        digest_hour: int = 9,
        timezone: str = "Asia/Tashkent",
        min_importance: int = 5,
        last_digest_at: datetime | None = None,
    ) -> User:
        counter["n"] += 1
        user = User(
            telegram_id=1000 + counter["n"],
            username=f"user{counter['n']}",
            digest_mode=digest_mode,
            digest_hour=digest_hour,
            timezone=timezone,
            min_importance=min_importance,
            last_digest_at=last_digest_at,
            created_at=now,
        )
        session.add(user)
        session.flush()
        for tag in topics or []:
            session.add(UserTopic(user_id=user.id, tag=tag))
        session.flush()
        session.refresh(user)
        return user

    return _make
