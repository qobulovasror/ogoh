from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ogoh.taxonomy import TAGS

TOPIC_PREFIX = "topic"
FREQ_PREFIX = "freq"
DONE = "done"

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
