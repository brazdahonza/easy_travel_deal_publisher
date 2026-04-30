import pytest
pytest.importorskip("sqlalchemy")


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
