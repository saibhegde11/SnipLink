import pytest
from fastapi.testclient import TestClient
import storage_practice as storage
import expiry_practice as expiry
import cache_practice as cache

@pytest.fixture
def clock(monkeypatch) : 
    state = {"now" : 1000}

    def fake_now() : 
        return state["now"]

    monkeypatch.setattr(
        expiry, 
        "current_timestamp",
        fake_now
    )

    return state

@pytest.fixture # add this above the fns ilke client, clock, etc... (which we will pass)
def client(tmp_path, monkeypatch, cache_store) : 
    test_db = tmp_path / "test_links.db"
    monkeypatch.setattr(storage, "DB_FILE", str(test_db))

    from sniplinkLearning_Uv import app

    storage.initialize_database()

    with TestClient(app) as test_client : 
        yield test_client

def test_generated_link_is_saved_once(client) : 
    url = "https://docs.python.org/3/"

    response = client.post(
        "/links",
        json={"original_url" : url}
    )

    assert response.status_code == 201
    code = response.json()["short_code"]

    lookup = client.get(f"/links/{code}")

    assert lookup.status_code == 200
    assert lookup.json() == {
        "short_code" : code,
        "original_url" : url
    }

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 1

def test_redirect_returns_destination(client) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links", 
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )
    assert created.status_code == 201

    response = client.get(
        "/r/docs",
        follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == url  

def test_duplicate_alias_keeps_original_link(client) :
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "docs", 
            "original_url" : url
        }
    )
    assert created.status_code == 201

    new_created = client.post(
        "/links", 
        json={
            "short_code" : "docs",
            "original_url" : "https://www.google.com"
        }
    )
    assert new_created.status_code == 409

    response = client.get(
        "/links/docs"
    )
    assert response.status_code == 200
    assert response.json()["original_url"] == url
    
    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 1

def test_invalid_url_does_not_save_link(client) : 
    response = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : "not_a_url"
        }
    )
    assert response.status_code == 422
    
    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 0

def test_missing_link_returns_404(client) : 
    lookup = client.get("/links/not_a_short_code")
    assert lookup.status_code == 404

    response = client.get(
        "/r/not_a_short_code",
        follow_redirects=False
    )
    assert response.status_code == 404
    
    deleted = client.delete("/links/not_a_short_code")
    assert deleted.status_code == 404

    stats = client.get("/links/not_a_short_code/stats")
    assert stats.status_code == 404

def test_deleted_link_cannot_be_used(client) : 
    url = "https://docs.python.org/3/"
    response = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )
    assert response.status_code == 201

    deleted = client.delete("/links/docs")
    assert deleted.status_code == 200
    assert deleted.json()["Deleted"] is True

    lookup = client.get("/links/docs")
    assert lookup.status_code == 404

    redirect = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert redirect.status_code == 404

    deleted_again = client.delete("/links/docs")
    assert deleted_again.status_code == 404

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 0

def test_generated_link_expires_at_deadline(client, clock) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "original_url" : url,
            "expires_in" : 60
        }
    )

    assert created.status_code == 201

    data = created.json()
    code = data["short_code"]
    assert data["expires_at"] == 1060.0

    clock["now"] = 1059.0

    active = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert active.status_code == 302
    assert active.headers["location"] == url

    clock["now"] = 1060.0
    expired = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert expired.status_code == 410

    clock["now"] = 1061.0
    expired = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert expired.status_code == 410

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 1

def test_link_without_expiry_stays_active(client, clock) : 
    url = "https://docs.python.org/3/"
    created = client.post(
        "/links",
        json={
            "original_url" : url
        }
    )
    assert created.status_code == 201
    data = created.json()
    code = data["short_code"]
    assert data["expires_at"] is None

    clock["now"] =  1000000.0
    active = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert active.status_code == 302
    assert active.headers["location"] == url

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 1

def test_custom_link_expiry(client, clock) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "SaiBh",
            "original_url" : url,
            "expires_in" : 30
        }
    )
    assert created.status_code == 201
    code = created.json()["short_code"]
    assert code == "SaiBh"
    assert created.json()["expires_at"] == 1030.0
    clock["now"] = 1029.0

    active = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert active.status_code == 302
    assert active.headers["location"] == url 

    clock["now"] = 1030.0
    active = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert active.status_code == 410

    clock["now"] = 1031.0
    active = client.get(
        f"/r/{code}",
        follow_redirects=False
    )
    assert active.status_code == 410
    
    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 1

    count = client.get("/links/SaiBh/stats")
    assert count.status_code == 200
    assert count.json()["count"] == 1

