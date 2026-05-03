try:
    from sqlalchemy import Column, Integer, String, DateTime, Text, func
    from .database import Base


    class PublishedDeal(Base):
        __tablename__ = "published_deals"

        id = Column(Integer, primary_key=True, index=True)
        destination = Column(String, nullable=False)
        title = Column(Text, nullable=False)
        body = Column(Text, nullable=False)
        draft_url = Column(String)
        post_id = Column(String, index=True)
        published_at = Column(DateTime, server_default=func.now())


    class IngestLog(Base):
        __tablename__ = "ingest_log"

        id = Column(Integer, primary_key=True, index=True)
        received_at = Column(DateTime, server_default=func.now())
        posts_count = Column(Integer, nullable=False)
        published_count = Column(Integer)
        status = Column(String, nullable=False)
        error_message = Column(Text)


    class PatreonSession(Base):
        __tablename__ = "patreon_sessions"

        id = Column(Integer, primary_key=True, index=True)
        cookies_b64 = Column(Text, nullable=False)
        email = Column(String)
        updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
except Exception:
    class PublishedDeal:
        pass


    class IngestLog:
        pass


    class PatreonSession:
        pass
