import pytest
import fakeredis
import cache_practice as cache
from redis.backoff import NoBackoff
from redis.retry import Retry

@pytest.fixture
def cache_server() : 
    return fakeredis.FakeServer()

@pytest.fixture
def cache_store(monkeypatch, cache_server) : 
    fake = fakeredis.FakeRedis(
        server=cache_server,
        decode_responses=True,
        retry=Retry(NoBackoff(), 0)
    )

    monkeypatch.setattr(cache, "redis_client", fake)
    return fake