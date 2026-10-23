import cache_practice as cache

def test_cache_ttl_respects_link_deadline() : 
    assert cache.calculate_cache_ttl(None, 1000.0) == 60
    assert cache.calculate_cache_ttl(1300.0, 1000.0) == 60
    assert cache.calculate_cache_ttl(1030.0, 1000.0) == 30
    assert cache.calculate_cache_ttl(1000.0, 1000.0) == 0
    assert cache.calculate_cache_ttl(1000.5, 1000.0) == 0
    assert cache.calculate_cache_ttl(998.5, 1000.0) == 0

def test_cached_link_can_be_deleted(cache_store) : 
    details = {
        "short_code": "docs",
        "original_url": "https://docs.python.org/3/",
        "expires_at": None
    }

    assert cache.cache_link("docs", details, 60) is True
    assert cache.delete_cached_link("docs") is True
    assert cache.get_cached_link("docs") is None
    assert cache.delete_cached_link("docs") is False

def test_expired_mappings_arent_cached(cache_store) : 
    details = {
        "short_code": "docs",
        "original_url": "https://docs.python.org/3/",
        "expires_at": 999.0
    }
    now = 1000.0

    assert cache.cache_link_with_expiry("docs", details, now) is False
    assert cache.get_cached_link("docs") is None

    details = {
        "short_code": "docs",
        "original_url": "https://docs.python.org/3/",
        "expires_at": 1000.5
    }

    assert cache.cache_link_with_expiry("docs", details, now) is False
    assert cache.get_cached_link("docs") is None

def test_shorter_lifetime_limits_stored_cache_ttl(cache_store) : 
    details = {
        "short_code" : "docs",
        "original_url" : "https://docs.python.org/3/",
        "expires_at" : 1030.0
    }
    now = 1000.0

    assert cache.cache_link_with_expiry("docs", details, now) is True
    assert cache.get_cached_link("docs") == details

    ttl = cache_store.ttl(cache.cache_key("docs"))
    assert 0 <= ttl <= 30
