def test_set_session_endpoint_writes_state(client, auth_headers):
    from app.session import state

    body = {
        "cookies": [
            {"name": "session_id", "value": "abc", "domain": ".patreon.com"},
            {"name": "csrf", "value": "xyz", "domain": ".patreon.com"},
        ],
        "email": "ops@flynow.cz",
    }
    r = client.post("/session/patreon", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["status"] == "ok"
    assert payload["cookies_count"] == 2
    assert payload["email"] == "ops@flynow.cz"

    stored = state.get_session()
    assert stored is not None
    assert len(stored["cookies"]) == 2
    assert stored["email"] == "ops@flynow.cz"


def test_set_session_endpoint_requires_api_key(client, auth_headers):
    body = {"cookies": [{"name": "a", "value": "b", "domain": ".patreon.com"}]}
    r = client.post("/session/patreon", json=body)
    assert r.status_code == 403


def test_status_endpoint_empty(client, auth_headers):
    r = client.get("/session/patreon/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["cookies_present"] is False
    assert body["cookies_count"] == 0
    assert body["needs_refresh"] is False


def test_status_endpoint_after_post(client, auth_headers):
    client.post(
        "/session/patreon",
        json={
            "cookies": [{"name": "session_id", "value": "abc", "domain": ".patreon.com"}],
            "email": "you@example.com",
        },
        headers=auth_headers,
    )
    r = client.get("/session/patreon/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["cookies_present"] is True
    assert body["cookies_count"] == 1
    assert body["email"] == "you@example.com"
    assert body["needs_refresh"] is False


def test_status_endpoint_requires_api_key(client):
    r = client.get("/session/patreon/status")
    assert r.status_code == 403