def test_redirect_updates_click_count(client) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )
    assert created.status_code == 201

    lookup = client.get("/links/docs") 
    assert lookup.status_code == 200

    stats = client.get("/links/docs/stats")
    assert stats.status_code == 200
    assert stats.json() == {
        "short_code" : "docs",
        "count" : 0
    }

    for _ in range(2) : 
        response = client.get(
            "/r/docs",
            follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == url

    stats = client.get("/links/docs/stats") 
    assert stats.status_code == 200
    assert stats.json()["count"] == 2

def test_redirect_reuses_cached_mapping(client, cache_store, monkeypatch) : 
    import sniplinkLearning_Uv as api   
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links", 
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )
    assert created.status_code == 201

    lookup_calls = []
    real_lookup = api.find_link_details

    def tracked_lookup(short_code) : 
        lookup_calls.append(short_code)
        return real_lookup(short_code)
    
    monkeypatch.setattr(
        api, 
        "find_link_details",
        tracked_lookup
    )
    for _ in range(2) : 
        response = client.get(
            "/r/docs",
            follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == url
    
    assert lookup_calls == ["docs"]
    assert cache.get_cached_link("docs") is not None

    stats = client.get("/links/docs/stats")
    assert stats.status_code == 200
    assert stats.json()["count"] == 2

def test_delete_removes_cached_mapping(client, cache_store) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )

    assert created.status_code == 201

    redirected = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert redirected.status_code == 302
    assert cache.get_cached_link("docs") is not None

    deleted = client.delete("/links/docs")
    assert deleted.status_code == 200
    assert deleted.json()["Deleted"] is True

    assert cache.get_cached_link("docs") is None

    redirected_again = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert redirected_again.status_code == 404

def test_redirect_works_when_redis_is_unavailable(client, cache_server) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )
    assert created.status_code == 201

    cache_server.connected = False

    response = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == url

    stats = client.get("/links/docs/stats")
    assert stats.status_code == 200
    assert stats.json()["count"] == 1

def test_delete_works_when_redis_is_unavailable(client, cache_server) : 
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : url
        }
    )
    assert created.status_code == 201

    warmed = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert warmed.status_code == 302

    cached_response = cache.get_cached_link("docs")
    assert cached_response is not None

    cache_server.connected = False

    deleted = client.delete("/links/docs")
    assert deleted.status_code == 200
    assert deleted.json()["Deleted"] is True

    revisit = client.get("/links/docs")
    assert revisit.status_code == 404
    
    redirect = client.get(
        "/r/docs", 
        follow_redirects=False
    )
    assert redirect.status_code == 404

def test_cached_link_still_expires(client, clock) : 
    clock["now"] = 1000.0

    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code" : "docs",
            "original_url" : url,
            "expires_in" : 30
        }
    )
    assert created.status_code == 201
    assert created.json()["expires_at"] == 1030.0

    redirect = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert redirect.status_code == 302
    assert redirect.headers["location"] == url

    clock["now"] = 1030.0
    check_cache_mapping = cache.get_cached_link("docs")
    assert check_cache_mapping is not None

    new_redirect = client.get(
        "/r/docs",
        follow_redirects=False
    )
    assert new_redirect.status_code == 410

    stats = client.get("/links/docs/stats")
    assert stats.status_code == 200
    assert stats.json()["count"] == 1

def test_reused_code_uses_new_url_after_cache_outage(
    client, cache_server
):
    old_url = "https://docs.python.org/3/"
    new_url = "https://www.python.org/"

    created = client.post(
        "/links",
        json={
            "short_code": "docs",
            "original_url": old_url
        }
    )
    assert created.status_code == 201

    warmed = client.get("/r/docs", follow_redirects=False)
    assert warmed.status_code == 302
    assert warmed.headers["location"] == old_url

    cache_server.connected = False
    try:
        deleted = client.delete("/links/docs")
        assert deleted.status_code == 200

        recreated = client.post(
            "/links",
            json={
                "short_code": "docs",
                "original_url": new_url
            }
        )
        assert recreated.status_code == 201
    finally:
        cache_server.connected = True

    redirected = client.get("/r/docs", follow_redirects=False)
    assert redirected.status_code == 302
    assert redirected.headers["location"] == new_url

def test_invalid_cached_json_falls_back_to_sqlite(client, cache_store):
    url = "https://docs.python.org/3/"

    created = client.post(
        "/links",
        json={
            "short_code": "docs",
            "original_url": url
        }
    )
    assert created.status_code == 201

    cache_store.set(
        cache.cache_key("docs"),
        "not-json",
        ex=60
    )

    response = client.get("/r/docs", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == url

    stats = client.get("/links/docs/stats")
    assert stats.status_code == 200
    assert stats.json()["count"] == 1

    assert cache.get_cached_link("docs") == {
        "short_code": "docs",
        "original_url": url,
        "expires_at": None
    }


def test_expiry_above_maximum_does_not_save_link(client):
    response = client.post(
        "/links",
        json={
            "short_code": "docs",
            "original_url": "https://docs.python.org/3/",
            "expires_in": 31_536_001
        }
    )

    assert response.status_code == 422

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["total_links"] == 0