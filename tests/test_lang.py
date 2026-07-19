"""Summary language.

Both summaries are written in the same enrichment call, so Uzbek costs no extra
quota. The fallback is the part worth pinning: rows enriched before summary_uz
existed have none, and a subscriber reading an English line is better served than
one reading a blank.
"""

from sqlalchemy import select
from stubs import StubCallback, StubMessage

from ogoh.bot import handlers
from ogoh.db.models import User
from ogoh.pipeline.digest import render_telegram, summary_for, top_entries


def _enriched(make_item, make_enrichment, session, *, uz: str | None):
    item = make_item("A new model ships")
    enrichment = make_enrichment(item, importance=8)
    enrichment.summary = "OpenAI shipped a model."
    enrichment.summary_uz = uz
    session.flush()
    return enrichment


def test_uzbek_is_used_when_present(session, make_item, make_enrichment):
    enrichment = _enriched(make_item, make_enrichment, session, uz="OpenAI model chiqardi.")
    assert summary_for(enrichment, "uz") == "OpenAI model chiqardi."


def test_english_is_used_when_asked_for(session, make_item, make_enrichment):
    enrichment = _enriched(make_item, make_enrichment, session, uz="OpenAI model chiqardi.")
    assert summary_for(enrichment, "en") == "OpenAI shipped a model."


def test_a_missing_translation_falls_back(session, make_item, make_enrichment):
    # Rows enriched before summary_uz existed. An English line beats a blank.
    enrichment = _enriched(make_item, make_enrichment, session, uz=None)
    assert summary_for(enrichment, "uz") == "OpenAI shipped a model."


def test_an_empty_translation_falls_back(session, make_item, make_enrichment):
    enrichment = _enriched(make_item, make_enrichment, session, uz="")
    assert summary_for(enrichment, "uz") == "OpenAI shipped a model."


def test_the_digest_renders_in_the_chosen_language(session, make_item, make_enrichment):
    _enriched(make_item, make_enrichment, session, uz="OpenAI model chiqardi.")
    entries = top_entries(session, min_importance=5, limit=10)

    assert "OpenAI model chiqardi." in render_telegram(entries, lang="uz")
    assert "OpenAI shipped a model." in render_telegram(entries, lang="en")


async def test_lang_command_sets_the_language(session):
    await handlers.handle_start(StubMessage())

    await handlers.handle_lang_set(StubCallback(data="lang:en"))

    session.expire_all()
    assert session.scalar(select(User).where(User.telegram_id == 42)).lang == "en"


async def test_an_unknown_language_is_refused(session):
    await handlers.handle_start(StubMessage())

    callback = StubCallback(data="lang:klingon")
    await handlers.handle_lang_set(callback)

    session.expire_all()
    assert session.scalar(select(User).where(User.telegram_id == 42)).lang == "uz"
    assert callback.answered == ["Noma'lum til"]


async def test_uzbek_is_the_default(session):
    await handlers.handle_start(StubMessage())
    assert session.scalar(select(User).where(User.telegram_id == 42)).lang == "uz"
