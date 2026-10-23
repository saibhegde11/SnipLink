"""Benchmark-only app wrapper; the project's API file stays unchanged."""

import os
import sqlite3

import cache_practice as cache
import storage_practice as storage
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

MODE = os.environ["SNIP_BENCH_MODE"]
SEED_COUNT = int(os.environ.get("SNIP_BENCH_SEEDS", "1000"))
memory_store = None

if MODE == "dict":
    from benchmarks.dictionary_storage import DictionaryStorage

    memory_store = DictionaryStorage()
    for name in ("initialize_database", "save_link", "find_link_details",
                 "find_link", "delete_link", "count_links", "record_click",
                 "get_click_count"):
        setattr(storage, name, getattr(memory_store, name))
else:
    storage.DB_FILE = os.environ["SNIP_BENCH_DB"]

if MODE == "redis":
    cache.redis_client = Redis(
        host="127.0.0.1", port=int(os.environ["SNIP_BENCH_REDIS_PORT"]),
        decode_responses=True, socket_connect_timeout=1, socket_timeout=1,
        retry=Retry(NoBackoff(), 0),
    )
else:
    # Disable cache operations entirely rather than time failed Redis connections.
    cache.get_cached_link = lambda short_code: None
    cache.cache_link_with_expiry = lambda short_code, details, now: False
    cache.delete_cached_link = lambda short_code: False

# Storage and cache are selected before the API imports their functions.
from sniplinkLearning_Uv import app  # noqa: E402

rows = [(f"s{i:08d}", f"https://example.com/page/{i}", None)
        for i in range(SEED_COUNT)]
if memory_store is not None:
    for row in rows:
        memory_store.save_link(*row)
else:
    with sqlite3.connect(storage.DB_FILE) as connection:
        connection.executemany(
            "INSERT INTO links (short_code, original_url, expires_at) VALUES (?, ?, ?)",
            rows,
        )


@app.get("/_benchmark/state", include_in_schema=False)
def benchmark_state():
    if memory_store is not None:
        return memory_store.state()
    with sqlite3.connect(storage.DB_FILE) as connection:
        count, clicks = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(click_count), 0) FROM links"
        ).fetchone()
        return {
            "rows": count, "clicks": clicks,
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
            "sqlite_version": sqlite3.sqlite_version,
        }
