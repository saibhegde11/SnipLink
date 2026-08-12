"""
Redis Cache Wrapper

Provides a resilient Redis client that gracefully degrades when Redis is
unavailable. Instead of crashing the app, cache operations log a warning
and return None / no-op, allowing the application to fall through to the
database.
"""

import logging

import redis

logger = logging.getLogger("sniplink.cache")


class RedisCache:
    """
    A thin wrapper around redis.Redis with graceful error handling.

    If Redis is down, all operations silently degrade:
      - get() returns None (cache miss)
      - set() and delete() become no-ops
      - rate_limit_check() always allows the request

    This ensures the app stays functional even without Redis,
    just slower (no caching) and unprotected (no rate limiting).
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self._client = redis.Redis(
            host=host, port=port, db=db, decode_responses=True
        )
        # Test connection on init
        try:
            self._client.ping()
            logger.info("Redis connected at %s:%d", host, port)
        except redis.ConnectionError:
            logger.warning("Redis not available at %s:%d — running without cache", host, port)

    def get(self, key: str) -> str | None:
        """Retrieve a value from cache. Returns None on miss or error."""
        try:
            return self._client.get(key)
        except redis.RedisError as e:
            logger.warning("Redis GET failed for key '%s': %s", key, e)
            return None

    def set(self, key: str, value: str, ttl_seconds: int | None = 3600) -> bool:
        """
        Store a value in cache with an optional TTL.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: Time-to-live in seconds. None for no expiry.

        Returns:
            True if stored successfully, False on error.
        """
        try:
            if ttl_seconds:
                self._client.set(key, value, ex=ttl_seconds)
            else:
                self._client.set(key, value)
            return True
        except redis.RedisError as e:
            logger.warning("Redis SET failed for key '%s': %s", key, e)
            return False

    def delete(self, key: str) -> bool:
        """Remove a key from cache. Returns True on success."""
        try:
            self._client.delete(key)
            return True
        except redis.RedisError as e:
            logger.warning("Redis DELETE failed for key '%s': %s", key, e)
            return False

    def rate_limit_check(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """
        Check if a rate-limited action is allowed using Redis INCR + EXPIRE.

        Args:
            key: The rate limit key (e.g. "rate_limit:192.168.1.1").
            max_requests: Maximum allowed requests in the window.
            window_seconds: Duration of the rate limit window.

        Returns:
            A tuple of (allowed: bool, current_count: int).
            If Redis is down, always returns (True, 0) — fail open.
        """
        try:
            count = self._client.incr(key)

            # First request in this window — set the expiry
            if count == 1:
                self._client.expire(key, window_seconds)

            return count <= max_requests, count
        except redis.RedisError as e:
            logger.warning("Redis rate limit check failed: %s — allowing request", e)
            return True, 0
