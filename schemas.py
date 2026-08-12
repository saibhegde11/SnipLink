"""
Pydantic Schemas — Request and Response Models

Defines the API contract for the URL shortener endpoints.
Separating schemas from SQLAlchemy models keeps the API layer
clean and decoupled from the database layer.
"""

from datetime import datetime

from pydantic import BaseModel, HttpUrl, Field


# ── Request Schemas ──────────────────────────────────────────


class URLCreateRequest(BaseModel):
    """Request body for creating a new short URL."""

    url: HttpUrl = Field(..., description="The original URL to shorten")
    custom_alias: str | None = Field(
        None,
        min_length=3,
        max_length=20,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Optional custom short code (3-20 alphanumeric chars, hyphens, underscores)",
    )
    minutes_to_live: int | None = Field(
        None,
        gt=0,
        description="Optional TTL in minutes. The link expires after this duration.",
    )


# ── Response Schemas ─────────────────────────────────────────


class URLCreateResponse(BaseModel):
    """Response after successfully creating a short URL."""

    short_code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None = None


class ClickEventResponse(BaseModel):
    """A single click event in the analytics response."""

    clicked_at: datetime
    referrer: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None


class URLStatsResponse(BaseModel):
    """Full analytics for a shortened URL."""

    short_code: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None = None
    total_clicks: int
    recent_clicks: list[ClickEventResponse]
    top_referrers: list[dict]
    top_user_agents: list[dict]
