import json
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from pydantic import BaseModel, ConfigDict, Field, ValidationError

class CachedLink(BaseModel):
    model_config = ConfigDict(
        strict=True,
        allow_inf_nan=False
    )

    short_code: str
    original_url: str = Field(min_length=1)
    expires_at: float | None

redis_client = redis.Redis(
    host = "127.0.0.1",
    port = 6379,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
    retry=Retry(NoBackoff(), 0)
)

def cache_key(short_code : str) -> str : 
    return f"sniplink:link:{short_code}"

def get_cached_link(short_code : str) -> dict | None : 
    value = redis_client.get(cache_key(short_code))

    if value is None : 
        return None

    try : 
        details = CachedLink.model_validate_json(value)
    except ValidationError:
        return None

    if details.short_code != short_code:
        return None

    return details.model_dump()

def cache_link(short_code : str, details : dict, ttl_seconds : int) -> bool:
    if ttl_seconds <= 0 : 
        raise ValueError("TTL should be greater than 0") 

    key = cache_key(short_code)
    value = json.dumps(details)
    return bool(redis_client.set(key, value, ex=ttl_seconds))

def calculate_cache_ttl(
    expires_at : float | None,
    now : float,
    max_ttl : int = 60
) -> int : 
        if max_ttl <= 0 : 
            raise ValueError("Maximum Cache TTL must be greater than 0")
        
        if expires_at is None : 
                return max_ttl
        remaining_seconds = int(expires_at - now)
        ttl = min(max_ttl, remaining_seconds)
        return max(0, ttl)

def cache_link_with_expiry(short_code : str, details : dict, now : float) -> bool: 
    ttl = calculate_cache_ttl(details["expires_at"], now)
    if ttl <= 0 : 
        return False
    return bool(cache_link(short_code, details, ttl))

def delete_cached_link(short_code : str) -> bool : 
    return redis_client.delete(cache_key(short_code)) > 0

