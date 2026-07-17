"""Feedback collection.

Nothing consumes these votes yet, on purpose: with a handful of subscribers the
data is far too sparse to tune against, and a scoring rule invented for data that
does not exist would be a guess wearing a number. What cannot wait is the
recording — votes are not collectable retroactively.
"""

from sqlalchemy import func, select
from stubs import StubCallback, StubMessage, StubUser

from ogoh.bot import handlers
from ogoh.bot.keyboards import MAX_FEEDBACK_ROWS, feedback_keyboard
from ogoh.db.models import Feedback
from ogoh.pipeline.digest import top_entries


async def test_a_vote_is_recorded(session, make_item, make_enrichment):
    item = make_item("A new model ships")
    make_enrichment(item, importance=8)
    session.commit()
    await handlers.handle_start(StubMessage())

    cluster = item.cluster_id or item.id
    await handlers.handle_vote(StubCallback(data=f"vote:{cluster}:1"))

    session.expire_all()
    stored = session.scalar(select(Feedback))
    assert stored.cluster_id == cluster
    assert stored.vote == 1


async def test_changing_your_mind_overwrites(session, make_item, make_enrichment):
    item = make_item("A new model ships")
    make_enrichment(item, importance=8)
    session.commit()
    await handlers.handle_start(StubMessage())
    cluster = item.cluster_id or item.id

    await handlers.handle_vote(StubCallback(data=f"vote:{cluster}:1"))
    await handlers.handle_vote(StubCallback(data=f"vote:{cluster}:-1"))

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Feedback)) == 1
    assert session.scalar(select(Feedback)).vote == -1


async def test_two_people_vote_independently(session, make_item, make_enrichment):
    item = make_item("A new model ships")
    make_enrichment(item, importance=8)
    session.commit()
    await handlers.handle_start(StubMessage(from_user=StubUser(id=1, username="a")))
    await handlers.handle_start(StubMessage(from_user=StubUser(id=2, username="b")))
    cluster = item.cluster_id or item.id

    await handlers.handle_vote(StubCallback(data=f"vote:{cluster}:1", from_user=StubUser(id=1)))
    await handlers.handle_vote(StubCallback(data=f"vote:{cluster}:-1", from_user=StubUser(id=2)))

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Feedback)) == 2


async def test_a_malformed_callback_is_ignored(session):
    await handlers.handle_start(StubMessage())

    for payload in ("vote:notanumber:1", "vote:1", "vote:1:5", "vote:1:x"):
        await handlers.handle_vote(StubCallback(data=payload))

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Feedback)) == 0


async def test_the_keyboard_numbers_match_the_digest(session, make_item, make_enrichment):
    # The buttons hang off the message, not off a paragraph, so the number in the
    # text is the only thing tying a button to a story. If those drift apart the
    # votes land on the wrong stories and nothing looks wrong.
    for i in range(3):
        make_enrichment(make_item(f"Story {i}"), importance=10 - i)

    entries = top_entries(session, min_importance=5, limit=10)
    keyboard = feedback_keyboard(entries)

    for position, (row, entry) in enumerate(zip(keyboard.inline_keyboard, entries), start=1):
        cluster = entry.item.cluster_id or entry.item.id
        assert row[0].text.startswith(f"{position} ")
        assert row[0].callback_data == f"vote:{cluster}:1"
        assert row[1].callback_data == f"vote:{cluster}:-1"


async def test_the_keyboard_does_not_become_a_wall(session, make_item, make_enrichment):
    for i in range(10):
        make_enrichment(make_item(f"Story {i}"), importance=8)

    entries = top_entries(session, min_importance=5, limit=10)
    keyboard = feedback_keyboard(entries)

    assert len(keyboard.inline_keyboard) == MAX_FEEDBACK_ROWS


def test_an_empty_digest_gets_no_keyboard():
    assert feedback_keyboard([]) is None
