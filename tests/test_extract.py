"""Extraction, with the network faked.

This step exists because feeds hand over teasers: OpenAI's flagship launch scored
2/10 on a 144-character lead and 10/10 on the article. The tests below guard the
rules that make that safe — never overwrite good text with worse, never touch
what a source says is already whole, never refetch a paywall forever.
"""

import pytest

from ogoh.pipeline import extract
from ogoh.pipeline.extract import THIN_TEXT_CHARS, extract_pending


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replace the network. Maps url -> extracted text, or None for a failure."""
    responses: dict[str, str | None] = {}
    calls: list[str] = []

    def _fetch(url: str) -> str | None:
        calls.append(url)
        return responses.get(url)

    monkeypatch.setattr(extract, "_fetch_text", _fetch)
    return type("FakeFetch", (), {"responses": responses, "calls": calls})()


def test_thin_items_get_the_article(session, make_item, fake_fetch):
    item = make_item("Item", raw_text="A teaser.")
    fake_fetch.responses[item.url] = "x" * 5000

    stats = extract_pending(session)

    assert stats.improved == 1
    assert len(item.raw_text) == 5000


def test_items_that_already_have_the_article_are_skipped(session, make_item, fake_fetch):
    make_item("Item", raw_text="x" * (THIN_TEXT_CHARS + 1))

    stats = extract_pending(session)

    assert stats.attempted == 0
    assert fake_fetch.calls == []


def test_a_source_that_says_its_text_is_whole_is_believed(session, make_item, fake_fetch):
    # The changelog's URL is the entire release notes page and its text is one
    # day's section — short enough to look thin. Fetching it would replace a
    # single day's entry with every entry on the page.
    item = make_item("Release notes — July 10", raw_text="Short but complete.", text_complete=True)
    fake_fetch.responses[item.url] = "the whole page " * 500

    stats = extract_pending(session)

    assert stats.attempted == 0
    assert item.raw_text == "Short but complete."


def test_a_worse_fetch_is_discarded(session, make_item, fake_fetch):
    # trafilatura can come back with a nav rail or a consent notice. Overwriting
    # a real lead with that is a downgrade nobody would ever notice.
    item = make_item("Item", raw_text="A" * 500)
    fake_fetch.responses[item.url] = "Accept cookies"

    stats = extract_pending(session)

    assert stats.improved == 0
    assert item.raw_text == "A" * 500


def test_an_item_with_no_text_at_all_is_fetched(session, make_item, fake_fetch):
    # Hugging Face's feed has no text field — title and link, nothing else.
    item = make_item("Item", raw_text=None)
    fake_fetch.responses[item.url] = "The article."

    extract_pending(session)

    assert item.raw_text == "The article."


def test_a_refusal_leaves_the_feed_lead_in_place(session, make_item, fake_fetch):
    # Sites that mean to refuse bots are respected; the item keeps what it had.
    item = make_item("Item", raw_text="A teaser.")
    fake_fetch.responses[item.url] = None

    stats = extract_pending(session)

    assert stats.failed == 1
    assert item.raw_text == "A teaser."


def test_a_failure_is_not_retried_forever(session, make_item, fake_fetch):
    # A paywall does not get better in twenty minutes.
    item = make_item("Item", raw_text="A teaser.")
    fake_fetch.responses[item.url] = None

    extract_pending(session)
    extract_pending(session)

    assert len(fake_fetch.calls) == 1
    assert item.text_extracted_at is not None


def test_success_is_not_refetched_either(session, make_item, fake_fetch):
    item = make_item("Item", raw_text="A teaser.")
    fake_fetch.responses[item.url] = "The article, at length."

    extract_pending(session)
    extract_pending(session)

    assert len(fake_fetch.calls) == 1


def test_stored_text_is_capped(session, make_item, fake_fetch):
    item = make_item("Item", raw_text="A teaser.")
    fake_fetch.responses[item.url] = "x" * 100_000

    extract_pending(session)

    assert len(item.raw_text) == extract._MAX_TEXT_CHARS


def test_one_failure_does_not_stop_the_batch(session, make_item, fake_fetch):
    good = make_item("Good", raw_text="teaser")
    bad = make_item("Bad", raw_text="teaser")
    fake_fetch.responses[good.url] = "The good article, at length."
    fake_fetch.responses[bad.url] = None

    stats = extract_pending(session)

    assert stats.improved == 1
    assert stats.failed == 1
