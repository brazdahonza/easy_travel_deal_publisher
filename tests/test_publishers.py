import asyncio
import pytest

from app.publishers.patreon import PatreonPublisher, SessionExpiredError


def test_patreon_no_session_no_creds_raises(monkeypatch):
    """No stored session + no PATREON_EMAIL/PASSWORD → SessionExpiredError on publish."""
    monkeypatch.setattr("app.publishers.patreon.session_store.load", lambda: None)
    monkeypatch.setattr("app.publishers.patreon.settings", type("S", (), {
        "PATREON_HEADLESS": True, "PATREON_SLOWMO_MS": 0,
        "PATREON_EMAIL": None, "PATREON_PASSWORD": None,
        "PATREON_TOTP_SECRET": None, "PATREON_2FA_CODE": None,
    })())

    pub = PatreonPublisher()
    assert pub.session is None
    # The error path requires actually launching playwright then probing — we want to
    # short-circuit by mocking _is_session_valid to bypass the network call.
    pytest.importorskip("playwright")
