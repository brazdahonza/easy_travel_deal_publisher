import logging
from .config import settings

log = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, declarative_base

    ENGINE = create_engine(settings.DATABASE_URL, echo=False, future=True)
    SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
    Base = declarative_base()


    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

except Exception:
    # SQLAlchemy not available in environment (tests may skip DB heavy tests)
    ENGINE = None
    SessionLocal = None

    class _DummyBase:
        pass

    Base = _DummyBase

    def get_db():
        raise RuntimeError("SQLAlchemy not installed; DB functionality unavailable in this environment")
