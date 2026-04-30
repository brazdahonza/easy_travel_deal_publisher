import logging
from .config import settings

log = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, declarative_base

    log.debug("💾 Connecting to database...")
    _is_memory = settings.DATABASE_URL == "sqlite:///:memory:"
    _engine_kwargs = {"echo": False, "future": True}
    if _is_memory:
        from sqlalchemy.pool import StaticPool
        _engine_kwargs["connect_args"] = {"check_same_thread": False}
        _engine_kwargs["poolclass"] = StaticPool
    ENGINE = create_engine(settings.DATABASE_URL, **_engine_kwargs)
    SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
    Base = declarative_base()
    log.info("💾 Database engine ready — %s", settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL)

    def get_db():
        db = SessionLocal()
        log.debug("💾 DB session opened")
        try:
            yield db
        finally:
            db.close()
            log.debug("💾 DB session closed")

except Exception:
    log.exception("❌ Failed to initialize database engine")
    ENGINE = None
    SessionLocal = None

    class _DummyBase:
        pass

    Base = _DummyBase

    def get_db():
        raise RuntimeError("SQLAlchemy not installed; DB functionality unavailable in this environment")
