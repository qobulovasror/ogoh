"""Bot commands.

Database calls here are the synchronous ones used everywhere else, invoked
straight from async handlers. That is deliberate at this size: each is a
sub-millisecond SQLite statement against a table of tens of rows, and the pause
it puts on the event loop is far below anything a person could notice. The
pipeline is the opposite kind of work and runs in a thread — see worker.py.
"""

import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import Session

from ogoh.bot.keyboards import (
    DONE,
    FREQ_PREFIX,
    TOPIC_PREFIX,
    VOTE_PREFIX,
    feedback_keyboard,
    freq_keyboard,
    freq_label,
    topics_keyboard,
)
from ogoh.db.models import Feedback, User, UserTopic
from ogoh.db.session import session_scope
from ogoh.pipeline.digest import render_telegram
from ogoh.pipeline.match import pending_for_user
from ogoh.taxonomy import TAG_KEYS

log = logging.getLogger(__name__)

router = Router()

_WELCOME = (
    "Salom! Men <b>Ogoh</b>man.\n\n"
    "AI olamidagi yangiliklarni kuzataman — yangi modellar, narx va limit "
    "o'zgarishlari, API yangiliklari — va faqat senga keragini yuboraman.\n\n"
    "<b>/topics</b> — qaysi mavzular qiziq\n"
    "<b>/freq</b> — qanchalik tez-tez xabar berish\n"
    "<b>/preview</b> — hozir nima bor, ko'rib ol\n"
    "<b>/pause</b> — vaqtincha to'xtatish\n"
    "<b>/stop</b> — butunlay o'chirish\n\n"
    "Hozircha barcha mavzular yoqilgan. <b>/topics</b> bilan toraytir."
)


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        user.is_active = True
    await message.answer(_WELCOME)


@router.message(Command("topics"))
async def handle_topics(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        selected = {topic.tag for topic in user.topics}
    await message.answer(
        "Qaysi mavzular kerak? Bosib yoq/o'chir.\n"
        "<i>Hech biri tanlanmasa — hammasi yuboriladi.</i>",
        reply_markup=topics_keyboard(selected),
    )


@router.callback_query(F.data.startswith(f"{TOPIC_PREFIX}:"))
async def handle_topic_toggle(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return
    tag = callback.data.split(":", 1)[1]
    if tag not in TAG_KEYS:
        await callback.answer("Noma'lum mavzu")
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        existing = session.get(UserTopic, (user.id, tag))
        if existing is None:
            session.add(UserTopic(user_id=user.id, tag=tag))
        else:
            session.delete(existing)
        session.flush()
        session.refresh(user)
        selected = {topic.tag for topic in user.topics}

    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=topics_keyboard(selected))
    await callback.answer()


@router.callback_query(F.data == DONE)
async def handle_done(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        count = len(user.topics)
    text = "Hammasi yoqilgan." if count == 0 else f"{count} ta mavzu tanlandi."
    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Saqlandi. {text}")
    await callback.answer()


@router.message(Command("freq"))
async def handle_freq(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        current = user.digest_mode
    await message.answer("Qanchalik tez-tez?", reply_markup=freq_keyboard(current))


@router.callback_query(F.data.startswith(f"{FREQ_PREFIX}:"))
async def handle_freq_set(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return
    mode = callback.data.split(":", 1)[1]
    if mode not in ("instant", "daily", "weekly", "off"):
        await callback.answer("Noma'lum rejim")
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        user.digest_mode = mode

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Rejim: <b>{freq_label(mode)}</b>")
    await callback.answer()


@router.message(Command("preview"))
async def handle_preview(message: Message) -> None:
    """Shows what would be sent without recording it as delivered.

    Someone who just set their topics wants to see the effect now, not tomorrow
    at nine. Deliberately does not write to `deliveries` — a preview must not
    burn the stories out of the next real digest.
    """
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        entries = pending_for_user(session, user, limit=5)
        text = render_telegram(entries)
        keyboard = feedback_keyboard(entries)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{VOTE_PREFIX}:"))
async def handle_vote(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return

    try:
        cluster_id, vote = int(parts[1]), int(parts[2])
    except ValueError:
        await callback.answer()
        return

    if vote not in (1, -1):
        await callback.answer()
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        existing = session.get(Feedback, (user.id, cluster_id))
        if existing is None:
            session.add(
                Feedback(
                    user_id=user.id,
                    cluster_id=cluster_id,
                    vote=vote,
                    created_at=datetime.now(UTC),
                )
            )
        else:
            # Changing your mind overwrites rather than stacking.
            existing.vote = vote
            existing.created_at = datetime.now(UTC)

    await callback.answer("Rahmat 👍" if vote == 1 else "Qayd etildi 👎")


@router.message(Command("pause"))
async def handle_pause(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        user.digest_mode = "off"
    await message.answer("To'xtatildi. <b>/freq</b> bilan qayta yoqasan.")


@router.message(Command("stop"))
async def handle_stop(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        user.is_active = False
        user.digest_mode = "off"
    await message.answer("O'chirildi. <b>/start</b> bilan qaytasan.")


def _get_or_create(session: Session, telegram_id: int, username: str | None) -> User:
    user = session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id, username=username, created_at=datetime.now(UTC))
        session.add(user)
        session.flush()
        log.info("registered telegram user %d", telegram_id)
    elif user.username != username:
        user.username = username
    return user
