"""Old article text is dropped; everything derived from it is kept."""

from datetime import timedelta

from ogoh.pipeline.retention import prune_raw_text


def _age(item, now, days):
    item.fetched_at = now - timedelta(days=days)


def test_text_past_the_window_is_pruned(session, make_item, now):
    old = make_item("Old", raw_text="a long article body")
    recent = make_item("Recent", raw_text="fresh body")
    _age(old, now, 100)
    _age(recent, now, 3)
    session.flush()

    pruned = prune_raw_text(session, 90)

    session.refresh(old)
    session.refresh(recent)
    assert pruned == 1
    assert old.raw_text is None
    assert recent.raw_text == "fresh body"


def test_metadata_and_enrichment_survive_the_prune(session, make_item, make_enrichment, now):
    old = make_item("Old headline", raw_text="body")
    enrichment = make_enrichment(old, importance=8)
    _age(old, now, 100)
    session.flush()

    prune_raw_text(session, 90)

    session.refresh(old)
    session.refresh(enrichment)
    assert old.title == "Old headline"
    assert old.raw_text is None
    assert enrichment.summary  # the point of keeping raw_text is already banked


def test_pruning_settles_extraction_so_nothing_refetches(session, make_item, now):
    # A thick-feed item never went through extraction, so text_extracted_at is
    # None. Nulling its text would make it look thin and queue a pointless refetch
    # unless the prune stamps it as settled.
    old = make_item("Old", raw_text="body")
    assert old.text_extracted_at is None
    _age(old, now, 100)
    session.flush()

    prune_raw_text(session, 90)

    session.refresh(old)
    assert old.text_extracted_at is not None


def test_a_zero_retention_disables_pruning(session, make_item, now):
    old = make_item("Old", raw_text="body")
    _age(old, now, 500)
    session.flush()

    assert prune_raw_text(session, 0) == 0
    session.refresh(old)
    assert old.raw_text == "body"
