"""Delivery.

The ledger is the point. Every guard above it is a convenience; PRIMARY
KEY(user_id, cluster_id) is what holds when the process dies mid-run or two
instances race, and these tests are what say so.
"""

from datetime import UTC, datetime, timedelta

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import func, select

from ogoh.db.models import Delivery, User
from ogoh.worker import deliver_due_digests

# 09:00 Asia/Tashkent, the default digest hour.
NINE_TASHKENT = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)


class FakeBot:
    def __init__(self, *, error=None):
        self.sent: list[tuple[int, str]] = []
        self._error = error

    async def send_message(self, chat_id, text, **kwargs):
        if self._error:
            raise self._error
        self.sent.append((chat_id, text))


@pytest.fixture
def due_now(monkeypatch):
    """Freeze the worker's clock on a moment when a daily digest is due."""
    from ogoh import worker

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NINE_TASHKENT

    monkeypatch.setattr(worker, "datetime", FrozenDatetime)
    return NINE_TASHKENT


async def test_a_due_user_gets_their_digest(session, make_user, make_item, make_enrichment, due_now):
    make_enrichment(make_item("A new model ships"), importance=8)
    user = make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    bot = FakeBot()
    sent = await deliver_due_digests(bot)

    assert sent == 1
    assert bot.sent[0][0] == user.telegram_id
    assert "A new model ships" in bot.sent[0][1]


async def test_a_story_is_never_sent_twice(session, make_user, make_item, make_enrichment, due_now):
    make_enrichment(make_item("A new model ships"), importance=8)
    make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    bot = FakeBot()
    await deliver_due_digests(bot)

    # Clear the clock gate so only the ledger can stop the second send.
    with session.begin():
        session.query(User).update({User.last_digest_at: None})

    await deliver_due_digests(bot)

    assert len(bot.sent) == 1


async def test_the_ledger_records_what_was_sent(
    session, make_user, make_item, make_enrichment, due_now
):
    item = make_item("A new model ships")
    make_enrichment(item, importance=8)
    user = make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    await deliver_due_digests(FakeBot())

    session.expire_all()
    recorded = session.scalar(
        select(Delivery.cluster_id).where(Delivery.user_id == user.id)
    )
    assert recorded == (item.cluster_id or item.id)


async def test_a_failed_send_records_nothing(
    session, make_user, make_item, make_enrichment, due_now
):
    # Recorded after the send lands, not before. The other order drops a digest
    # on the floor every time Telegram hiccups.
    make_enrichment(make_item("A new model ships"), importance=8)
    make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    await deliver_due_digests(FakeBot(error=RuntimeError("network")))

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0


async def test_a_digest_lost_to_an_error_is_sent_next_run(
    session, make_user, make_item, make_enrichment, due_now
):
    make_enrichment(make_item("A new model ships"), importance=8)
    make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    await deliver_due_digests(FakeBot(error=RuntimeError("network")))
    bot = FakeBot()
    await deliver_due_digests(bot)

    assert len(bot.sent) == 1


async def test_blocking_the_bot_deactivates_the_user(
    session, make_user, make_item, make_enrichment, due_now
):
    # Telegram will reject every future send too, so stop trying rather than
    # logging this every twenty minutes forever.
    make_enrichment(make_item("A new model ships"), importance=8)
    user = make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    error = TelegramForbiddenError(method=None, message="bot was blocked by the user")
    await deliver_due_digests(FakeBot(error=error))

    session.expire_all()
    assert session.get(User, user.id).is_active is False


async def test_rate_limiting_leaves_the_user_for_next_time(
    session, make_user, make_item, make_enrichment, due_now
):
    make_enrichment(make_item("A new model ships"), importance=8)
    user = make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    error = TelegramRetryAfter(method=None, message="Too Many Requests", retry_after=30)
    await deliver_due_digests(FakeBot(error=error))

    session.expire_all()
    stored = session.get(User, user.id)
    assert stored.is_active is True
    assert stored.last_digest_at is None
    assert session.scalar(select(func.count()).select_from(Delivery)) == 0


async def test_users_who_are_not_due_are_left_alone(
    session, make_user, make_item, make_enrichment, due_now
):
    make_enrichment(make_item("A new model ships"), importance=8)
    make_user(digest_mode="daily", digest_hour=17)  # not this hour
    make_user(digest_mode="off")
    session.commit()

    bot = FakeBot()
    assert await deliver_due_digests(bot) == 0
    assert bot.sent == []


async def test_a_user_with_nothing_to_read_gets_no_message(
    session, make_user, make_item, make_enrichment, due_now
):
    # Below their floor: no digest at all beats an empty one.
    make_enrichment(make_item("Routine"), importance=2)
    make_user(digest_mode="daily", digest_hour=9, min_importance=5)
    session.commit()

    bot = FakeBot()
    assert await deliver_due_digests(bot) == 0
    assert bot.sent == []


async def test_an_empty_digest_does_not_burn_the_clock(
    session, make_user, make_item, make_enrichment, due_now
):
    # last_digest_at only moves when something was actually sent, so a quiet
    # morning does not cost the reader their digest when news lands at ten.
    make_enrichment(make_item("Routine"), importance=2)
    user = make_user(digest_mode="daily", digest_hour=9, min_importance=5)
    session.commit()

    await deliver_due_digests(FakeBot())

    session.expire_all()
    assert session.get(User, user.id).last_digest_at is None


async def test_each_subscriber_gets_their_own_topics(
    session, make_user, make_item, make_enrichment, due_now
):
    make_enrichment(make_item("A new model ships"), importance=8, tags=["model-release"])
    make_enrichment(make_item("Someone raised a round"), importance=8, tags=["funding-business"])
    models = make_user(digest_mode="daily", digest_hour=9, topics=["model-release"])
    money = make_user(digest_mode="daily", digest_hour=9, topics=["funding-business"])
    session.commit()

    bot = FakeBot()
    await deliver_due_digests(bot)

    delivered = dict(bot.sent)
    assert "A new model ships" in delivered[models.telegram_id]
    assert "Someone raised a round" not in delivered[models.telegram_id]
    assert "Someone raised a round" in delivered[money.telegram_id]


async def test_inactive_users_are_skipped(
    session, make_user, make_item, make_enrichment, due_now
):
    make_enrichment(make_item("A new model ships"), importance=8)
    user = make_user(digest_mode="daily", digest_hour=9)
    user.is_active = False
    session.commit()

    bot = FakeBot()
    assert await deliver_due_digests(bot) == 0


async def test_one_blocked_user_does_not_stop_the_rest(
    session, make_user, make_item, make_enrichment, due_now, monkeypatch
):
    make_enrichment(make_item("A new model ships"), importance=8)
    blocked = make_user(digest_mode="daily", digest_hour=9)
    fine = make_user(digest_mode="daily", digest_hour=9)
    session.commit()

    class PartlyBrokenBot(FakeBot):
        async def send_message(self, chat_id, text, **kwargs):
            if chat_id == blocked.telegram_id:
                raise TelegramForbiddenError(method=None, message="blocked")
            self.sent.append((chat_id, text))

    bot = PartlyBrokenBot()
    sent = await deliver_due_digests(bot)

    assert sent == 1
    assert [chat_id for chat_id, _ in bot.sent] == [fine.telegram_id]
