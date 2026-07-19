"""Enrichment, with the LLM faked.

The interesting failures here are not "the model said something odd" — they are
what our code does when it does. A batch that comes back short is the one that
matters: matching by position would attach the wrong summary to the wrong story
and nothing would look broken.
"""

from ogoh.db.models import ItemEnrichment
from ogoh.llm.base import Verdict
from ogoh.pipeline.enrich import enrich_pending


class FakeProvider:
    model = "fake-model"

    def __init__(self, verdicts_for=None, *, error=None):
        self._verdicts_for = verdicts_for or (lambda items: [_verdict(i.index) for i in items])
        self._error = error
        self.batches = []

    def classify_batch(self, items):
        self.batches.append(items)
        if self._error:
            raise self._error
        return self._verdicts_for(items)


def _verdict(index, *, importance=6, tags=None, summary=None):
    return Verdict(
        index=index,
        importance=importance,
        summary=summary or f"Summary {index}.",
        tags=tags if tags is not None else ["model-release"],
        entities=["OpenAI"],
    )


def test_every_item_gets_enriched(session, make_item):
    for i in range(3):
        make_item(f"Item {i}")

    stats = enrich_pending(session, FakeProvider(), batch_size=10)

    assert stats.enriched == 3
    assert stats.batches == 1


def test_items_are_batched(session, make_item):
    for i in range(25):
        make_item(f"Item {i}")

    provider = FakeProvider()
    stats = enrich_pending(session, provider, batch_size=10)

    assert stats.batches == 3
    assert [len(batch) for batch in provider.batches] == [10, 10, 5]
    assert stats.enriched == 25


def test_already_enriched_items_are_not_redone(session, make_item, make_enrichment):
    done = make_item("Done")
    make_enrichment(done)
    make_item("Pending")

    stats = enrich_pending(session, FakeProvider(), batch_size=10)

    assert stats.enriched == 1


def _echoing(transform):
    """Fake that writes each item's own title into its summary.

    Asserting on that afterwards pins the property that matters — this story's
    summary reached this story — without assuming anything about the order
    enrich hands items over in. `transform` mangles the returned list.
    """

    def _classify(batch):
        verdicts = [_verdict(item.index, summary=f"About {item.title}.") for item in batch]
        return transform(verdicts)

    return _classify


def test_a_short_batch_does_not_shift_summaries(session, make_item):
    # The model returns one verdict fewer than it was asked for. Falling back to
    # position here would give one story the summary written for the next one —
    # wrong, and with nothing on the surface to show it.
    items = [make_item(f"Item {i}") for i in range(3)]
    missing = {}

    def drop_the_middle(verdicts):
        missing["index"] = verdicts[1].index
        return [verdicts[0], verdicts[2]]

    stats = enrich_pending(session, FakeProvider(_echoing(drop_the_middle)), batch_size=10)

    assert stats.enriched == 2
    assert stats.skipped == 1

    stored = {item.id: session.get(ItemEnrichment, item.id) for item in items}
    assert sum(record is None for record in stored.values()) == 1
    for item in items:
        record = stored[item.id]
        if record is not None:
            assert record.summary == f"About {item.title}."


def test_misordered_verdicts_land_on_the_right_items(session, make_item):
    items = [make_item(f"Item {i}") for i in range(3)]

    enrich_pending(session, FakeProvider(_echoing(lambda v: list(reversed(v)))), batch_size=10)

    for item in items:
        assert session.get(ItemEnrichment, item.id).summary == f"About {item.title}."


def test_invented_tags_are_dropped(session, make_item):
    # An open tag set drifts into synonyms and nothing ever matches a
    # subscription again, so anything outside the taxonomy is discarded.
    item = make_item("Item")

    def invents(batch):
        return [_verdict(0, tags=["model-release", "brand-new-tag", "AI"])]

    enrich_pending(session, FakeProvider(invents), batch_size=10)

    assert session.get(ItemEnrichment, item.id).tags == ["model-release"]


def test_an_item_with_only_invented_tags_still_stores(session, make_item):
    item = make_item("Item")

    def all_invented(batch):
        return [_verdict(0, tags=["nonsense"])]

    enrich_pending(session, FakeProvider(all_invented), batch_size=10)

    stored = session.get(ItemEnrichment, item.id)
    assert stored is not None
    assert stored.tags == []


def test_entities_are_capped(session, make_item):
    item = make_item("Item")

    def many_entities(batch):
        verdict = _verdict(0)
        verdict.entities = [f"Org{i}" for i in range(12)]
        return [verdict]

    enrich_pending(session, FakeProvider(many_entities), batch_size=10)

    assert len(session.get(ItemEnrichment, item.id).entities) == 5


def test_a_failed_batch_is_retried_next_run(session, make_item):
    # Left unenriched rather than half-written, so the next pass picks it up.
    item = make_item("Item")

    stats = enrich_pending(session, FakeProvider(error=RuntimeError("429")), batch_size=10)
    assert stats.skipped == 1
    assert session.get(ItemEnrichment, item.id) is None

    enrich_pending(session, FakeProvider(), batch_size=10)
    assert session.get(ItemEnrichment, item.id) is not None


def test_one_failed_batch_does_not_take_the_others(session, make_item):
    for i in range(15):
        make_item(f"Item {i}")

    calls = {"n": 0}

    def fail_first_batch(batch):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return [_verdict(item.index) for item in batch]

    provider = FakeProvider(fail_first_batch)
    stats = enrich_pending(session, provider, batch_size=10)

    assert stats.skipped == 10
    assert stats.enriched == 5


def test_limit_caps_the_run(session, make_item):
    for i in range(30):
        make_item(f"Item {i}")

    stats = enrich_pending(session, FakeProvider(), batch_size=10, limit=15)

    assert stats.enriched == 15
