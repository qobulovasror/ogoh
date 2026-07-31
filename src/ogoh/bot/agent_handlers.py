"""The /ask conversation: an interactive research agent, for enabled users only.

A FSM state holds the running transcript between messages, so a clarifying
question and its answer are one exchange. The heavy work — LLM steps, web search,
DB reads — runs off the event loop in a thread. Cost is held down three ways: the
corpus is tried before the web (in the runner), a repeated question hits the
cache, and each fresh question spends one unit of a per-day budget.
"""

import asyncio
import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from ogoh.agent import audit, budget, cache
from ogoh.agent.runner import run_turn
from ogoh.agent.search import build_search_provider
from ogoh.agent.types import AgentReply, Turn
from ogoh.bot.handlers import _get_or_create
from ogoh.config import get_settings
from ogoh.db.models import User
from ogoh.db.session import session_scope
from ogoh.llm.gemini import GeminiProvider

log = logging.getLogger(__name__)

agent_router = Router()


class AgentStates(StatesGroup):
    chatting = State()


@agent_router.message(Command("ask"))
async def handle_ask(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        enabled = user.agent_enabled
    if not enabled:
        # No hint that the feature exists — it is off for this person on purpose.
        await message.answer("Bu funksiya sen uchun yoqilmagan.")
        return

    await state.set_state(AgentStates.chatting)
    await state.set_data({"transcript": [], "awaiting": False, "ts": _now_iso()})
    await message.answer(
        "Savolingni yoz — yangilik yoki ma'lumotni qidirib topaman.\n"
        "Tugatish: <b>/done</b>"
    )


@agent_router.message(AgentStates.chatting, Command("done"))
async def handle_done(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Suhbat yopildi. Qayta boshlash: /ask")


@agent_router.message(AgentStates.chatting, F.text, ~F.text.startswith("/"))
async def handle_agent_message(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not message.text:
        return

    data = await state.get_data()
    awaiting = bool(data.get("awaiting"))
    transcript = list(data.get("transcript", []))
    # An idle gap ends the previous thread: a dangling clarification goes stale,
    # and the next message starts clean so context can't pile up unbounded.
    if awaiting and _stale(data.get("ts")):
        awaiting = False
        transcript = []
    is_fresh = not awaiting

    _kind, text, sources, new_transcript, new_awaiting = await asyncio.to_thread(
        _process, message.from_user.id, message.text.strip(), transcript, is_fresh
    )

    await state.set_data(
        {"transcript": new_transcript, "awaiting": new_awaiting, "ts": _now_iso()}
    )
    await message.answer(_render(text, sources), link_preview_options={"is_disabled": True})


def _process(
    telegram_id: int, user_message: str, transcript_dicts: list[dict], is_fresh: bool
) -> tuple[str, str, list[str], list[dict], bool]:
    """All the blocking work for one message. Pure over its inputs; own session."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return "answer", "Agent hozircha ishlamayapti (LLM sozlanmagan).", [], [], False

    transcript = [Turn(role=d["role"], content=d["content"]) for d in transcript_dicts]

    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None or not user.agent_enabled:
            return "answer", "Bu funksiya sen uchun yoqilmagan.", [], [], False

        if is_fresh:
            cached = cache.get_cached(session, user_message, settings.agent_cache_ttl_hours)
            if cached is not None:
                audit.log_exchange(session, user.id, user_message, cached)
                return "answer", cached, [], [], False
            if budget.remaining(session, user.id, settings.agent_daily_budget) <= 0:
                limit_msg = "Bugungi limit tugadi. Ertaga qayta urin."
                audit.log_exchange(session, user.id, user_message, limit_msg)
                return "answer", limit_msg, [], [], False

        brain = GeminiProvider(api_key=settings.gemini_api_key, model=settings.agent_model)
        heavy = None
        if settings.agent_model_heavy and settings.agent_model_heavy != settings.agent_model:
            heavy = GeminiProvider(api_key=settings.gemini_api_key, model=settings.agent_model_heavy)
        search = build_search_provider(settings)
        try:
            reply = run_turn(
                session, brain, search, user_message, transcript, settings, heavy_brain=heavy
            )
            failed = False
        except Exception:
            # The model call itself fell over (429, timeout, bad response). Do not
            # charge for a question we could not answer, and never let it surface
            # as an unhandled error in the message handler.
            log.exception("agent run failed for user %d", user.id)
            reply = AgentReply("answer", "Kechirasan, hozir javob berolmadim. Birozdan keyin urin.")
            failed = True

        if is_fresh and not failed:
            budget.spend(session, user.id)
            if reply.kind == "answer":
                cache.put_cached(session, user_message, reply.text)
        audit.log_exchange(session, user.id, user_message, reply.text)

    awaiting = reply.kind == "question"
    kept = [{"role": t.role, "content": t.content} for t in transcript] if awaiting else []
    return reply.kind, reply.text, reply.sources, kept, awaiting


def _render(text: str, sources: list[str]) -> str:
    from html import escape

    body = escape(text)
    if sources:
        links = "\n".join(f"• {escape(url)}" for url in sources[:5])
        body += f"\n\n<i>Manbalar:</i>\n{links}"
    return body


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stale(ts: str | None) -> bool:
    if not ts:
        return True
    minutes = get_settings().agent_idle_timeout_minutes
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return True
    return (datetime.now(UTC) - when).total_seconds() > minutes * 60
