import pytest
from app.publishers.patreon import PatreonPublisher, SessionExpiredError
from app.publishers.twitter import TwitterPublisher


def test_patreon_missing_session():
    p = PatreonPublisher()
    with pytest.raises(SessionExpiredError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(p.publish("t", "<p>x</p>"))


def test_twitter_not_configured():
    t = TwitterPublisher()
    res = t.publish("hello")
    assert res["success"] is False or res.get("reason") == "not_configured"
