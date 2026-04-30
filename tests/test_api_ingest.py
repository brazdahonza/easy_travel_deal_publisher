import json
import pytest

# skip if SQLAlchemy not installed in this environment
pytest.importorskip("sqlalchemy")

from app.database import ENGINE, Base
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def create_tables():
    import app.models  # noqa: F401 — registers models with Base.metadata
    Base.metadata.create_all(bind=ENGINE)
    yield
    # no teardown for in-memory sqlite


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


def test_ingest_single_deal_skips_llm(monkeypatch):
    """Single-deal batch must publish without LLM selection."""
    client = TestClient(app)

    select_with_llm_called = []

    def fake_select(deals):
        select_with_llm_called.append(deals)
        return {"selected": [deals[0]["id"]], "justification": "ok"}

    monkeypatch.setattr("app.main.select_with_llm", fake_select)

    async def fake_patreon_publish(self, title, body_text, destination=None):
        return {"success": True, "url": "https://patreon.fake/post/1"}

    def fake_twitter_publish(self, text):
        return {"success": True, "result": {"id": "123"}}

    monkeypatch.setattr("app.publishers.patreon.PatreonPublisher.publish", fake_patreon_publish)
    monkeypatch.setattr("app.publishers.twitter.TwitterPublisher.publish", fake_twitter_publish)
    monkeypatch.setattr("app.main.settings", type("S", (), {
        "TWITTER_API_KEY": "fake", "TWITTER_ACCESS_TOKEN": "fake",
        "INGEST_API_KEY": None, "ANTHROPIC_API_KEY": None,
    })())

    payload = {"deals": [
        {"id": "solo1", "destination": "Tokyo", "departure_city": "Praha", "price": 9900, "duration_days": 10},
    ]}

    r = client.post("/ingest", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "accepted"
    assert data["deals_count"] == 1
    assert isinstance(data["ingest_id"], int)

    # background task runs after response — TestClient awaits it before returning
    log_row = _read_ingest_log(data["ingest_id"])
    assert log_row.status == "done"
    assert log_row.selected_count == 1
    assert select_with_llm_called == []

    pd_rows = _read_published_deals()
    assert any(p.destination == "Tokyo" for p in pd_rows)


def test_ingest_pipeline(monkeypatch):
    client = TestClient(app)

    # mock LLM selection to select both deals
    def fake_select(deals):
        return {"selected": [deals[0]["id"], deals[1]["id"]], "justification": "ok"}

    monkeypatch.setattr("app.main.select_with_llm", fake_select)

    # mock PatreonPublisher.publish async
    async def fake_patreon_publish(self, title, body_text, destination=None):
        return {"success": True, "url": "https://patreon.fake/post/1"}

    monkeypatch.setattr("app.publishers.patreon.PatreonPublisher.publish", fake_patreon_publish)

    # mock Twitter publish
    def fake_twitter_publish(self, text):
        return {"success": True, "result": {"id": "123"}}

    monkeypatch.setattr("app.publishers.twitter.TwitterPublisher.publish", fake_twitter_publish)
    monkeypatch.setattr("app.main.settings", type("S", (), {
        "TWITTER_API_KEY": "fake", "TWITTER_ACCESS_TOKEN": "fake",
        "INGEST_API_KEY": None, "ANTHROPIC_API_KEY": None,
    })())

    payload = {
        "deals": [
            {"id": "a1", "destination": "Bali", "departure_city": "Praha", "price": 5000, "duration_days": 7},
            {"id": "b2", "destination": "Lisbon", "departure_city": "Praha", "price": 4200, "duration_days": 5},
        ]
    }

    r = client.post("/ingest", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "accepted"
    assert data["deals_count"] == 2
    assert isinstance(data["ingest_id"], int)

    log_row = _read_ingest_log(data["ingest_id"])
    assert log_row.status == "done"
    assert log_row.selected_count == 2

    destinations = {p.destination for p in _read_published_deals()}
    assert {"Bali", "Lisbon"}.issubset(destinations)
