"""The /ask orchestration: access, budget and cache around the agent loop.

The LLM loop itself is covered in test_agent_runner; here the brain is replaced
with a scripted fake so the gating logic is what's under test.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from stubs import StubMessage, StubState

from ogoh.agent import cache
from ogoh.agent.types import AgentAction
from ogoh.bot import agent_handlers, handlers
from ogoh.bot.agent_handlers import AgentStates, _process
from ogoh.config import Settings
from ogoh.db.models import AgentMessage, AgentQueryCache, AgentUsage, User
from ogoh.db.session import session_scope


class FakeBrain:
    model = "fake"

    def __init__(self, *actions):
        self._actions = list(actions)

    def agent_step(self, system, transcript):
        return self._actions.pop(0)


def _register(telegram_id=42):
    asyncio.run(handlers.handle_start(StubMessage()))


def _enable_agent(session, telegram_id=42):
    user = session.scalar(select(User).where(User.telegram_id == telegram_id))
    user.agent_enabled = True
    session.commit()
    return user


def _patch(monkeypatch, brain, *, budget=3, ttl=6):
    settings = Settings(
        gemini_api_key="x",
        tavily_api_key="",
        agent_daily_budget=budget,
        agent_cache_ttl_hours=ttl,
    )
    monkeypatch.setattr(agent_handlers, "get_settings", lambda: settings)
    monkeypatch.setattr(agent_handlers, "GeminiProvider", lambda **kw: brain)
    monkeypatch.setattr(agent_handlers, "build_search_provider", lambda s: None)


async def test_ask_refuses_a_user_without_the_flag(session):
    await handlers.handle_start(StubMessage())  # user created, agent_enabled=False

    message, state = StubMessage(), StubState()
    await agent_handlers.handle_ask(message, state)

    assert state.state is None
    assert "yoqilmagan" in message.replies[0]


async def test_ask_opens_the_chat_for_an_enabled_user(session):
    await handlers.handle_start(StubMessage())
    _enable_agent(session)

    message, state = StubMessage(), StubState()
    await agent_handlers.handle_ask(message, state)

    assert state.state == AgentStates.chatting


def test_process_refuses_a_disabled_user(session, monkeypatch):
    _register()
    _patch(monkeypatch, FakeBrain())

    _, text, *_ = _process(42, "salom", [], True)
    assert "yoqilmagan" in text


def test_process_answers_and_spends_budget(session, monkeypatch):
    _register()
    user = _enable_agent(session)
    _patch(monkeypatch, FakeBrain(AgentAction("final_answer", "Mana javob.", [])))

    kind, text, _sources, _transcript, _awaiting = _process(user.telegram_id, "savol", [], True)

    assert kind == "answer"
    assert text == "Mana javob."
    session.expire_all()
    usage = session.scalar(select(AgentUsage).where(AgentUsage.user_id == user.id))
    assert usage.count == 1
    assert session.scalar(select(AgentQueryCache)) is not None  # answered fresh question cached
    # The exchange is logged: one user row, one assistant row.
    roles = sorted(
        m.role for m in session.scalars(select(AgentMessage).where(AgentMessage.user_id == user.id))
    )
    assert roles == ["assistant", "user"]


def test_process_refuses_when_the_budget_is_spent(session, monkeypatch):
    _register()
    user = _enable_agent(session)
    _patch(monkeypatch, FakeBrain(), budget=1)
    session.add(AgentUsage(user_id=user.id, day=datetime.now(UTC).date(), count=1))
    session.commit()

    _, text, *_ = _process(user.telegram_id, "savol", [], True)
    assert "limit tugadi" in text


class BoomBrain:
    model = "fake"

    def agent_step(self, system, transcript):
        raise RuntimeError("gemini 429")


def test_process_survives_an_llm_failure_without_charging(session, monkeypatch):
    _register()
    user = _enable_agent(session)
    _patch(monkeypatch, BoomBrain())

    kind, text, _sources, _transcript, _awaiting = _process(user.telegram_id, "savol", [], True)

    assert kind == "answer"
    assert "javob berolmadim" in text
    session.expire_all()
    # A failed question is not billed.
    assert session.scalar(select(AgentUsage).where(AgentUsage.user_id == user.id)) is None


def test_process_serves_a_cache_hit_without_spending(session, monkeypatch):
    _register()
    user = _enable_agent(session)
    _patch(monkeypatch, FakeBrain())  # would IndexError if the loop ran
    with session_scope() as scoped:
        cache.put_cached(scoped, "takror savol", "keshdagi javob")

    _, text, *_ = _process(user.telegram_id, "takror savol", [], True)

    assert text == "keshdagi javob"
    session.expire_all()
    assert session.scalar(select(AgentUsage).where(AgentUsage.user_id == user.id)) is None
