"""Agent building blocks — search, corpus, budget, cache — without the LLM."""

import json

import httpx

from ogoh.agent import budget, cache
from ogoh.agent.corpus import search_corpus
from ogoh.agent.search import TavilyProvider, build_search_provider
from ogoh.config import Settings

# --- search -------------------------------------------------------------------


def test_tavily_sends_the_query_and_parses_results():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answer": "A short answer.",
                "results": [
                    {"title": "T", "url": "https://x.test/a", "content": "clean text"},
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TavilyProvider(api_key="k", max_results=3, client=client)

    result = provider.search("latest claude model")

    assert seen["body"]["query"] == "latest claude model"
    assert seen["body"]["include_answer"] is True
    assert result.answer == "A short answer."
    assert result.results[0].url == "https://x.test/a"


def test_no_key_means_no_search_provider():
    assert build_search_provider(Settings(tavily_api_key="")) is None
    assert build_search_provider(Settings(tavily_api_key="k")) is not None


# --- corpus -------------------------------------------------------------------


def test_corpus_finds_the_relevant_item(session, make_item, make_enrichment):
    make_enrichment(make_item("Anthropic ships Claude Opus"), importance=8)
    make_enrichment(make_item("A datacenter opens in Iowa"), importance=6)
    session.commit()

    hits = search_corpus(session, "claude opus model")

    assert hits
    assert hits[0].title == "Anthropic ships Claude Opus"


def test_corpus_returns_nothing_for_an_unrelated_query(session, make_item, make_enrichment):
    make_enrichment(make_item("Anthropic ships Claude Opus"), importance=8)
    session.commit()

    assert search_corpus(session, "weather in tashkent tomorrow") == []


# --- budget -------------------------------------------------------------------


def test_budget_counts_down_per_user(session, make_user):
    user = make_user()
    session.commit()

    assert budget.remaining(session, user.id, 3) == 3
    budget.spend(session, user.id)
    budget.spend(session, user.id)
    assert budget.remaining(session, user.id, 3) == 1


def test_budget_is_independent_between_users(session, make_user):
    a = make_user()
    b = make_user()
    session.commit()

    budget.spend(session, a.id)
    assert budget.remaining(session, a.id, 5) == 4
    assert budget.remaining(session, b.id, 5) == 5


# --- cache --------------------------------------------------------------------


def test_cache_round_trips_within_ttl(session):
    cache.put_cached(session, "  Latest Claude?  ", "the answer")
    # Case and surrounding space do not make a different question.
    assert cache.get_cached(session, "latest claude?", ttl_hours=6) == "the answer"


def test_cache_misses_when_disabled(session):
    cache.put_cached(session, "q", "a")
    assert cache.get_cached(session, "q", ttl_hours=0) is None
