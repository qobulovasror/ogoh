"""Bot commands.

Database calls here are the synchronous ones used everywhere else, invoked
straight from async handlers. That is deliberate at this size: each is a
sub-millisecond SQLite statement against a table of tens of rows, and the pause
it puts on the event loop is far below anything a person could notice. The
pipeline is the opposite kind of work and runs in a thread — see worker.py.
"""

import logging
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.bot.keyboards import (
    DONE,
    FREQ_PREFIX,
    HOUR_PREFIX,
    LANG_PREFIX,
    LEVEL_KEYS,
    LEVEL_PREFIX,
    TOPIC_PREFIX,
    TZ_PREFIX,
    VOTE_PREFIX,
    ZONE_KEYS,
    feedback_keyboard,
    freq_keyboard,
    freq_label,
    hour_keyboard,
    lang_keyboard,
    lang_label,
    level_keyboard,
    level_label,
    topics_keyboard,
    tz_keyboard,
)
from ogoh.config import get_settings
from ogoh.db.models import Feedback, Item, ItemEnrichment, Source, User, UserKeyword, UserTopic
from ogoh.db.session import session_scope
from ogoh.pipeline.digest import as_utc, render_telegram
from ogoh.pipeline.match import pending_for_user
from ogoh.taxonomy import LABELS_UZ, TAG_KEYS

log = logging.getLogger(__name__)

router = Router()

