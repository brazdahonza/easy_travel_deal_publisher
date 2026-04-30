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


def test_ingest_single_deal_skips_dedup_and_llm(monkeypatch):
    """Single-deal batch must publish regardless of prior history and without LLM selection."""
    client = TestClient(app)

    filter_duplicates_called = []
    select_with_llm_called = []

    def fake_filter(db, deals):
        filter_duplicates_called.append(deals)
        return []  # would normally filter everything out

    def fake_select(deals):
        select_with_llm_called.append(deals)
        return {"selected": [deals[0]["id"]], "justification": "ok"}

    monkeypatch.setattr("app.main.filter_duplicates", fake_filter)
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
    assert data["status"] == "ok"
    assert data["selected"] == 1
    assert data["published"]["patreon"] is True
    # dedup and LLM must NOT have been called
    assert filter_duplicates_called == []
    assert select_with_llm_called == []


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
    assert data["status"] == "ok"
    assert data["selected"] == 2
    assert data["published"]["patreon"] is True
    assert data["published"]["x"] is True
