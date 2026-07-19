"""The daily deep dive.

Built on our own corpus, not web grounding. The plan wanted google_search
grounding, but a free-tier key answers 429 to the first grounded call while an
ordinary call on the same key succeeds — so it is not available here, and the
research reads what we already hold instead. These tests fake the model and pin
the selection and the guards around it.
"""

from ogoh.db.models import ClusterResearch
from ogoh.llm.base import ResearchResult
from ogoh.pipeline.research import MIN_IMPORTANCE, research_top_stories


class FakeResearcher:
    model = "fake"

    def __init__(self, *, error=None):
        self.seen = []
        self._error = error

    def research(self, payload):
        self.seen.append(payload)
        if self._error:
            raise self._error
        return ResearchResult(
            body=f"Deep dive on {payload.headline}.",
            body_uz=f"{payload.headline} haqida tahlil.",
        )


def test_the_biggest_story_gets_written_up(session, make_item, make_enrichment):
    item = make_item("A flagship launch", age_hours=2)
    make_enrichment(item, importance=10)

    stats = research_top_stories(session, FakeResearcher(), limit=1)

    assert stats.written == 1
    stored = session.get(ClusterResearch, item.cluster_id or item.id)
    assert stored is not None
    assert "A flagship launch" in stored.body


def test_routine_stories_are_left_alone(session, make_item, make_enrichment):
    # The extra call is only worth it above the interrupt threshold; everything
    # else is a summary's job.
    make_enrichment(make_item("Incremental update"), importance=MIN_IMPORTANCE - 1)

    stats = research_top_stories(session, FakeResearcher(), limit=1)

    assert stats.written == 0


def test_a_story_is_written_up_once(session, make_item, make_enrichment):
    item = make_item("A flagship launch", age_hours=2)
    make_enrichment(item, importance=10)

    researcher = FakeResearcher()
    research_top_stories(session, researcher, limit=1)
    research_top_stories(session, researcher, limit=1)

    # The news has not changed since morning; a second run must not spend another
    # call re-writing it.
    assert len(researcher.seen) == 1


def test_the_second_biggest_is_reached_once_the_first_is_done(
    session, make_item, make_enrichment
):
    # Asking for exactly `limit` candidates would pick the same top story every
    # run and never reach the rest of the day's big news.
    first = make_item("Biggest", age_hours=3)
    make_enrichment(first, importance=10)
    second = make_item("Second biggest", age_hours=2)
    make_enrichment(second, importance=9)

    researcher = FakeResearcher()
    research_top_stories(session, researcher, limit=1)  # writes the first
    research_top_stories(session, researcher, limit=1)  # should reach the second

    assert session.get(ClusterResearch, second.cluster_id or second.id) is not None


def test_the_run_up_is_gathered_from_earlier_stories(session, make_item, make_enrichment):
    # The part a web search could not do: earlier items about the same names.
    old = make_item("OpenAI shipped GPT-5.5", age_hours=24 * 5)
    make_enrichment(old, importance=7, tags=["model-release"])
    old.enrichment.entities = ["OpenAI", "GPT"]

    lead = make_item("OpenAI ships GPT-5.6", age_hours=2)
    make_enrichment(lead, importance=10)
    lead.enrichment.entities = ["OpenAI", "GPT"]
    session.flush()

    researcher = FakeResearcher()
    research_top_stories(session, researcher, limit=1)

    payload = researcher.seen[0]
    assert any("GPT-5.5" in source.title for source in payload.background)


def test_a_failed_write_up_records_nothing(session, make_item, make_enrichment):
    item = make_item("A flagship launch", age_hours=2)
    make_enrichment(item, importance=10)

    stats = research_top_stories(session, FakeResearcher(error=RuntimeError("429")), limit=1)

    assert stats.written == 0
    assert session.get(ClusterResearch, item.cluster_id or item.id) is None


def test_nothing_big_enough_means_no_calls(session, make_item, make_enrichment):
    make_enrichment(make_item("Routine"), importance=4)

    researcher = FakeResearcher()
    stats = research_top_stories(session, researcher, limit=1)

    assert stats.written == 0
    assert researcher.seen == []


def test_the_write_up_reaches_the_digest(session, make_item, make_enrichment):
    from ogoh.pipeline.digest import render_telegram, top_entries

    item = make_item("A flagship launch", age_hours=2)
    make_enrichment(item, importance=10)
    research_top_stories(session, FakeResearcher(), limit=1)

    entries = top_entries(session, min_importance=5, limit=10)
    assert any(entry.research is not None for entry in entries)
    assert "<blockquote" in render_telegram(entries, lang="uz")


def test_the_digest_survives_a_story_without_a_write_up(session, make_item, make_enrichment):
    # Most stories have none, so the renderer must simply omit the block.
    make_enrichment(make_item("No deep dive here"), importance=8)

    from ogoh.pipeline.digest import render_telegram, top_entries

    entries = top_entries(session, min_importance=5, limit=10)
    html = render_telegram(entries, lang="uz")
    assert "<blockquote" not in html
