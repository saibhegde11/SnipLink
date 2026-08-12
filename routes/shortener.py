"""
Shortener Routes — URL Creation & Redirect

POST /shorten      → Create a new short URL (with optional custom alias and TTL)
GET  /{short_code} → Redirect to the original URL (logs click analytics)
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from schemas import URLCreateRequest, URLCreateResponse
from services.cache import RedisCache
from services.encoder import encode_base62

logger = logging.getLogger("sniplink.shortener")

router = APIRouter()


# ── Dependencies ─────────────────────────────────────────────

def get_db():
    """Yield a database session, ensuring it's closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Singleton cache instance — imported by main.py and injected here
_cache: RedisCache | None = None


def set_cache(cache: RedisCache) -> None:
    """Called during app startup to inject the shared Redis cache."""
    global _cache
    _cache = cache


def get_cache() -> RedisCache:
    """Dependency that returns the shared Redis cache instance."""
    if _cache is None:
        raise RuntimeError("Cache not initialized")
    return _cache


# ── Routes ───────────────────────────────────────────────────

@router.post("/shorten", response_model=URLCreateResponse)
def create_short_url(
    payload: URLCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """
    Create a new shortened URL.

    - Optionally provide a `custom_alias` for a branded short code.
    - Optionally provide `minutes_to_live` for auto-expiring links.
    - Rate limited to 10 requests per 60 seconds per IP.
    - If the URL was already shortened, returns the existing short code.
    """
    # ── Rate Limiting ──
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"rate_limit:{client_ip}"
    allowed, count = cache.rate_limit_check(rate_key, max_requests=10, window_seconds=60)

    if not allowed:
        logger.warning("Rate limit exceeded for IP %s (%d requests)", client_ip, count)
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )

    target_url = str(payload.url)

    # ── Custom Alias Check ──
    if payload.custom_alias:
        existing_alias = (
            db.query(models.URL)
            .filter(models.URL.s_url == payload.custom_alias)
            .first()
        )
        if existing_alias:
            raise HTTPException(
                status_code=409,
                detail=f"Alias '{payload.custom_alias}' is already taken.",
            )

    # ── Check for Duplicate URL ──
    # Only return existing if no custom alias was requested
    if not payload.custom_alias:
        existing_url = db.query(models.URL).filter(models.URL.url == target_url).first()
        if existing_url:
            logger.info("URL already shortened: %s → %s", target_url, existing_url.s_url)
            base_url = str(request.base_url).rstrip("/")
            return URLCreateResponse(
                short_code=existing_url.s_url,
                short_url=f"{base_url}/{existing_url.s_url}",
                original_url=existing_url.url,
                created_at=existing_url.created_at,
                expires_at=existing_url.expires_at,
            )

    # ── Create New URL Record ──
    expires_at = None
    if payload.minutes_to_live:
        expires_at = datetime.now() + timedelta(minutes=payload.minutes_to_live)

    new_url = models.URL(
        url=target_url,
        custom_alias=payload.custom_alias,
        expires_at=expires_at,
    )
    db.add(new_url)
    db.commit()
    db.refresh(new_url)

    # Generate short code: use custom alias if provided, else base62 of ID
    short_code = payload.custom_alias if payload.custom_alias else encode_base62(new_url.id)
    new_url.s_url = short_code
    db.commit()
    db.refresh(new_url)

    # ── Pre-populate Cache ──
    # Cache the mapping immediately so the first redirect is a cache hit
    cache_ttl = payload.minutes_to_live * 60 if payload.minutes_to_live else 3600
    cache.set(short_code, target_url, ttl_seconds=cache_ttl)

    base_url = str(request.base_url).rstrip("/")
    logger.info("Created short URL: %s → %s", short_code, target_url)

    return URLCreateResponse(
        short_code=short_code,
        short_url=f"{base_url}/{short_code}",
        original_url=target_url,
        created_at=new_url.created_at,
        expires_at=new_url.expires_at,
    )


@router.get("/{short_code}")
def redirect_to_url(
    short_code: str,
    request: Request,
    db: Session = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """
    Redirect a short code to its original URL.

    - First checks Redis cache (fast path).
    - On cache miss, queries MySQL and populates cache.
    - Logs a ClickEvent with referrer, user-agent, and client IP for analytics.
    - Returns HTTP 307 Temporary Redirect (preserves HTTP method).
    """
    # ── Cache Check ──
    cached_url = cache.get(short_code)

    if cached_url:
        logger.debug("Cache HIT: %s", short_code)
        # Log click event asynchronously (still need DB for analytics)
        _log_click_event(db, short_code, request)
        return RedirectResponse(url=cached_url, status_code=307)

    # ── Cache Miss → Database Lookup ──
    logger.debug("Cache MISS: %s", short_code)
    url_record = db.query(models.URL).filter(models.URL.s_url == short_code).first()

    if not url_record:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # Check if expired
    if url_record.expires_at and url_record.expires_at < datetime.now():
        raise HTTPException(status_code=410, detail="This short URL has expired")

    # Increment click counter and log event
    url_record.clicks += 1
    _log_click_event(db, short_code, request, url_record)
    db.commit()

    # Populate cache for next time
    cache.set(short_code, url_record.url, ttl_seconds=3600)

    return RedirectResponse(url=url_record.url, status_code=307)


def _log_click_event(
    db: Session,
    short_code: str,
    request: Request,
    url_record: models.URL | None = None,
) -> None:
    """
    Record a click event with analytics data.

    If url_record is not provided (cache hit path), we look it up.
    """
    if url_record is None:
        url_record = db.query(models.URL).filter(models.URL.s_url == short_code).first()
        if url_record is None:
            return
        url_record.clicks += 1

    event = models.ClickEvent(
        url_id=url_record.id,
        referrer=request.headers.get("referer"),
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(event)
    db.commit()
