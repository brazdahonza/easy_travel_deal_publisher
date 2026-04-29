from app.deal_selector import duration_bucket, deal_hash, filter_duplicates
import pytest


def test_duration_bucket():
    assert duration_bucket(3) == "weekend"
    assert duration_bucket(7) == "week"
    assert duration_bucket(12) == "twoweeks"
    assert duration_bucket(1) == "short"


def test_deal_hash_consistent():
    h1 = deal_hash("Bangkok", "Praha", "week")
    h2 = deal_hash("Bangkok", "Praha", "week")
    assert h1 == h2


def test_filter_duplicates_no_sqlalchemy(monkeypatch):
    # If SQLAlchemy not present, importorskip in DB tests will skip heavy tests.
    # Here we check filter_duplicates runs when passed a fake db with query returning None
    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeDB:
        def query(self, *args, **kwargs):
            return FakeQuery()

    db = FakeDB()
    deals = [{"destination": "A", "departure_city": "B", "duration_days": 3}]
    res = filter_duplicates(db, deals)
    assert len(res) == 1
    assert "_deal_hash" in res[0]
