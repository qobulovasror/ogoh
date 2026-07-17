"""Dedupe, pinned to the cases measured against live data.

Every pair below was observed in the real feed sample. They are here so that
anyone retuning THRESHOLD has to look at what it costs — the true and false
pairs sit only 0.17 apart, which is why the number is high and why moving it is
not a free knob.
"""

import pytest

from ogoh.pipeline.dedupe import THRESHOLD, assign_clusters, jaccard, title_tokens


def _similarity(left: str, right: str) -> float:
    return jaccard(title_tokens(left), title_tokens(right))


def test_typographic_variants_are_one_story():
    # Observed: OpenAI's feed and Simon Willison's carried the same headline, one
    # with a plain hyphen and one with U+2011. Identical to a reader, different
    # bytes, and the single duplicate the lexical pass actually catches.
    assert _similarity("Introducing GPT-Live", "Introducing GPT‑Live") == 1.0


def test_version_numbers_are_not_interchangeable():
    # These are distinct releases. An early tokeniser dropped short tokens, which
    # left both as {sqlite, utils} and merged three announcements into one.
    assert _similarity("sqlite-utils 4.1.1", "sqlite-utils 4.0") < THRESHOLD
    assert "4.1.1" in title_tokens("sqlite-utils 4.1.1")


def test_same_series_different_articles_stay_apart():
    # Observed false pair, scores 0.50. The nearest true pair scores 0.67, so a
    # threshold anywhere between them is a coin flip on another day's news.
    assert (
        _similarity(
            "How sales teams use ChatGPT Work",
            "How data science teams use ChatGPT Work",
        )
        < THRESHOLD
    )


def test_semantic_duplicates_are_a_known_miss():
    # The same story, two outlets, 0.67 — under the threshold on purpose. This is
    # what embedding dedupe is for; asserting it documents the gap rather than
    # pretending the lexical pass closes it.
    score = _similarity("xai-org/grok-build, now open source", "Grok Build is open source")
    assert 0.6 < score < THRESHOLD


def test_earliest_publisher_becomes_canonical(session, make_item, make_source):
    first = make_item("Introducing GPT-Live", age_hours=10)
    rerun = make_item("Introducing GPT‑Live", age_hours=2)

    stats = assign_clusters(session)

    assert rerun.cluster_id == first.id
    assert first.cluster_id == first.id
    assert stats.merged == 1


def test_reruns_join_clusters_from_earlier_passes(session, make_item):
    first = make_item("Introducing GPT-Live", age_hours=10)
    assign_clusters(session)

    # A second outlet picks the story up after we already clustered the first.
    late = make_item("Introducing GPT‑Live", age_hours=1)
    assign_clusters(session)

    assert late.cluster_id == first.id


def test_clustering_is_idempotent(session, make_item):
    make_item("Introducing GPT-Live", age_hours=10)
    make_item("Introducing GPT‑Live", age_hours=2)

    assign_clusters(session)
    second_pass = assign_clusters(session)

    # Nothing new to do; a rerun must not re-cluster or re-count what it saw.
    assert second_pass.merged == 0
    assert second_pass.clustered == 0


def test_unrelated_items_get_their_own_clusters(session, make_item):
    a = make_item("OpenAI ships a new model")
    b = make_item("Anthropic changes rate limits")

    assign_clusters(session)

    assert a.cluster_id == a.id
    assert b.cluster_id == b.id


def test_items_outside_the_window_are_still_clustered(session, make_item):
    # The window follows what ingest retains, not what today's digest shows.
    # Tying it to 48h left older items unclustered, and weekly subscribers were
    # the ones who got the duplicates.
    old = make_item("Introducing GPT-Live", age_hours=24 * 10)
    older_rerun = make_item("Introducing GPT‑Live", age_hours=24 * 9)

    assign_clusters(session)

    assert older_rerun.cluster_id == old.id


@pytest.mark.parametrize("title", ["", "   ", "!!! ???"])
def test_untokenisable_titles_stand_alone(session, make_item, title):
    item = make_item(title)
    assign_clusters(session)
    assert item.cluster_id == item.id
