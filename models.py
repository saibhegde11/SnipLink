"""
SQLAlchemy Models — Database Schema

Defines the database tables:
  - URL: Stores shortened URLs with metadata
  - ClickEvent: Logs every redirect with analytics data (referrer, user-agent, IP)
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from database import Base


class URL(Base):
    """
    Represents a shortened URL.

    Attributes:
        id:           Auto-incremented primary key (used for base62 encoding).
        url:          The original long URL.
        s_url:        The generated or custom short code.
        custom_alias: If the user provided a custom alias, it's stored here.
        clicks:       Total click count (denormalized for fast reads).
        created_at:   Timestamp when the short URL was created.
        expires_at:   Optional expiry timestamp (NULL = never expires).
        click_events: Relationship to detailed click analytics.
    """

    __tablename__ = "s_URL"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(2048), index=True, nullable=False)
    s_url = Column(String(255), unique=True, index=True)
    custom_alias = Column(String(20), nullable=True)
    clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=True)

    # One-to-many relationship with click events
    click_events = relationship(
        "ClickEvent", back_populates="url_record", cascade="all, delete-orphan"
    )


class ClickEvent(Base):
    """
    Logs a single redirect event for analytics.

    Each time a short URL is accessed, a ClickEvent is created with
    the client's referrer, user-agent, and IP address. This enables
    analytics like top referrers, device breakdowns, and click timelines.

    Attributes:
        id:         Auto-incremented primary key.
        url_id:     Foreign key to the parent URL record.
        clicked_at: Timestamp of the click.
        referrer:   The HTTP Referer header (where the user came from).
        user_agent: The client's User-Agent string.
        ip_address: The client's IP address.
    """

    __tablename__ = "click_events"

    id = Column(Integer, primary_key=True, index=True)
    url_id = Column(Integer, ForeignKey("s_URL.id"), nullable=False, index=True)
    clicked_at = Column(DateTime, default=datetime.now, index=True)
    referrer = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Supports IPv6

    url_record = relationship("URL", back_populates="click_events")
