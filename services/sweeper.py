"""
Background Database Sweeper

Runs as an asyncio background task that periodically scans for expired
short URLs and removes them from both the database and Redis cache.
"""

import asyncio
import logging
from datetime import datetime

from database import SessionLocal
import models
from services.cache import RedisCache

logger = logging.getLogger("sniplink.sweeper")


async def run_sweeper(cache: RedisCache, interval_seconds: int = 60) -> None:
    """
    Periodically scan for and delete expired short URLs.

    Runs indefinitely, sleeping for `interval_seconds` between sweeps.
    Deletes expired URLs and their associated click events from the
    database, and removes their cache entries from Redis.

    Args:
        cache: The Redis cache instance for clearing cached redirects.
        interval_seconds: Seconds to sleep between sweep cycles.
    """
    logger.info("Sweeper started (interval=%ds)", interval_seconds)

    while True:
        try:
            await _sweep_expired(cache)
        except Exception as e:
            logger.error("Sweeper encountered an error: %s", e)

        await asyncio.sleep(interval_seconds)


async def _sweep_expired(cache: RedisCache) -> None:
    """Execute a single sweep cycle: find and delete expired links."""
    db = SessionLocal()
    try:
        now = datetime.now()
        expired_links = (
            db.query(models.URL)
            .filter(models.URL.expires_at.isnot(None))
            .filter(models.URL.expires_at < now)
            .all()
        )

        if not expired_links:
            return

        for link in expired_links:
            logger.info("Deleting expired link: %s → %s", link.s_url, link.url)

            # Remove associated click events first (FK constraint)
            db.query(models.ClickEvent).filter(
                models.ClickEvent.url_id == link.id
            ).delete()

            # Remove from Redis cache
            if link.s_url:
                cache.delete(link.s_url)

            # Remove from database
            db.delete(link)

        db.commit()
        logger.info("Swept %d expired link(s)", len(expired_links))

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