_WELCOME = (
    "Salom! Men <b>Ogoh</b>man.\n\n"
    "AI olamidagi yangiliklarni kuzataman — yangi modellar, narx va limit "
    "o'zgarishlari, API yangiliklari — va faqat senga keragini yuboraman.\n\n"
    "<b>/topics</b> — qaysi mavzular qiziq\n"
    "<b>/keywords</b> — erkin kalit so'zlar\n"
    "<b>/freq</b> — qanchalik tez-tez xabar berish\n"
    "<b>/time</b> — kunlik yig'ma soati\n"
    "<b>/zone</b> — vaqt mintaqang\n"
    "<b>/level</b> — muhimlik chegarasi\n"
    "<b>/preview</b> — hozir nima bor, ko'rib ol\n"
    "<b>/lang</b> — xulosalar tili\n"
    "<b>/settings</b> — hamma sozlama bir joyda\n"
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
        text = render_telegram(entries, lang=user.lang)
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


@router.message(Command("lang"))
async def handle_lang(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        current = user.lang
    await message.answer("Xulosalar tili?", reply_markup=lang_keyboard(current))


@router.callback_query(F.data.startswith(f"{LANG_PREFIX}:"))
async def handle_lang_set(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return
    code = callback.data.split(":", 1)[1]
    if code not in ("uz", "en"):
        await callback.answer("Noma'lum til")
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        user.lang = code

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Til: <b>{lang_label(code)}</b>")
    await callback.answer()


@router.message(Command("time"))
async def handle_time(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        current = user.digest_hour
    await message.answer(
        "Kunlik yig'ma soati? <i>(vaqt mintaqang bo'yicha — /zone bilan o'zgartir)</i>",
        reply_markup=hour_keyboard(current),
    )


@router.callback_query(F.data.startswith(f"{HOUR_PREFIX}:"))
async def handle_hour_set(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return
    try:
        hour = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    if not 0 <= hour <= 23:
        await callback.answer("Noto'g'ri soat")
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        # last_digest_at is left alone on purpose: the 23h gap in is_due is what
        # stops a same-day change re-sending, and clearing it here would undo that.
        user.digest_hour = hour

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Yig'ma soati: <b>{hour:02d}:00</b>")
    await callback.answer()


@router.message(Command("zone"))
async def handle_zone(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        current = user.timezone
    await message.answer("Vaqt mintaqang?", reply_markup=tz_keyboard(current))


@router.callback_query(F.data.startswith(f"{TZ_PREFIX}:"))
async def handle_zone_set(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return
    zone = callback.data.split(":", 1)[1]
    if zone not in ZONE_KEYS:
        await callback.answer("Noma'lum mintaqa")
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        user.timezone = zone

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Vaqt mintaqa: <b>{zone}</b>")
    await callback.answer()


@router.message(Command("level"))
async def handle_level(message: Message) -> None:
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        current = user.min_importance
    await message.answer(
        "Qanchalik muhim yangilik kerak? Pastroq chegara ko'proq xabar demakdir.",
        reply_markup=level_keyboard(current),
    )


@router.callback_query(F.data.startswith(f"{LEVEL_PREFIX}:"))
async def handle_level_set(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.data, str):
        return
    try:
        level = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    if level not in LEVEL_KEYS:
        await callback.answer("Noma'lum daraja")
        return

    with session_scope() as session:
        user = _get_or_create(session, callback.from_user.id, callback.from_user.username)
        user.min_importance = level

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"Muhimlik chegarasi: <b>{level}+</b>")
    await callback.answer()


# A guard, not a real limit: nobody filters on twenty words, but an accidental
# paste of a paragraph should not become two hundred rows.
_MAX_KEYWORDS = 20


def _parse_keywords(raw: str) -> list[str]:
    seen: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        keyword = part.strip().lower()[:32]
        if keyword and keyword not in seen:
            seen.append(keyword)
        if len(seen) >= _MAX_KEYWORDS:
            break
    return seen


@router.message(Command("keywords"))
async def handle_keywords(message: Message, command: CommandObject) -> None:
    """Free-text interests, on top of the fixed /topics taxonomy.

    `/keywords` shows the current list; `/keywords MCP, Anthropic` replaces it;
    `/keywords tozala` clears it. Replace rather than append: a set the reader can
    see in full and retype is simpler than an add/remove protocol over chat.
    """
    if message.from_user is None:
        return
    raw = (command.args or "").strip()

    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)

        if not raw:
            current = [keyword.keyword for keyword in user.keywords]
            shown = escape(", ".join(current)) if current else "(bo'sh)"
            await message.answer(
                f"Kalit so'zlaring: <b>{shown}</b>\n\n"
                "O'zgartirish: <code>/keywords MCP, Anthropic, rate limit</code>\n"
                "Tozalash: <code>/keywords tozala</code>\n\n"
                "<i>Mavzu teglaridan tashqari — sarlavha yoki nomlarda shu so'z "
                "uchrasa, yangilik o'tadi.</i>"
            )
            return

        for existing in list(user.keywords):
            session.delete(existing)
        session.flush()

        if raw.lower() in ("tozala", "clear", "-"):
            await message.answer("Kalit so'zlar tozalandi.")
            return

        keywords = _parse_keywords(raw)
        for keyword in keywords:
            session.add(UserKeyword(user_id=user.id, keyword=keyword))
        shown = escape(", ".join(keywords)) if keywords else "(bo'sh)"

    await message.answer(f"Saqlandi: <b>{shown}</b>")


@router.message(Command("settings"))
async def handle_settings(message: Message) -> None:
    """Every current preference on one screen, with the command that changes each."""
    if message.from_user is None:
        return
    with session_scope() as session:
        user = _get_or_create(session, message.from_user.id, message.from_user.username)
        topics = [LABELS_UZ.get(topic.tag, topic.tag) for topic in user.topics]
        keywords = [keyword.keyword for keyword in user.keywords]
        topics_shown = ", ".join(topics) if topics else "hammasi"
        keywords_shown = escape(", ".join(keywords)) if keywords else "(bo'sh)"
        text = (
            "<b>Sozlamalar</b>\n\n"
            f"Rejim: <b>{freq_label(user.digest_mode)}</b>  /freq\n"
            f"Vaqt: <b>{user.digest_hour:02d}:00</b> ({user.timezone})  /time /zone\n"
            f"Muhimlik: <b>{level_label(user.min_importance)}</b>  /level\n"
            f"Til: <b>{lang_label(user.lang)}</b>  /lang\n"
            f"Mavzular: <b>{topics_shown}</b>  /topics\n"
            f"Kalit so'zlar: <b>{keywords_shown}</b>  /keywords"
        )
    await message.answer(text)


# A feed we fetched but that returned nothing for a week is the silent failure
# the plan warns about — DeepMind's rss.xml parses fine and is permanently empty.
# This window is what tells a live-but-quiet source from a dead one.
_SOURCE_HEALTH_DAYS = 7


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "hech qachon"
    seconds = (now - as_utc(when)).total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)} daq oldin"
    if seconds < 86400:
        return f"{int(seconds // 3600)} soat oldin"
    return f"{int(seconds // 86400)} kun oldin"


@router.message(Command("sources"))
async def handle_sources(message: Message) -> None:
    """Which feeds are alive. A source with zero items in a week is flagged.

    Read-only and cheap; useful to anyone, but the real audience is whoever runs
    the bot and needs to notice a feed that has quietly stopped returning news.
    """
    if message.from_user is None:
        return
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_SOURCE_HEALTH_DAYS)

    with session_scope() as session:
        _get_or_create(session, message.from_user.id, message.from_user.username)
        rows = session.execute(
            select(Source, func.count(Item.id))
            .outerjoin(Item, (Item.source_id == Source.id) & (Item.fetched_at >= cutoff))
            .where(Source.enabled.is_(True))
            .group_by(Source.id)
            .order_by(Source.trust_tier, Source.name)
        ).all()

    if not rows:
        await message.answer("Hali manba yo'q.")
        return

    lines = [f"<b>Manbalar</b> (oxirgi {_SOURCE_HEALTH_DAYS} kun)\n"]
    for source, count in rows:
        mark = "✅" if count else "⚠️"
        lines.append(
            f"{mark} {escape(source.name)} — <b>{count}</b> ta · {_ago(source.last_fetched_at, now)}"
        )
    await message.answer("\n".join(lines))


def _provider_label(settings) -> str:
    parts = []
    if settings.gemini_api_key:
        parts.append("gemini")
    if settings.groq_api_key:
        parts.append("groq")
    return " + ".join(parts) or "yo'q"


@router.message(Command("stats"))
async def handle_stats(message: Message) -> None:
    """Aggregate health at a glance — how many subscribers, how much news is
    flowing, which feeds are quiet. Aggregates only, no per-person data."""
    if message.from_user is None:
        return
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=_SOURCE_HEALTH_DAYS)

    with session_scope() as session:
        _get_or_create(session, message.from_user.id, message.from_user.username)

        users = session.scalar(select(func.count()).select_from(User)) or 0
        active = (
            session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
            or 0
        )
        sources = (
            session.scalar(
                select(func.count()).select_from(Source).where(Source.enabled.is_(True))
            )
            or 0
        )
        # Enabled feeds with nothing in the last week — the silent-death count.
        fed_recently = select(Item.source_id).where(Item.fetched_at >= week_ago).distinct()
        quiet = (
            session.scalar(
                select(func.count())
                .select_from(Source)
                .where(Source.enabled.is_(True))
                .where(Source.id.not_in(fed_recently))
            )
            or 0
        )
        items_total = session.scalar(select(func.count()).select_from(Item)) or 0
        items_day = (
            session.scalar(select(func.count()).select_from(Item).where(Item.fetched_at >= day_ago))
            or 0
        )
        enriched_day = (
            session.scalar(
                select(func.count())
                .select_from(ItemEnrichment)
                .where(ItemEnrichment.enriched_at >= day_ago)
            )
            or 0
        )

    text = (
        "<b>📊 Holat</b>\n\n"
        f"Obunachilar: <b>{users}</b> ({active} faol)\n"
        f"Manbalar: <b>{sources}</b> ta"
        + (f" · <b>{quiet}</b> jim ⚠️" if quiet else "")
        + "\n"
        f"Yangiliklar: 24 soatda <b>{items_day}</b> (jami {items_total})\n"
        f"Baholangan: 24 soatda <b>{enriched_day}</b>\n"
        f"LLM: <b>{_provider_label(get_settings())}</b>"
    )
    await message.answer(text)


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
    # This deactivates; it does not delete. The row keeps the telegram id, the
    # username, the chosen topics, every feedback vote, and the dated ledger of
    # everything ever delivered. Saying "deleted" while holding all of that was
    # untrue, and the wording is the part that can be fixed in one line — real
    # deletion needs a cascade across four tables and a decision about whether
    # /start should then be able to bring the account back at all.
    await message.answer(
        "Obuna bekor qilindi — endi hech narsa yubormayman.\n"
        "Sozlamalaring saqlanib qoladi, <b>/start</b> bilan o'sha yerdan davom etasan."
    )


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
