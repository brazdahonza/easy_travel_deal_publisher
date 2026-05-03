from typing import List, Optional

from pydantic import BaseModel, Field


class PatreonDraftPayload(BaseModel):
    """Body of POST /publish/patreon — already-formatted Patreon post."""
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    destination: Optional[str] = Field(
        None,
        description="Optional. Used to look up a hero image under assets/patreon/.",
    )


class PatreonDraftResult(BaseModel):
    status: str
    draft_url: Optional[str] = None
    post_id: Optional[str] = None


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
    """Body of POST /session/patreon — a pre-captured cookie blob."""
    cookies: List[PatreonCookie]
    email: Optional[str] = None


class SessionStatusOut(BaseModel):
    cookies_present: bool
    cookies_count: int
    email: Optional[str] = None
    stored_at: Optional[str] = None
    needs_refresh: bool
    last_error: Optional[str] = None
