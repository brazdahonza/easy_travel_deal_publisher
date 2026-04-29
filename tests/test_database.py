import pytest


sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
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
