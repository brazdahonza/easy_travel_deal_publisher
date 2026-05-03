import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app.database import Base, ENGINE
from app.main import app


@pytest.fixture(autouse=True)
def create_tables():
    import app.models  # noqa: F401 — registers models with Base.metadata
    Base.metadata.create_all(bind=ENGINE)
    yield


def _read_ingest_log(ingest_id):
    from app.database import SessionLocal
    from app.models import IngestLog
    db = SessionLocal()
    try:
        return db.query(IngestLog).filter(IngestLog.id == ingest_id).first()
    finally:
        db.close()


def _read_published_deals():
    from app.database import SessionLocal
    from app.models import PublishedDeal
    db = SessionLocal()
    try:
        return db.query(PublishedDeal).all()
    finally:
        db.close()


def test_ingest_batch_publishes_each_post(monkeypatch):
    """Batch of posts goes straight to Patreon publisher; no LLM, no dedup."""
    client = TestClient(app)

    seen_calls = []

    async def fake_publish(self, title, body_text, destination=None):
        seen_calls.append((title, body_text, destination))
        return {"success": True, "url": "https://patreon.fake/post/x", "draft_url": "https://patreon.fake/post/x/edit", "post_id": "x"}

    monkeypatch.setattr("app.publishers.patreon.PatreonPublisher.publish", fake_publish)

    payload = {
        "posts": [
            {"title": "Bali deal", "body": "body A", "destination_name": "Bali"},
            {"title": "Lisbon deal", "body": "body B", "destination_name": "Lisbon"},
        ]
    }

    r = client.post("/ingest", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "accepted"
    assert data["posts_count"] == 2
    assert isinstance(data["ingest_id"], int)

    log_row = _read_ingest_log(data["ingest_id"])
    assert log_row.status == "done"
    assert log_row.published_count == 2

    destinations = {p.destination for p in _read_published_deals()}
    assert {"Bali", "Lisbon"}.issubset(destinations)
    assert len(seen_calls) == 2
