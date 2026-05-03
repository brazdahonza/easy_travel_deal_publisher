def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "cookies_present" in body
    assert "needs_refresh" in body


def test_health_no_auth_required(client):
    r = client.get("/health")
    assert r.status_code == 200
