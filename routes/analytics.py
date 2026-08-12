"""
Analytics Routes — URL Statistics & Click Data

GET /api/stats/{short_code} → Full analytics for a shortened URL
"""

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from schemas import URLStatsResponse, ClickEventResponse

logger = logging.getLogger("sniplink.analytics")

router = APIRouter(prefix="/api", tags=["Analytics"])


def get_db():
    """Yield a database session, ensuring it's closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/stats/{short_code}", response_model=URLStatsResponse)
def get_url_stats(short_code: str, db: Session = Depends(get_db)):
    """
    Retrieve full analytics for a shortened URL.

    Returns:
        - Original URL, creation time, expiry time
        - Total click count
        - List of recent click events (last 100) with referrer, user-agent, IP
        - Top 10 referrers by frequency
        - Top 10 user agents by frequency
    """
    url_record = db.query(models.URL).filter(models.URL.s_url == short_code).first()

    if not url_record:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # Fetch recent click events (last 100, ordered newest first)
    click_events = (
        db.query(models.ClickEvent)
        .filter(models.ClickEvent.url_id == url_record.id)
        .order_by(models.ClickEvent.clicked_at.desc())
        .limit(100)
        .all()
    )

    # Build recent clicks response
    recent_clicks = [
        ClickEventResponse(
            clicked_at=event.clicked_at,
            referrer=event.referrer,
            user_agent=event.user_agent,
            ip_address=event.ip_address,
        )
        for event in click_events
    ]

    # Compute top referrers (ignoring None)
    referrers = [e.referrer for e in click_events if e.referrer]
    top_referrers = [
        {"referrer": ref, "count": count}
        for ref, count in Counter(referrers).most_common(10)
    ]

    # Compute top user agents (ignoring None)
    agents = [e.user_agent for e in click_events if e.user_agent]
    top_user_agents = [
        {"user_agent": ua, "count": count}
        for ua, count in Counter(agents).most_common(10)
    ]

    logger.info("Stats retrieved for %s: %d total clicks", short_code, url_record.clicks)

    return URLStatsResponse(
        short_code=short_code,
        original_url=url_record.url,
        created_at=url_record.created_at,
        expires_at=url_record.expires_at,
        total_clicks=url_record.clicks,
        recent_clicks=recent_clicks,
        top_referrers=top_referrers,
        top_user_agents=top_user_agents,
    )
