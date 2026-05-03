import base64
import json

import pytest


@pytest.fixture(autouse=True)
def clean_state():
    from app.session import state
    state.clear_session()
    yield
    state.clear_session()


def test_set_and_get_session_roundtrip():
    from app.session import state

    cookies = [{"name": "a", "value": "b", "domain": ".patreon.com"}]
    stored = state.set_session(cookies, email="me@example.com")
    assert stored["cookies"] == cookies
    assert stored["email"] == "me@example.com"
    assert stored["stored_at"]

    fetched = state.get_session()
    assert fetched is stored


def test_get_session_when_empty():
    from app.session import state

    assert state.get_session() is None


def test_status_when_empty():
    from app.session import state

    s = state.get_status()
    assert s["cookies_present"] is False
    assert s["cookies_count"] == 0
    assert s["needs_refresh"] is False
    assert s["last_error"] is None


def test_status_after_set():
    from app.session import state

    state.set_session([{"name": "x", "value": "1", "domain": ".patreon.com"}], "me@example.com")
    s = state.get_status()
    assert s["cookies_present"] is True
    assert s["cookies_count"] == 1
    assert s["email"] == "me@example.com"
    assert s["needs_refresh"] is False


def test_mark_expired_does_not_clear_cookies():
    from app.session import state

    state.set_session([{"name": "x", "value": "1", "domain": ".patreon.com"}], None)
    state.mark_expired("test_reason")
    s = state.get_status()
    assert s["needs_refresh"] is True
    assert s["last_error"] == "test_reason"
    assert s["cookies_present"] is True  # cookies still present, just flagged


def test_set_session_clears_needs_refresh():
    from app.session import state

    state.mark_expired("oops")
    state.set_session([{"name": "y", "value": "1", "domain": ".patreon.com"}], None)
    s = state.get_status()
    assert s["needs_refresh"] is False
    assert s["last_error"] is None


def test_seed_from_env_decodes_base64(monkeypatch):
    from app.session import state

    blob = {
        "cookies": [{"name": "k", "value": "v", "domain": ".patreon.com"}],
        "email": "you@example.com",
    }
    encoded = base64.b64encode(json.dumps(blob).encode()).decode()
    monkeypatch.setattr("app.config.settings.PATREON_SESSION", encoded)

    state.seed_from_env()
    s = state.get_status()
    assert s["cookies_present"] is True
    assert s["cookies_count"] == 1
    assert s["email"] == "you@example.com"


def test_seed_from_env_with_no_blob(monkeypatch):
    from app.session import state

    monkeypatch.setattr("app.config.settings.PATREON_SESSION", None)
    state.seed_from_env()
    assert state.get_session() is None


def test_seed_from_env_handles_garbage(monkeypatch):
    from app.session import state

    monkeypatch.setattr("app.config.settings.PATREON_SESSION", "not-valid-base64!@#")
    # Should log and silently keep an empty session, not raise.
    state.seed_from_env()
    assert state.get_session() is None
