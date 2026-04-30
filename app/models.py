try:
    from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Enum, func
    from .database import Base
    import enum


    class PublishedToEnum(str, enum.Enum):
        patreon = "patreon"
        x = "x"
        both = "both"


    class PublishedDeal(Base):
        __tablename__ = "published_deals"

        id = Column(Integer, primary_key=True, index=True)
        destination = Column(String, nullable=False)
        departure_city = Column(String, nullable=False)
        price = Column(Integer, nullable=False)
        median_price = Column(Integer)
        discount_pct = Column(Float)
        date_from = Column(Date)
        date_to = Column(Date)
        duration_days = Column(Integer)
        published_at = Column(DateTime, server_default=func.now())
        published_to = Column(Enum(PublishedToEnum), nullable=True)
        post_text_patreon = Column(Text)
        post_text_x = Column(Text)
        deal_hash = Column(String, index=True, nullable=False)


    class IngestLog(Base):
        __tablename__ = "ingest_log"

        id = Column(Integer, primary_key=True, index=True)
        received_at = Column(DateTime, server_default=func.now())
        deals_count = Column(Integer, nullable=False)
        selected_count = Column(Integer)
        status = Column(String, nullable=False)
        error_message = Column(Text)
except Exception:
    # SQLAlchemy not available in environment; provide placeholders for import-time
    import enum


    class PublishedToEnum(str, enum.Enum):
        patreon = "patreon"
        x = "x"
        both = "both"


    class PublishedDeal:
        pass


    class IngestLog:
        pass
