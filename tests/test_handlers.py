"""Bot commands, against stub updates.

These assert what the handlers do to the database, not what Telegram renders.
The stubs are not aiogram Message instances, so the isinstance-guarded
edit_text/edit_reply_markup calls are skipped — which is fine here: the risk in
this file is a subscription silently not being saved, not a keyboard drawn wrong.
"""

from sqlalchemy import func, select
from stubs import StubCallback, StubMessage, StubUser

from ogoh.bot import handlers
from ogoh.db.models import Delivery, User, UserTopic


async def test_start_registers_the_person(session):
    message = StubMessage()

    await handlers.handle_start(message)

    stored = session.scalar(select(User).where(User.telegram_id == 42))
    assert stored is not None
    assert stored.username == "tester"
    assert stored.is_active is True
    assert message.replies


async def test_start_twice_does_not_duplicate(session):
    await handlers.handle_start(StubMessage())
    await handlers.handle_start(StubMessage())

    assert session.scalar(select(func.count()).select_from(User)) == 1


async def test_start_reactivates_someone_who_left(session, make_user):
    await handlers.handle_start(StubMessage())
    session.expire_all()
    user = session.scalar(select(User).where(User.telegram_id == 42))
    user.is_active = False
    user.digest_mode = "off"
    session.commit()

    await handlers.handle_start(StubMessage())

    session.expire_all()
    assert session.scalar(select(User).where(User.telegram_id == 42)).is_active is True


async def test_a_renamed_account_is_updated(session):
    await handlers.handle_start(StubMessage(from_user=StubUser(username="before")))
    await handlers.handle_start(StubMessage(from_user=StubUser(username="after")))

    session.expire_all()
    assert session.scalar(select(User).where(User.telegram_id == 42)).username == "after"


async def test_a_topic_toggles_on_and_off(session):
    await handlers.handle_start(StubMessage())

    await handlers.handle_topic_toggle(StubCallback(data="topic:model-release"))
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(UserTopic)) == 1

    await handlers.handle_topic_toggle(StubCallback(data="topic:model-release"))
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(UserTopic)) == 0


async def test_an_unknown_topic_is_refused(session):
    await handlers.handle_start(StubMessage())

    callback = StubCallback(data="topic:not-a-real-tag")
    await handlers.handle_topic_toggle(callback)

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(UserTopic)) == 0
    assert callback.answered == ["Noma'lum mavzu"]


async def test_topics_reach_the_right_person(session):
    await handlers.handle_start(StubMessage(from_user=StubUser(id=1, username="a")))
    await handlers.handle_start(StubMessage(from_user=StubUser(id=2, username="b")))

    await handlers.handle_topic_toggle(
        StubCallback(data="topic:model-release", from_user=StubUser(id=1))
    )

    session.expire_all()
    first = session.scalar(select(User).where(User.telegram_id == 1))
    second = session.scalar(select(User).where(User.telegram_id == 2))
    assert [t.tag for t in first.topics] == ["model-release"]
    assert second.topics == []


async def test_freq_sets_the_mode(session):
    await handlers.handle_start(StubMessage())

    await handlers.handle_freq_set(StubCallback(data="freq:weekly"))

    session.expire_all()
    assert session.scalar(select(User).where(User.telegram_id == 42)).digest_mode == "weekly"


async def test_an_unknown_mode_is_refused(session):
    await handlers.handle_start(StubMessage())

    callback = StubCallback(data="freq:hourly")
    await handlers.handle_freq_set(callback)

    session.expire_all()
    assert session.scalar(select(User).where(User.telegram_id == 42)).digest_mode == "daily"
    assert callback.answered == ["Noma'lum rejim"]


async def test_pause_stops_the_digest_but_keeps_the_account(session):
    await handlers.handle_start(StubMessage())

    await handlers.handle_pause(StubMessage())

    session.expire_all()
    stored = session.scalar(select(User).where(User.telegram_id == 42))
    assert stored.digest_mode == "off"
    assert stored.is_active is True


async def test_stop_deactivates(session):
    await handlers.handle_start(StubMessage())

    await handlers.handle_stop(StubMessage())

    session.expire_all()
    stored = session.scalar(select(User).where(User.telegram_id == 42))
    assert stored.is_active is False
    assert stored.digest_mode == "off"


async def test_preview_shows_what_is_waiting(session, make_item, make_enrichment):
    make_enrichment(make_item("A new model ships"), importance=8)
    session.commit()
    await handlers.handle_start(StubMessage())

    message = StubMessage()
    await handlers.handle_preview(message)

    assert "A new model ships" in message.replies[0]


async def test_preview_does_not_spend_the_next_digest(session, make_item, make_enrichment):
    # A preview that recorded deliveries would quietly empty the digest the
    # reader is actually waiting for.
    make_enrichment(make_item("A new model ships"), importance=8)
    session.commit()
    await handlers.handle_start(StubMessage())

    await handlers.handle_preview(StubMessage())

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0


async def test_preview_is_honest_when_there_is_nothing(session):
    await handlers.handle_start(StubMessage())

    message = StubMessage()
    await handlers.handle_preview(message)

    assert message.replies[0]


async def test_a_command_from_a_stranger_registers_them(session):
    # Every handler creates the user if missing, so someone who runs /topics
    # before /start is not answered with silence.
    await handlers.handle_topics(StubMessage())

    assert session.scalar(select(func.count()).select_from(User)) == 1
