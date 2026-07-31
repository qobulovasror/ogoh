"""The admin panel, driven through a TestClient against the scratch database.

The session fixture patches the package's engine, so the app — which opens its own
session_scope, as a separate process would — reads and writes the same file the
test does. Cookies persist across a client's requests, so a successful login
carries into the pages behind it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ogoh.admin.app import create_app
from ogoh.config import Settings
from ogoh.db.models import AdminLoginCode, AgentUsage, Source, User, UserKeyword, UserTopic

ADMIN_ID = 42


@pytest.fixture
def client(session):
    settings = Settings(admin_telegram_id=ADMIN_ID, admin_session_secret="test-secret")
    return TestClient(create_app(settings))


def _issue_code(session, code="123456", *, telegram_id=ADMIN_ID, ttl_minutes=5):
    session.add(
        AdminLoginCode(
            code=code,
            telegram_id=telegram_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
    )
    session.commit()


def _login(client, session, code="123456"):
    _issue_code(session, code)
    return client.post("/login", data={"code": code}, follow_redirects=False)


def test_unauthenticated_requests_are_sent_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_a_valid_code_logs_in_and_the_dashboard_opens(client, session):
    resp = _login(client, session)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Dashboard" in dashboard.text


def test_a_wrong_code_does_not_log_in(client, session):
    resp = client.post("/login", data={"code": "000000"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?error")
    # And the dashboard is still closed.
    assert client.get("/", follow_redirects=False).status_code == 303


def test_a_code_is_single_use(client, session):
    _login(client, session, "123456")
    # A second client using the same spent code is refused.
    other = TestClient(create_app(Settings(admin_telegram_id=ADMIN_ID, admin_session_secret="x")))
    resp = other.post("/login", data={"code": "123456"}, follow_redirects=False)
    assert resp.headers["location"].startswith("/login?error")


def test_an_expired_code_is_refused(client, session):
    _issue_code(session, "555000", ttl_minutes=-1)
    resp = client.post("/login", data={"code": "555000"}, follow_redirects=False)
    assert resp.headers["location"].startswith("/login?error")


def test_a_source_can_be_added(client, session):
    _login(client, session)

    client.post(
        "/sources/add",
        data={"name": "New Feed", "url": "https://new.test/rss", "kind": "rss", "trust_tier": "1"},
    )

    stored = session.scalar(select(Source).where(Source.name == "New Feed"))
    assert stored is not None
    assert stored.trust_tier == 1


def test_deleting_a_source_with_items_disables_it_instead(
    client, session, make_source, make_item
):
    _login(client, session)
    source = make_source("Has Items")
    make_item("A story", source=source)
    session.commit()

    client.post(f"/sources/{source.id}/delete")

    session.expire_all()
    still_there = session.get(Source, source.id)
    assert still_there is not None
    assert still_there.enabled is False


def test_admin_can_rewrite_a_users_rules(client, session, make_user):
    _login(client, session)
    user = make_user(topics=["model-release"])
    session.commit()

    client.post(
        f"/users/{user.id}/update",
        data={
            "digest_mode": "weekly",
            "lang": "en",
            "digest_hour": "7",
            "timezone": "Europe/London",
            "min_importance": "8",
            "is_active": "on",
            "topics": ["research", "opensource"],
            "keywords": "MCP, Anthropic",
        },
    )

    session.expire_all()
    stored = session.get(User, user.id)
    assert stored.digest_mode == "weekly"
    assert stored.min_importance == 8
    assert stored.digest_hour == 7
    assert {t.tag for t in session.scalars(select(UserTopic).where(UserTopic.user_id == user.id))} == {
        "research",
        "opensource",
    }
    assert {k.keyword for k in session.scalars(select(UserKeyword).where(UserKeyword.user_id == user.id))} == {
        "mcp",
        "anthropic",
    }


def test_admin_can_enable_the_agent_for_a_user(client, session, make_user):
    _login(client, session)
    user = make_user()
    session.commit()
    assert user.agent_enabled is False

    client.post(
        f"/users/{user.id}/update",
        data={
            "digest_mode": user.digest_mode,
            "lang": user.lang,
            "digest_hour": str(user.digest_hour),
            "timezone": user.timezone,
            "min_importance": str(user.min_importance),
            "is_active": "on",
            "agent_enabled": "on",
        },
    )

    session.expire_all()
    assert session.get(User, user.id).agent_enabled is True


def test_the_agent_page_shows_usage(client, session, make_user):
    from datetime import UTC, datetime

    _login(client, session)
    user = make_user()
    user.agent_enabled = True
    session.add(AgentUsage(user_id=user.id, day=datetime.now(UTC).date(), count=4))
    session.commit()

    resp = client.get("/agent")

    assert resp.status_code == 200
    assert "bugungi savol" in resp.text
    assert (user.username or "") in resp.text


def test_the_items_browser_lists_a_stored_item(client, session, make_item, make_enrichment):
    _login(client, session)
    make_enrichment(make_item("A findable headline"), importance=7)
    session.commit()

    resp = client.get("/items")
    assert "A findable headline" in resp.text
