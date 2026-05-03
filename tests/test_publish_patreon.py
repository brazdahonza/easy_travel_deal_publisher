import pytest


@pytest.fixture
def fake_publish(monkeypatch):
    """Replace PatreonPublisher.publish with a stub returning a known result."""

    captured = {}

    async def _publish(self, title, body_text, destination=None):
        captured["title"] = title
        captured["body"] = body_text
        captured["destination"] = destination
        return {
            "success": True,
            "url": "https://www.patreon.com/posts/123/edit",
            "draft_url": "https://www.patreon.com/posts/123/edit",
            "post_id": "123",
        }

    monkeypatch.setattr("app.main.PatreonPublisher.publish", _publish)
    return captured


def test_publish_patreon_success(client, auth_headers, fake_publish):
    body = {
        "title": "Akce: Bangkok 8500 Kč",
        "body": "Letenka z Prahy 15.6.–22.6.",
        "destination": "Bangkok",
    }
    r = client.post("/publish/patreon", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["status"] == "ok"
    assert payload["draft_url"] == "https://www.patreon.com/posts/123/edit"
    assert payload["post_id"] == "123"
    assert fake_publish["title"] == "Akce: Bangkok 8500 Kč"
    assert fake_publish["destination"] == "Bangkok"


def test_publish_patreon_session_unavailable(client, auth_headers, monkeypatch):
    from app.publishers import SessionUnavailableError
    from app.session import state as session_state

    notified = []
    monkeypatch.setattr("app.main.notify_telegram", lambda msg: notified.append(msg))

    async def _publish(self, title, body_text, destination=None):
        session_state.mark_expired("missing_credentials")
        raise SessionUnavailableError("missing credentials")

    monkeypatch.setattr("app.main.PatreonPublisher.publish", _publish)

    r = client.post(
        "/publish/patreon",
        json={"title": "x", "body": "y"},
        headers=auth_headers,
    )
    assert r.status_code == 401
    detail = r.json()["detail"]
    assert detail["error"] == "session_unavailable"
    assert notified, "Telegram notify should fire on session_unavailable"

    status = client.get("/session/patreon/status", headers=auth_headers).json()
    assert status["needs_refresh"] is True
    assert status["last_error"] == "missing_credentials"


def test_publish_patreon_browser_error_is_502(client, auth_headers, monkeypatch):
    async def _publish(self, title, body_text, destination=None):
        raise RuntimeError("composer mount failed")

    monkeypatch.setattr("app.main.PatreonPublisher.publish", _publish)

    r = client.post(
        "/publish/patreon",
        json={"title": "x", "body": "y"},
        headers=auth_headers,
    )
    assert r.status_code == 502
    assert "patreon_error" in r.json()["detail"]


def test_publish_patreon_validation_missing_title(client, auth_headers):
    r = client.post(
        "/publish/patreon",
        json={"body": "no title"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_publish_patreon_validation_empty_body(client, auth_headers):
    r = client.post(
        "/publish/patreon",
        json={"title": "ok", "body": ""},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_publish_patreon_requires_api_key(client):
    r = client.post(
        "/publish/patreon",
        json={"title": "x", "body": "y"},
    )
    assert r.status_code == 403


def test_publish_patreon_dry_run(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.PATREON_DRY_RUN", True)
    r = client.post(
        "/publish/patreon",
        json={"title": "t", "body": "b"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "dry_run"
    assert body["draft_url"] is None
