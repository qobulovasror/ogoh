"""Dedupe, pinned to the cases measured against live data.

Every pair below was observed in the real feed sample. They are here so that
anyone retuning THRESHOLD has to see what it costs: no similarity number of any
kind separates the true pairs from the false ones. Lexically the true pair scores
lower than the false one (0.67 against 0.50 is the best case); by embedding it is
worse still — 0.942 against 0.960, the wrong way round. That is why the lexical
pass only auto-merges what is near-certain and everything ambiguous goes to the
model, which gets these right and can say why.
"""

import pytest

from ogoh.llm.base import PairVerdict
from ogoh.pipeline.dedupe import CANDIDATE, THRESHOLD, assign_clusters, jaccard, title_tokens


def _similarity(left: str, right: str) -> float:
    return jaccard(title_tokens(left), title_tokens(right))


class FakeJudge:
    """Stands in for the model. `same` decides each pair from the two titles."""

    model = "fake"

    def __init__(self, same=lambda left, right: False, *, error=None):
        self._same = same
        self._error = error
        self.asked: list[tuple[str, str]] = []

    def judge_pairs(self, pairs):
        if self._error:
            raise self._error
        self.asked.extend((p.left_title, p.right_title) for p in pairs)
        return [
            PairVerdict(index=p.index, same_event=self._same(p.left_title, p.right_title))
            for p in pairs
        ]

    def classify_batch(self, items):  # unused here
        return []


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


def test_semantic_duplicates_land_in_the_ambiguous_band():
    # The same story, two outlets, 0.67 — too low to merge on sight, high enough
    # to be worth asking about. The lexical pass cannot close this and should not
    # try: the nearest false pair scores 0.50.
    score = _similarity("xai-org/grok-build, now open source", "Grok Build is open source")
    assert CANDIDATE <= score < THRESHOLD


def test_the_model_settles_what_similarity_cannot(session, make_item):
    # By any number, "grok-build" (0.67) and "sqlite-utils 4.1.1/4.0" (0.50) are
    # the wrong way round or too close to call. The model is asked, and only it
    # can tell a rerun from a point release.
    first = make_item("xai-org/grok-build, now open source", age_hours=10)
    rerun = make_item("Grok Build is open source", age_hours=2)
    release = make_item("sqlite-utils 4.1.1", age_hours=9)
    other_release = make_item("sqlite-utils 4.0", age_hours=3)

    judge = FakeJudge(same=lambda left, right: "grok" in left.lower())
    stats = assign_clusters(session, judge)

    assert rerun.cluster_id == first.id
    assert other_release.cluster_id == other_release.id
    assert stats.merged_by_model == 1
    assert release.cluster_id == release.id


def test_only_ambiguous_pairs_are_sent_to_the_model(session, make_item):
    # Near-certain merges cost nothing, and unrelated headlines are not worth a
    # prompt. Only the middle band is asked about.
    make_item("Introducing GPT-Live", age_hours=10)
    make_item("Introducing GPT‑Live", age_hours=9)  # 1.00, merged on sight
    make_item("Anthropic changes rate limits", age_hours=8)  # nothing like it
    make_item("xai-org/grok-build, now open source", age_hours=7)
    make_item("Grok Build is open source", age_hours=6)  # 0.67, ambiguous

    judge = FakeJudge()
    stats = assign_clusters(session, judge)

    assert stats.adjudicated == 1
    assert judge.asked == [("Grok Build is open source", "xai-org/grok-build, now open source")]


def test_without_a_provider_ambiguous_pairs_stay_separate(session, make_item):
    # The safe direction: a duplicate the reader can see beats a merge nobody can.
    first = make_item("xai-org/grok-build, now open source", age_hours=10)
    rerun = make_item("Grok Build is open source", age_hours=2)

    assign_clusters(session, None)

    assert rerun.cluster_id == rerun.id
    assert first.cluster_id == first.id


def test_a_failed_judgement_leaves_them_separate(session, make_item):
    first = make_item("xai-org/grok-build, now open source", age_hours=10)
    rerun = make_item("Grok Build is open source", age_hours=2)

    stats = assign_clusters(session, FakeJudge(error=RuntimeError("429")))

    assert rerun.cluster_id == rerun.id
    assert first.cluster_id == first.id
    assert stats.merged_by_model == 0


def test_a_missing_verdict_leaves_that_pair_separate(session, make_item):
    make_item("xai-org/grok-build, now open source", age_hours=10)
    rerun = make_item("Grok Build is open source", age_hours=2)

    class SilentJudge(FakeJudge):
        def judge_pairs(self, pairs):
            return []

    assign_clusters(session, SilentJudge())

    assert rerun.cluster_id == rerun.id


def test_a_pair_is_judged_once(session, make_item):
    # Once an item has a cluster it is never revisited, so the model is not asked
    # the same question every twenty minutes for a fortnight.
    make_item("xai-org/grok-build, now open source", age_hours=10)
    make_item("Grok Build is open source", age_hours=2)

    judge = FakeJudge()
    assign_clusters(session, judge)
    assign_clusters(session, judge)

    assert len(judge.asked) == 1


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
