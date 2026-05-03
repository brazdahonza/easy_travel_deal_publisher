import asyncio

import pytest


@pytest.fixture(autouse=True)
def clean_state():
    from app.session import state
    state.clear_session()
    yield
    state.clear_session()


def _fake_login(cookies=None, email_out="auto@test"):
    cookies = cookies or [{"name": "auto", "value": "ok", "domain": ".patreon.com"}]

    async def _login(*args, **kwargs):
        return {"cookies": cookies, "email": email_out, "timestamp": "now"}

    return _login


def test_ensure_session_runs_auto_login(monkeypatch):
    from app.publishers.patreon import PatreonPublisher
    from app.session import state

    monkeypatch.setattr("app.config.settings.PATREON_EMAIL", "u@x")
    monkeypatch.setattr("app.config.settings.PATREON_PASSWORD", "p")
    monkeypatch.setattr("app.publishers.patreon.perform_patreon_login", _fake_login())

    pub = PatreonPublisher()
    assert pub.session is None

    asyncio.run(pub._ensure_session())

    assert pub.session is not None
    assert pub.session["cookies"][0]["name"] == "auto"
    s = state.get_status()
    assert s["cookies_present"] is True
    assert s["needs_refresh"] is False


def test_ensure_session_skips_login_when_cookies_present(monkeypatch):
    from app.publishers.patreon import PatreonPublisher
    from app.session import state

    state.set_session([{"name": "x", "value": "1", "domain": ".patreon.com"}], "you")

    called = {"hit": False}

    async def _no_call(*a, **kw):
        called["hit"] = True
        return {}

    monkeypatch.setattr("app.publishers.patreon.perform_patreon_login", _no_call)

    pub = PatreonPublisher()
    asyncio.run(pub._ensure_session())
    assert called["hit"] is False


def test_ensure_session_raises_when_no_credentials(monkeypatch):
    from app.publishers.patreon import PatreonPublisher, SessionUnavailableError
    from app.session import state

    monkeypatch.setattr("app.config.settings.PATREON_EMAIL", None)
    monkeypatch.setattr("app.config.settings.PATREON_PASSWORD", None)

    pub = PatreonPublisher()
    with pytest.raises(SessionUnavailableError):
        asyncio.run(pub._ensure_session())

    s = state.get_status()
    assert s["needs_refresh"] is True
    assert s["last_error"] == "missing_credentials"


def test_publish_relogins_and_retries_once(monkeypatch):
    from app.publishers.patreon import PatreonPublisher, _SessionExpiredMidFlow

    monkeypatch.setattr("app.config.settings.PATREON_EMAIL", "u@x")
    monkeypatch.setattr("app.config.settings.PATREON_PASSWORD", "p")
    monkeypatch.setattr("app.publishers.patreon.perform_patreon_login", _fake_login())

    pub = PatreonPublisher()
    attempts = {"n": 0}

    async def _publish_once(self, title, body, destination=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _SessionExpiredMidFlow("redirected to login")
        return {"success": True, "draft_url": "https://patreon.test/draft", "post_id": "9", "url": "u"}

    monkeypatch.setattr(PatreonPublisher, "_publish_once", _publish_once)

    result = asyncio.run(pub.publish("t", "b"))
    assert attempts["n"] == 2
    assert result["success"] is True
    assert result["draft_url"] == "https://patreon.test/draft"


def test_publish_gives_up_after_one_retry(monkeypatch):
    from app.publishers.patreon import (
        PatreonPublisher,
        SessionUnavailableError,
        _SessionExpiredMidFlow,
    )

    monkeypatch.setattr("app.config.settings.PATREON_EMAIL", "u@x")
    monkeypatch.setattr("app.config.settings.PATREON_PASSWORD", "p")
    monkeypatch.setattr("app.publishers.patreon.perform_patreon_login", _fake_login())

    pub = PatreonPublisher()
    attempts = {"n": 0}

    async def _publish_once(self, title, body, destination=None):
        attempts["n"] += 1
        raise _SessionExpiredMidFlow("redirected to login")

    monkeypatch.setattr(PatreonPublisher, "_publish_once", _publish_once)

    with pytest.raises(SessionUnavailableError):
        asyncio.run(pub.publish("t", "b"))
    assert attempts["n"] == 2  # initial + one retry, then give up
