"""The agent loop, with a scripted brain and a fake search — no LLM, no network."""

from ogoh.agent.runner import run_turn
from ogoh.agent.search import WebResult, WebSearch
from ogoh.agent.types import AgentAction
from ogoh.config import Settings


class FakeBrain:
    model = "fake"

    def __init__(self, actions):
        self._actions = list(actions)
        self.calls = 0

    def agent_step(self, system, transcript):
        self.calls += 1
        self.last_transcript = transcript
        return self._actions.pop(0)


class FakeSearch:
    def __init__(self, result):
        self._result = result
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self._result


def _settings(**kw):
    defaults = {"agent_max_tool_calls": 5, "agent_max_web_searches": 3}
    defaults.update(kw)
    return Settings(**defaults)


def test_a_corpus_hit_leads_straight_to_an_answer(session, make_item, make_enrichment):
    make_enrichment(make_item("Anthropic ships Claude Opus"), importance=8)
    session.commit()
    brain = FakeBrain(
        [
            AgentAction("search_corpus", "claude opus"),
            AgentAction("final_answer", "Claude Opus chiqdi.", ["https://x.test"]),
        ]
    )

    reply = run_turn(session, brain, None, "eng oxirgi claude?", [], _settings())

    assert reply.kind == "answer"
    assert reply.text == "Claude Opus chiqdi."
    assert reply.sources == ["https://x.test"]


def test_web_search_is_used_and_its_result_reaches_the_answer(session):
    search = FakeSearch(WebSearch(answer="+17", results=[WebResult("W", "https://w.test", "text")]))
    brain = FakeBrain(
        [
            AgentAction("web_search", "tashkent weather"),
            AgentAction("final_answer", "17 daraja.", ["https://w.test"]),
        ]
    )

    reply = run_turn(session, brain, search, "ob-havo?", [], _settings())

    assert search.queries == ["tashkent weather"]
    assert reply.text == "17 daraja."


def test_ask_user_pauses_the_loop_for_a_clarification(session):
    brain = FakeBrain([AgentAction("ask_user", "Qaysi shahar?")])

    reply = run_turn(session, brain, None, "ob-havo?", [], _settings())

    assert reply.kind == "question"
    assert reply.text == "Qaysi shahar?"


def test_the_loop_is_capped_and_forces_an_answer(session):
    # Never returns final on its own — every step asks to search again.
    actions = [AgentAction("search_corpus", "x") for _ in range(5)]
    actions.append(AgentAction("final_answer", "Topilmadi, lekin mana.", []))
    brain = FakeBrain(actions)

    reply = run_turn(session, brain, None, "q", [], _settings(agent_max_tool_calls=5))

    assert reply.kind == "answer"
    # 5 loop steps + 1 forced step.
    assert brain.calls == 6


def test_web_search_limit_is_respected(session):
    search = FakeSearch(WebSearch(answer="", results=[]))
    # Ask to web_search four times; the cap is two.
    actions = [AgentAction("web_search", f"q{i}") for i in range(4)]
    actions.append(AgentAction("final_answer", "done", []))
    brain = FakeBrain(actions)

    run_turn(session, brain, search, "q", [], _settings(agent_max_web_searches=2))

    assert len(search.queries) == 2


def test_fetch_page_reads_a_url(session, monkeypatch):
    from ogoh.agent import runner

    monkeypatch.setattr(runner, "fetch_article_text", lambda url: f"BODY of {url}")
    brain = FakeBrain(
        [
            AgentAction("fetch_page", "https://a.test/article"),
            AgentAction("final_answer", "o'qidim", ["https://a.test/article"]),
        ]
    )

    run_turn(session, brain, None, "u haqda", [], _settings())

    # The fetched body reached the model's next step.
    assert "BODY of https://a.test/article" in brain.last_transcript


def test_fetch_limit_is_respected(session, monkeypatch):
    from ogoh.agent import runner

    calls = []
    monkeypatch.setattr(runner, "fetch_article_text", lambda url: calls.append(url) or "x")
    actions = [AgentAction("fetch_page", f"https://a.test/{i}") for i in range(4)]
    actions.append(AgentAction("final_answer", "done", []))
    brain = FakeBrain(actions)

    run_turn(session, brain, None, "q", [], _settings(agent_max_fetches=2))

    assert len(calls) == 2


def test_escalate_switches_to_the_heavy_brain(session):
    light = FakeBrain([AgentAction("escalate", "")])
    heavy = FakeBrain([AgentAction("final_answer", "kuchli javob", [])])

    reply = run_turn(session, light, None, "murakkab savol", [], _settings(), heavy_brain=heavy)

    assert reply.text == "kuchli javob"
    assert heavy.calls == 1


def test_escalate_without_a_heavy_brain_continues_on_the_light_one(session):
    light = FakeBrain(
        [AgentAction("escalate", ""), AgentAction("final_answer", "light javob", [])]
    )

    reply = run_turn(session, light, None, "q", [], _settings(), heavy_brain=None)

    assert reply.text == "light javob"
    assert light.calls == 2


def test_the_forced_final_answer_uses_the_heavy_brain(session):
    light = FakeBrain([AgentAction("search_corpus", "x") for _ in range(5)])
    heavy = FakeBrain([AgentAction("final_answer", "heavy forced", [])])

    reply = run_turn(
        session, light, None, "q", [], _settings(agent_max_tool_calls=5), heavy_brain=heavy
    )

    assert reply.text == "heavy forced"
    assert heavy.calls == 1


def test_a_failing_web_search_does_not_sink_the_turn(session):
    class Boom:
        def search(self, query):
            raise RuntimeError("tavily down")

    brain = FakeBrain(
        [AgentAction("web_search", "q"), AgentAction("final_answer", "korpusdan javob", [])]
    )

    reply = run_turn(session, brain, Boom(), "q", [], _settings())

    assert reply.kind == "answer"
    assert reply.text == "korpusdan javob"
    assert "error" in brain.last_transcript  # the failure became an observation


def test_observations_are_capped(session, monkeypatch):
    from ogoh.agent import runner

    monkeypatch.setattr(runner, "fetch_article_text", lambda url: "A" * 10_000)
    brain = FakeBrain(
        [AgentAction("fetch_page", "https://a.test/x"), AgentAction("final_answer", "ok", [])]
    )

    run_turn(session, brain, None, "q", [], _settings(agent_obs_char_cap=500))

    # The 10k body was trimmed before it re-entered the prompt.
    assert "[truncated]" in brain.last_transcript
    assert brain.last_transcript.count("A") < 1_000
