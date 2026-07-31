from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ogoh.taxonomy import TAGS

TOPIC_PREFIX = "topic"
FREQ_PREFIX = "freq"
VOTE_PREFIX = "vote"
LANG_PREFIX = "lang"
HOUR_PREFIX = "hour"
TZ_PREFIX = "tz"
LEVEL_PREFIX = "level"
DONE = "done"

# A digest of ten stories would be twenty buttons — a wall under every message.
# The top few carry most of the signal anyway.
MAX_FEEDBACK_ROWS = 5

_FREQ_LABELS = {
    "instant": "Darhol (faqat muhimi)",
    "daily": "Kunlik",
    "weekly": "Haftalik",
    "off": "O'chirilgan",
}


def topics_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tag in TAGS:
        mark = "✅" if tag.key in selected else "▫️"
        builder.button(text=f"{mark} {tag.label_uz}", callback_data=f"{TOPIC_PREFIX}:{tag.key}")
    builder.adjust(2)
    builder.button(text="Tayyor", callback_data=DONE)
    return builder.as_markup()


def freq_keyboard(current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for mode, label in _FREQ_LABELS.items():
        mark = "✅" if mode == current else "▫️"
        builder.button(text=f"{mark} {label}", callback_data=f"{FREQ_PREFIX}:{mode}")
    builder.adjust(1)
    return builder.as_markup()


def freq_label(mode: str) -> str:
    return _FREQ_LABELS.get(mode, mode)


_LANG_LABELS = {"uz": "O'zbekcha", "en": "English"}


def lang_keyboard(current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in _LANG_LABELS.items():
        mark = "✅" if code == current else "▫️"
        builder.button(text=f"{mark} {label}", callback_data=f"{LANG_PREFIX}:{code}")
    builder.adjust(1)
    return builder.as_markup()


def lang_label(code: str) -> str:
    return _LANG_LABELS.get(code, code)


def hour_keyboard(current: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hour in range(24):
        mark = "✅ " if hour == current else ""
        builder.button(text=f"{mark}{hour:02d}:00", callback_data=f"{HOUR_PREFIX}:{hour}")
    builder.adjust(6)
    return builder.as_markup()


# A curated set rather than the full zoneinfo list: a few hundred buttons is not a
# picker. Covers this bot's readers and the common diaspora hops. Anyone elsewhere
# keeps the default and their digest still lands, an hour or two off.
_ZONES: dict[str, str] = {
    "Asia/Tashkent": "Toshkent",
    "Asia/Almaty": "Almati",
    "Europe/Moscow": "Moskva",
    "Asia/Istanbul": "Istanbul",
    "Asia/Dubai": "Dubay",
    "Europe/London": "London",
    "America/New_York": "Nyu-York",
    "UTC": "UTC",
}


def tz_keyboard(current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for zone, label in _ZONES.items():
        mark = "✅ " if zone == current else ""
        builder.button(text=f"{mark}{label}", callback_data=f"{TZ_PREFIX}:{zone}")
    builder.adjust(2)
    return builder.as_markup()


# The thresholds worth offering. The rubric in prompts.py makes 8 the "launches and
# limit changes only" line and 5 the everyday floor; 3 lets the merely-interesting
# through. Free-form 0-10 would be a slider nobody would tune sensibly.
_LEVELS: dict[int, str] = {
    8: "Faqat eng muhimi (8+)",
    5: "Muvozanat (5+)",
    3: "Ko'proq (3+)",
}


def level_keyboard(current: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for level, label in _LEVELS.items():
        mark = "✅ " if level == current else ""
        builder.button(text=f"{mark}{label}", callback_data=f"{LEVEL_PREFIX}:{level}")
    builder.adjust(1)
    return builder.as_markup()


def level_label(level: int) -> str:
    return _LEVELS.get(level, f"{level}+")


# What the callbacks accept — the picker is the whole menu, so anything off it is a
# stale or forged callback and is refused rather than written to the row.
ZONE_KEYS: frozenset[str] = frozenset(_ZONES)
LEVEL_KEYS: frozenset[int] = frozenset(_LEVELS)


def feedback_keyboard(entries: Sequence) -> InlineKeyboardMarkup | None:
    """One row per story, numbered to match the digest text.

    Telegram attaches a keyboard to a message, not to a paragraph inside it, so
    the numbering is what ties a button to the story it is about.
    """
    if not entries:
        return None

    builder = InlineKeyboardBuilder()
    for position, entry in enumerate(entries[:MAX_FEEDBACK_ROWS], start=1):
        cluster = entry.item.cluster_id or entry.item.id
        builder.row(
            InlineKeyboardButton(text=f"{position} 👍", callback_data=f"{VOTE_PREFIX}:{cluster}:1"),
            InlineKeyboardButton(text=f"{position} 👎", callback_data=f"{VOTE_PREFIX}:{cluster}:-1"),
        )
    return builder.as_markup()
