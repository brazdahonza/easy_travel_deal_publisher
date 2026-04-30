from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from datetime import date


class DealIn(BaseModel):
    id: str
    destination: str
    departure_city: str
    price: int
    median_price: Optional[int] = None
    discount_pct: Optional[float] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    duration_days: Optional[int] = None
    ticket_url: Optional[HttpUrl] = None
    is_nearby: Optional[bool] = None
    extra: Optional[str] = None


class IngestPayload(BaseModel):
    deals: List[DealIn]


class PublishedDealOut(BaseModel):
    id: int
    destination: str
    departure_city: str
    price: int
    median_price: Optional[int]
    discount_pct: Optional[float]
    date_from: Optional[date]
    date_to: Optional[date]
    duration_days: Optional[int]
    published_at: Optional[str]
    published_to: Optional[str]
    post_text_patreon: Optional[str]
    post_text_x: Optional[str]


class IngestLogOut(BaseModel):
    id: int
    received_at: Optional[str]
    deals_count: int
    selected_count: Optional[int]
    status: str
    error_message: Optional[str]


class StatsOut(BaseModel):
    total_deals: int
    by_platform: dict
    ingest_totals: dict
    ingest_by_status: dict
    avg_discount_pct: Optional[float]
    avg_price: Optional[float]
    min_price: Optional[int]
    max_price: Optional[int]
    top_destinations: list
    last_7_days_deals: int
    last_7_days_ingests: int


class DeleteResult(BaseModel):
    deleted: int


class PatreonCookie(BaseModel):
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: Optional[float] = None
    httpOnly: Optional[bool] = None
    secure: Optional[bool] = None
    sameSite: Optional[str] = None


class PatreonSessionPayload(BaseModel):
    cookies: List[PatreonCookie]
    email: Optional[str] = None
