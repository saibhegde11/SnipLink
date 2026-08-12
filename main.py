"""
SnipLink — URL Shortener API

Main entry point. Wires together the FastAPI application, database
initialization, background tasks, and route registration.

Usage:
    uvicorn main:app --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import models
from database import engine
from services.cache import RedisCache
from services.sweeper import run_sweeper
from routes import shortener, analytics

# ── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-22s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sniplink")

# ── Shared Redis Cache ───────────────────────────────────────

cache = RedisCache(host="localhost", port=6379, db=0)


# ── Application Lifespan ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the application."""

    # ─ Startup ─
    # Create database tables (if they don't exist)
    models.Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")

    # Inject the shared cache into the shortener routes
    shortener.set_cache(cache)

    # Launch the background sweeper for expired links
    sweeper_task = asyncio.create_task(run_sweeper(cache, interval_seconds=60))
    logger.info("SnipLink is ready.")

    yield  # ← App is running

    # ─ Shutdown ─
    sweeper_task.cancel()
    try:
        await sweeper_task
    except asyncio.CancelledError:
        pass
    logger.info("SnipLink has shut down.")


# ── FastAPI App ──────────────────────────────────────────────

app = FastAPI(
    title="SnipLink",
    description="A fast, analytics-enabled URL shortener with Redis caching and MySQL storage.",
    version="1.0.0",
    lifespan=lifespan,
)

# Register route modules
app.include_router(analytics.router)   # /api/stats/{code} — registered FIRST to avoid catch-all conflict
app.include_router(shortener.router)   # /shorten + /{short_code}
