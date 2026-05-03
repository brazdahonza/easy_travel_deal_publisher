from pydantic import BaseModel, Field
from typing import List, Optional


class PostIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    destination_name: str = Field(..., min_length=1)


class IngestPayload(BaseModel):
    posts: List[PostIn]


class PublishedDealOut(BaseModel):
    id: int
    destination: str
    title: Optional[str]
    body: Optional[str]
    draft_url: Optional[str]
    post_id: Optional[str]
    published_at: Optional[str]


class IngestLogOut(BaseModel):
    id: int
    received_at: Optional[str]
    posts_count: int
    published_count: Optional[int]
    status: str
    error_message: Optional[str]


class StatsOut(BaseModel):
    total_posts: int
    ingest_totals: dict
    ingest_by_status: dict
    top_destinations: list
    last_7_days_posts: int
    last_7_days_ingests: int


class DeleteResult(BaseModel):
    deleted: int
