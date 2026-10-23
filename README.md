# SnipLink

SnipLink is a URL shortener built with FastAPI, SQLite, and Redis. It supports custom or generated short codes, persistent mappings, optional link expiry, and click counts.

Redis caches redirect mappings with a bounded lifetime. SQLite stores the mappings and click counts, and the API falls back to SQLite when Redis is unavailable. The project includes 26 passing correctness tests and reproducible local benchmarks comparing a dictionary, SQLite, and SQLite with Redis.

## Running locally

The commands below are for Windows PowerShell. The project was tested with Python 3.12. Docker Desktop is needed if you want to run Redis in a container.

Run these commands from the folder containing `sniplinkLearning_Uv.py`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create the Redis container once:

```powershell
docker run -d --name sniplink-redis -p 127.0.0.1:6379:6379 redis:latest
```

On later runs, start the existing container:

```powershell
docker start sniplink-redis
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn sniplinkLearning_Uv:app --reload
```

The server runs at [http://127.0.0.1:8000](http://127.0.0.1:8000). Open [the API documentation](http://127.0.0.1:8000/docs) to try the endpoints in your browser.

The application creates `sniplink_practice.db` automatically. Its path is relative to the folder where you start the server, so use the same project folder on later runs to keep using the same database.

On Linux or macOS, create the environment with `python3 -m venv .venv` and use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

## Creating a link

With the server running, open another PowerShell window and send a request:

```powershell
$linkRequest = '{"short_code":"docs","original_url":"https://docs.python.org/3/"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/links" -ContentType "application/json" -Body $linkRequest
```

The API returns `201` with this JSON body:

```json
{
  "short_code": "docs",
  "original_url": "https://docs.python.org/3/",
  "redirect_url": "http://127.0.0.1:8000/r/docs",
  "expires_at": null
}
```

Use an unused code when trying this example. Creating a second link with the same code returns `409`.

Open [http://127.0.0.1:8000/r/docs](http://127.0.0.1:8000/r/docs) to follow the redirect. You can check its click count with:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/links/docs/stats"
```

After one successful redirect, the response body is:

```json
{
  "short_code": "docs",
  "count": 1
}
```

To generate a code and give the link a lifetime of 60 seconds, send this body to `POST /links` through the API documentation:

```json
{
  "original_url": "https://docs.python.org/3/",
  "expires_in": 60
}
```

Generated codes contain six characters. Custom codes must contain between 3 and 20 characters and can use uppercase letters, lowercase letters, numbers, underscores, and hyphens. URLs must use HTTP or HTTPS.

`expires_in` accepts an integer number of seconds from 1 to 31,536,000, which is 365 days. Omitting it or sending `null` creates a link without an expiry time. The response field `expires_at` is the absolute Unix timestamp in seconds when the link expires.

To delete the example link:

```powershell
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/links/docs"
```

A successful deletion returns `{"Deleted": true}`. Deleting the same code again returns `404`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Return `{"status": "ok"}`. |
| POST | `/links` | Create a mapping and return `201`. |
| GET | `/links/{short_code}` | Return the code and original URL. |
| GET | `/r/{short_code}` | Record a click and return a `302` redirect. |
| DELETE | `/links/{short_code}` | Delete the mapping and attempt to remove its cached copy. |
| GET | `/stats` | Return the number of stored links as `total_links`. |
| GET | `/links/{short_code}/stats` | Return the code and its click count as `count`. |

An unknown code returns `404`. Duplicate custom codes return `409`, invalid request bodies return `422`, and expired redirects return `410`. A `503` response means code generation exhausted its attempts or the mapping kept changing during a redirect.

The click counter increases for each successful redirect decision. Repeated requests from the same visitor count separately. Looking up a link's details or statistics does not increase the counter.

## Storage and expiry

SQLite stores the short code, original URL, expiry timestamp, and click count. Committed records remain available after the server restarts. The short code is the primary key, so SQLite enforces uniqueness when a mapping is inserted. Queries use placeholders for input values.

Expiry stops redirects when the current time reaches `expires_at`. Expired rows stay in SQLite, so their details and statistics remain available. `/stats` includes those rows. An expired code stays reserved until its mapping is deleted.

## How Redis fits in

Each short code has its own Redis key. A redirect checks Redis first and reads SQLite on a cache miss. The mapping is then cached for up to 60 seconds, limited by the link's remaining lifetime and rounded down to whole seconds. A cache hit does not restart that timer.

Cached JSON is validated before use. Invalid JSON, missing fields, incorrect types, and mismatched short codes are treated as cache misses. If Redis is unavailable, the API falls back to SQLite.

Every successful redirect still writes to SQLite to record the click. That update also checks that the URL and expiry match the mapping used by the handler. If a cached mapping is stale, the handler reads SQLite again and retries once. This handles a code being deleted and recreated while Redis is unavailable.

Deletion commits the SQLite change before attempting to remove the Redis key. If cache invalidation fails, the database deletion still succeeds. SQLite remains the source of truth.

Redis reduces repeated mapping reads. The SQLite write on every redirect is still a limit to consider as traffic grows.

## Tests

Install the test dependencies and run the suite from the project folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The current suite has 26 passing tests. It covers creation, duplicate codes, validation, lookup, deletion, redirects, expiry boundaries, click counts, cache reuse, Redis outages, stale cached mappings, and malformed cached JSON.

Tests use temporary SQLite databases and `fakeredis`. A running Redis server is not required for the suite, and the tests do not use the application's normal database file.

## Benchmarks

The recorded benchmark ran on 23 October 2026. It compared three storage setups behind the same API routes, with validation, expiry metadata, and click counting retained in every setup. The dictionary baseline reconstructs the current storage interface; it is not an archived earlier revision.

The HTTP matrix contains 36 trials: three repeats for each setup at 1, 8, 32, and 64 concurrent clients. Each trial started with 1,000 mappings without expiry, used two seconds of warmup, and measured eight seconds of request starts before draining outstanding responses.

The synthetic traffic mix was 90% redirects, 5% metadata lookups, and 5% link creations. For existing links, 80% of selections came from 100 hot links and the rest from the other 900. Each load client waited for its response before sending its next request, without a pause. Redirects were checked without following them to external websites.

The API, client processes, and real Redis server shared a Linux container with an eight CPU quota and an 8 GiB memory limit. The run used one Uvicorn worker without reload or access logging. Versions were Python 3.12.14, FastAPI 0.161.1, SQLite 3.53.1, and Redis 6.2.14. SQLite retained rollback journal mode `delete` and `synchronous=2` (`FULL`).

### HTTP results

Requests/s counts successful responses. Throughput and p95 are medians across the three repeated trials. Each trial's p95 is the time within which 95% of measured attempts completed. Errors and attempts are totals across the three measured phases, and failed attempts remain in latency calculations. Throughput timing includes the final drain.

| Concurrent clients | Storage | Requests/s | p95 response time (ms) | Errors / requests |
| --- | --- | ---: | ---: | ---: |
| 1 | Python dictionary | 658.2 | 1.89 | 0 / 15,366 |
| 1 | SQLite | 309.4 | 3.86 | 0 / 7,404 |
| 1 | SQLite + Redis | 303.2 | 4.03 | 0 / 7,193 |
| 8 | Python dictionary | 1667.5 | 6.85 | 0 / 41,839 |
| 8 | SQLite | 408.3 | 85.21 | 0 / 9,932 |
| 8 | SQLite + Redis | 407.7 | 83.55 | 0 / 9,872 |
| 32 | Python dictionary | 1853.5 | 26.33 | 0 / 46,181 |
| 32 | SQLite | 403.1 | 365.13 | 0 / 9,957 |
| 32 | SQLite + Redis | 416.5 | 341.72 | 0 / 10,274 |
| 64 | Python dictionary | 1617.1 | 120.51 | 0 / 38,528 |
| 64 | SQLite | 405.8 | 588.67 | 0 / 10,018 |
| 64 | SQLite + Redis | 409.1 | 520.66 | 2 / 10,419 |

All 36 trials passed checks that saved row totals matched successful creations and saved clicks matched successful redirects, including warmup. There were 216,983 measured attempts. At 64 concurrent clients, one Redis trial recorded an HTTP `500` from SQLite reporting `database is locked` and a connection read error. The retained results include both failures.

The dictionary had the highest throughput while keeping data in process memory. SQLite provided persistent mappings. Redis and SQLite had similar HTTP throughput in these runs. Every redirect still committed a SQLite click update, so the write path remains a bottleneck to investigate.

### Cache reuse

Across the Redis HTTP trials, including warmup, Redis served 34,977 cache hits and 7,002 misses, an 83.3% cache hit ratio. Cache hits reused redirect mappings without another SQLite mapping lookup. Click updates still went to SQLite, and metadata requests continued to use SQLite directly.

### Mapping lookup experiment

A separate experiment called the existing mapping lookup helper directly, with one caller and three trials of five seconds per setup. All 1,000 mappings were read once before timing, giving Redis a warm cache. The test excluded HTTP handling, redirect responses, and click writes. Timing included Python loop work and validation of each returned mapping.

| Storage | Mapping lookups/second | Mean time per lookup (microseconds) |
| --- | ---: | ---: |
| Python dictionary | 1,098,939.3 | 0.91 |
| SQLite | 19,501.5 | 51.28 |
| SQLite + Redis, warm cache | 13,958.7 | 71.64 |

These values measure function lookups per second. They are a different measurement from the HTTP results above. All nine lookup trials had zero errors and left rows and click counts unchanged. SQLite reads were already cheap for this small local dataset; the Redis call and cached JSON handling did not improve lookup speed in this environment.

### Scope of the results

These short local runs compare the supplied configurations. They do not establish maximum user capacity, sustained production throughput, or behavior with multiple API workers. Sixty-four concurrent clients was the largest tested load, not a maximum number of people the service supports. A user capacity estimate also needs a request frequency, a response time target, and an error target.

The dictionary loses its data when the process stops and normally has a separate copy in each API worker. SQLite workers on one host can use the same database file, and Redis provides a shared cache server. These differences in persistence and shared state are separate from the measured request rates.

### Repeating the benchmarks

Run these commands from the project folder in Linux or WSL. Use a new output directory for each run:

```bash
.venv/bin/python -m pip install -r benchmarks/requirements.txt
.venv/bin/python benchmarks/run.py --output benchmarks/results/new-http-run --concurrency 1 8 32 64 --repeats 3 --seconds 8 --warmup 2
.venv/bin/python benchmarks/summarize.py benchmarks/results/new-http-run
.venv/bin/python benchmarks/lookup.py --output benchmarks/results/new-lookup-run --seconds 5 --repeats 3
```

The runner starts its own Redis server on an unused localhost port and uses temporary SQLite databases. It does not use the application's normal database or Redis instance. See the [benchmark instructions](benchmarks/README.md) for dependencies and isolation details.

The [full HTTP results](benchmarks/results/2026-10-23/summary.md) contain throughput ranges and p50, p95, and p99 values. The [lookup results](benchmarks/results/2026-10-23-lookup/summary.md) describe the supplementary experiment. Their folders include raw trial JSON and run settings; the HTTP results also retain the server error log.

## Files

| File | Role |
| --- | --- |
| `sniplinkLearning_Uv.py` | Request validation, routes, code generation, and redirect handling. |
| `storage_practice.py` | SQLite schema setup and database operations. |
| `expiry_practice.py` | Timestamp and expiry calculations. |
| `cache_practice.py` | Redis operations, cached data validation, and cache TTL calculation. |
| `conftest.py` | Shared fake Redis fixtures. |
| `test_api.py` | API behavior and integration tests. |
| `test_storage.py` | Database operation tests. |
| `test_cache.py` | Cache behavior and TTL tests. |
| `benchmarks/` | HTTP benchmark scripts, reproduction instructions, and recorded results. |
| `requirements.txt` | Runtime dependencies. |
| `requirements-dev.txt` | Runtime and test dependencies. |
| `.gitignore` | Excludes local databases, environments, caches, and personal artifacts. |
