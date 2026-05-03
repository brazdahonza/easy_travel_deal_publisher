import pytest
pytest.importorskip("sqlalchemy")


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "patreon_session" in body
    assert "patreon_login_creds" in body
