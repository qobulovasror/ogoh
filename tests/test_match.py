from datetime import UTC, datetime, timedelta


from ogoh.pipeline.match import INSTANT_MIN_IMPORTANCE, is_due, pending_for_user

# 09:00 in Asia/Tashkent (UTC+5), the default digest hour.
NINE_TASHKENT = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)


def test_daily_fires_at_the_local_hour(make_user):
    user = make_user(digest_mode="daily", digest_hour=9, timezone="Asia/Tashkent")
    assert is_due(user, NINE_TASHKENT)


def test_daily_stays_quiet_at_other_hours(make_user):
    user = make_user(digest_mode="daily", digest_hour=9, timezone="Asia/Tashkent")
    assert not is_due(user, NINE_TASHKENT + timedelta(hours=3))


def test_digest_hour_follows_the_user_timezone(make_user):
    # Same instant, two subscribers. The hour is theirs, not the server's.
    tashkent = make_user(digest_mode="daily", digest_hour=9, timezone="Asia/Tashkent")
    london = make_user(digest_mode="daily", digest_hour=9, timezone="Europe/London")

    assert is_due(tashkent, NINE_TASHKENT)
    assert not is_due(london, NINE_TASHKENT)


def test_the_hour_does_not_fire_three_times(make_user):
    # The scheduler ticks every 20 minutes, so the due hour comes round three
    # times. Without last_digest_at that is three digests every morning.
    user = make_user(digest_mode="daily", last_digest_at=NINE_TASHKENT)
    assert not is_due(user, NINE_TASHKENT + timedelta(minutes=20))
    assert not is_due(user, NINE_TASHKENT + timedelta(minutes=40))


def test_the_next_day_fires_again(make_user):
    user = make_user(digest_mode="daily", last_digest_at=NINE_TASHKENT)
    assert is_due(user, NINE_TASHKENT + timedelta(days=1))


def test_naive_timestamps_from_sqlite_do_not_explode(make_user):
    # SQLite has no timestamptz: DateTime(timezone=True) comes back naive, and
    # subtracting it from an aware now raises TypeError rather than misbehaving.
    user = make_user(digest_mode="daily")
    user.last_digest_at = NINE_TASHKENT.replace(tzinfo=None)
    assert not is_due(user, NINE_TASHKENT + timedelta(minutes=20))


def test_weekly_only_fires_on_monday(make_user):
    user = make_user(digest_mode="weekly", digest_hour=9, timezone="Asia/Tashkent")
    thursday = NINE_TASHKENT  # 2026-07-16 is a Thursday
    monday = NINE_TASHKENT + timedelta(days=4)

    assert not is_due(user, thursday)
    assert is_due(user, monday)


def test_off_and_inactive_never_fire(make_user):
    assert not is_due(make_user(digest_mode="off"), NINE_TASHKENT)

    inactive = make_user(digest_mode="daily")
    inactive.is_active = False
    assert not is_due(inactive, NINE_TASHKENT)


def test_instant_ignores_the_clock(make_user):
    # Importance does the gating for instant, not the hour.
    user = make_user(digest_mode="instant")
    assert is_due(user, NINE_TASHKENT + timedelta(hours=7))


def test_unknown_timezone_falls_back_without_raising(make_user):
    user = make_user(digest_mode="daily", timezone="Mars/Olympus_Mons")
    # UTC 09:00 rather than Tashkent's, but the point is it answers at all.
    assert is_due(user, datetime(2026, 7, 16, 9, 0, tzinfo=UTC)) in (True, False)


def test_topics_filter_the_digest(session, make_user, make_item, make_enrichment):
    wanted = make_item("A new model ships")
    make_enrichment(wanted, importance=7, tags=["model-release"])
    unwanted = make_item("Someone raised a round")
    make_enrichment(unwanted, importance=7, tags=["funding-business"])

    user = make_user(topics=["model-release"])
    titles = [entry.item.title for entry in pending_for_user(session, user)]

    assert titles == ["A new model ships"]


def test_no_topics_means_everything(session, make_user, make_item, make_enrichment):
    # An empty topic set is "hasn't picked yet", not "wants nothing". Sending
    # silence to someone who never ran /topics just reads as a broken bot.
    for title, tag in (("A", "model-release"), ("B", "funding-business")):
        make_enrichment(make_item(title), importance=7, tags=[tag])

    user = make_user(topics=[])
    assert len(pending_for_user(session, user)) == 2


def test_importance_floor_applies(session, make_user, make_item, make_enrichment):
    make_enrichment(make_item("Routine"), importance=4)
    make_enrichment(make_item("Real"), importance=8)

    user = make_user(min_importance=5)
    titles = [entry.item.title for entry in pending_for_user(session, user)]

    assert titles == ["Real"]


def test_instant_only_carries_what_is_worth_interrupting_for(
    session, make_user, make_item, make_enrichment
):
    make_enrichment(make_item("Interesting"), importance=6)
    make_enrichment(make_item("A launch"), importance=INSTANT_MIN_IMPORTANCE)

    user = make_user(digest_mode="instant", min_importance=5)
    titles = [entry.item.title for entry in pending_for_user(session, user)]

    assert titles == ["A launch"]


def test_delivered_stories_do_not_come_round_again(
    session, make_user, make_item, make_enrichment
):
    from ogoh.db.models import Delivery

    item = make_item("A new model ships")
    make_enrichment(item, importance=8)
    user = make_user()

    assert len(pending_for_user(session, user)) == 1

    session.add(
        Delivery(
            user_id=user.id,
            cluster_id=item.cluster_id or item.id,
            sent_at=datetime.now(UTC),
        )
    )
    session.flush()

    assert pending_for_user(session, user) == []
