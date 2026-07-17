from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from ogoh.db.models import Item, Source
from ogoh.pipeline.ingest import ingest_all
from ogoh.sources.base import RawItem


class FakeSource:
    kind = "rss"
    trust_tier = 2

    def __init__(self, name="Fake", items=None, *, url="https://fake.test/feed", error=None):
        self.name = name
        self.url = url
        self._items = items or []
        self._error = error
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if self._error:
            raise self._error
        return self._items


def _raw(title="A headline", url="https://fake.test/a", **kwargs):
    kwargs.setdefault("published_at", datetime.now(UTC) - timedelta(hours=1))
    return RawItem(url=url, title=title, **kwargs)


def test_new_items_are_stored(session):
    source = FakeSource(items=[_raw(url="https://fake.test/a"), _raw(url="https://fake.test/b")])
    stats = ingest_all(session, (source,))

    assert stats.new == 2
    assert session.scalar(select(func.count(Item.id))) == 2


def test_the_same_url_is_only_stored_once(session):
    source = FakeSource(items=[_raw(url="https://fake.test/a")])

    ingest_all(session, (source,))
    stats = ingest_all(session, (source,))

    assert stats.new == 0
    assert stats.duplicate == 1


def test_tracking_params_do_not_make_a_new_item(session):
    first = FakeSource("A", [_raw(url="https://fake.test/a?utm_source=rss")])
    second = FakeSource("B", [_raw(url="https://www.fake.test/a/")])

    ingest_all(session, (first,))
    stats = ingest_all(session, (second,))

    assert stats.duplicate == 1


def test_a_feed_listing_one_url_twice_stores_it_once(session):
    # The within-batch case: the second occurrence has to hit the seen-check, not
    # the UNIQUE constraint.
    source = FakeSource(items=[_raw(url="https://fake.test/a"), _raw(url="https://fake.test/a")])
    stats = ingest_all(session, (source,))

    assert stats.new == 1
    assert stats.duplicate == 1


def test_uid_gives_one_url_many_identities(session):
    # A changelog addresses entries by anchor, and canonicalisation drops
    # fragments. Without uid the whole page would collapse to one item, forever.
    source = FakeSource(
        items=[
            _raw(url="https://docs.test/notes#july-10", uid="notes:2026-07-10"),
            _raw(url="https://docs.test/notes#july-08", uid="notes:2026-07-08"),
        ]
    )
    stats = ingest_all(session, (source,))

    assert stats.new == 2


def test_uid_still_dedupes_across_runs(session):
    source = FakeSource(items=[_raw(url="https://docs.test/notes#july-10", uid="notes:2026-07-10")])

    ingest_all(session, (source,))
    stats = ingest_all(session, (source,))

    assert stats.duplicate == 1


def test_uids_are_namespaced_per_source(session):
    # Two sources both numbering their entries "1" must not collide.
    first = FakeSource("First", [_raw(url="https://a.test/x", uid="1")])
    second = FakeSource("Second", [_raw(url="https://b.test/y", uid="1")])

    ingest_all(session, (first, second))

    assert session.scalar(select(func.count(Item.id))) == 2


def test_archive_items_are_left_alone(session):
    # OpenAI's feed serves its whole archive back to 2015. Without the cutoff the
    # first run enriches a decade and the first digest leads with 2015.
    source = FakeSource(
        items=[
            _raw(url="https://fake.test/old", published_at=datetime(2015, 12, 11, tzinfo=UTC)),
            _raw(url="https://fake.test/new"),
        ]
    )
    stats = ingest_all(session, (source,))

    assert stats.new == 1
    assert stats.too_old == 1


def test_undated_items_are_kept(session):
    # Rare, and dropping them would silently lose any feed that omits the field.
    source = FakeSource(items=[_raw(url="https://fake.test/a", published_at=None)])
    stats = ingest_all(session, (source,))

    assert stats.new == 1


def test_one_broken_source_does_not_stop_the_others(session):
    broken = FakeSource("Broken", error=RuntimeError("feed moved"))
    working = FakeSource("Working", [_raw(url="https://fake.test/a")])

    stats = ingest_all(session, (broken, working))

    assert stats.failed_sources == ["Broken"]
    assert stats.new == 1


def test_an_empty_source_is_reported(session):
    # The failure that hides: a feed stops returning anything, nothing raises,
    # and the news just stops. DeepMind's rss.xml does exactly this.
    source = FakeSource("Silent", [])
    stats = ingest_all(session, (source,))

    assert stats.empty_sources == ["Silent"]


def test_source_config_is_resynced_on_every_run(session):
    # Writing these only on insert left the registry saying one thing and every
    # existing database another.
    source = FakeSource("Shifting", [_raw(url="https://fake.test/a")], url="https://old.test/feed")
    ingest_all(session, (source,))

    source.url = "https://new.test/feed"
    source.trust_tier = 1
    ingest_all(session, (source,))

    stored = session.scalar(select(Source).where(Source.name == "Shifting"))
    assert stored.url == "https://new.test/feed"
    assert stored.trust_tier == 1


def test_text_complete_is_carried_through(session):
    source = FakeSource(
        items=[
            _raw(url="https://docs.test/notes#july-10", uid="n:1", text_is_complete=True),
            _raw(url="https://fake.test/article"),
        ]
    )
    ingest_all(session, (source,))

    changelog = session.scalar(select(Item).where(Item.url.contains("notes")))
    article = session.scalar(select(Item).where(Item.url.contains("article")))
    assert changelog.text_complete is True
    assert article.text_complete is False
