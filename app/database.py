import logging
from .config import settings

log = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine, inspect, text
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

    def drop_stale_deal_hash_unique(engine) -> None:
        # Drops legacy UNIQUE index/constraint on published_deals.deal_hash.
        # Why: dedup moved upstream (commit c18cbbb); model no longer marks the
        # column unique, but create_all never drops existing DB objects, so old
        # deployments keep enforcing uniqueness and fail re-publish attempts.
        if engine is None:
            return
        insp = inspect(engine)
        if "published_deals" not in insp.get_table_names():
            return
        for uc in insp.get_unique_constraints("published_deals"):
            if uc.get("column_names") == ["deal_hash"] and uc.get("name"):
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE published_deals DROP CONSTRAINT "{uc["name"]}"'))
                log.info("💾 Dropped stale unique constraint %s on deal_hash", uc["name"])
        for idx in insp.get_indexes("published_deals"):
            if idx.get("column_names") == ["deal_hash"] and idx.get("unique") and idx.get("name"):
                name = idx["name"]
                with engine.begin() as conn:
                    conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
                    conn.execute(text(f'CREATE INDEX "{name}" ON published_deals (deal_hash)'))
                log.info("💾 Replaced stale unique index %s with non-unique on deal_hash", name)

except Exception:
    log.exception("❌ Failed to initialize database engine")
    ENGINE = None
    SessionLocal = None

    class _DummyBase:
        pass

    Base = _DummyBase

    def get_db():
        raise RuntimeError("SQLAlchemy not installed; DB functionality unavailable in this environment")
