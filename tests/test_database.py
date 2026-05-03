import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import IngestLog, PatreonSession, PublishedDeal


def test_models_create_and_insert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    pd = PublishedDeal(
        destination="Testland",
        title="t",
        body="b",
        draft_url="https://patreon.fake/posts/1/edit",
        post_id="1",
    )
    s.add(pd)
    s.commit()

    q = s.query(PublishedDeal).filter_by(destination="Testland").first()
    assert q is not None
    assert q.post_id == "1"


def test_ingest_log_and_session_table_present():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    s.add(IngestLog(posts_count=2, status="queued"))
    s.add(PatreonSession(cookies_b64="abc", email="x@y"))
    s.commit()

    assert s.query(IngestLog).count() == 1
    assert s.query(PatreonSession).count() == 1
