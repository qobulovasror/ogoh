from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ogoh.taxonomy import TAGS

TOPIC_PREFIX = "topic"
FREQ_PREFIX = "freq"
VOTE_PREFIX = "vote"
LANG_PREFIX = "lang"
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
