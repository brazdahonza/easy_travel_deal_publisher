import pytest


sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from app.database import Base, drop_stale_deal_hash_unique
from app.models import PublishedDeal


def test_models_create_and_insert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    pd = PublishedDeal(destination="Testland", departure_city="Praha", price=1000, deal_hash="abc123")
    s.add(pd)
    s.commit()
    q = s.query(PublishedDeal).filter_by(destination="Testland").first()
    assert q is not None
    assert q.price == 1000


def _deal_hash_index(engine):
    for idx in inspect(engine).get_indexes("published_deals"):
        if idx.get("column_names") == ["deal_hash"]:
            return idx
    return None


def test_drop_stale_deal_hash_unique_removes_legacy_unique_index():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    # Simulate pre-c18cbbb deployment: replace non-unique index with a unique one.
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_published_deals_deal_hash"))
        conn.execute(text("CREATE UNIQUE INDEX ix_published_deals_deal_hash ON published_deals (deal_hash)"))
    assert bool(_deal_hash_index(engine)["unique"]) is True

    drop_stale_deal_hash_unique(engine)
    Base.metadata.create_all(bind=engine)

    idx = _deal_hash_index(engine)
    assert idx is not None
    assert bool(idx["unique"]) is False

    # Duplicate deal_hash now allowed.
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(PublishedDeal(destination="A", departure_city="Praha", price=1, deal_hash="dup"))
    s.add(PublishedDeal(destination="B", departure_city="Praha", price=2, deal_hash="dup"))
    s.commit()
    assert s.query(PublishedDeal).filter_by(deal_hash="dup").count() == 2


def test_drop_stale_deal_hash_unique_idempotent_on_clean_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    drop_stale_deal_hash_unique(engine)
    drop_stale_deal_hash_unique(engine)
    idx = _deal_hash_index(engine)
    assert idx is not None and bool(idx["unique"]) is False


def test_drop_stale_deal_hash_unique_handles_missing_table():
    engine = create_engine("sqlite:///:memory:")
    drop_stale_deal_hash_unique(engine)  # no tables yet — must not raise
    drop_stale_deal_hash_unique(None)    # no engine — must not raise
