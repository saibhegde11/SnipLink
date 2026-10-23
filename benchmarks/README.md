# Benchmark

This compares three storage setups behind the same FastAPI routes. It sends real HTTP requests over localhost. The Redis case uses a real Redis server over TCP. `fakeredis` is only used by the separate correctness test suite.

The dictionary adapter reconstructs a version that keeps links in a dictionary and uses the current storage interface, including expiry metadata and conditional click updates. It is not an archived copy of the original project. A lock protects the dictionary because the synchronous routes run in worker threads. Dictionary data disappears when the process stops.

The SQLite case uses the project's storage module with cache operations disabled. The Redis case uses both original modules. The API file is unchanged in all cases. The wrapper selects storage before importing the API and adds a state endpoint that is only available during benchmarks.

## Workload

Each trial starts a fresh API process with 1,000 mappings without expiry. Requests are chosen randomly with a fixed seed: 90% redirects, 5% metadata lookups, and 5% creations with unique custom codes. For seeded link selection, 80% of requests choose among 100 hot links and 20% choose among the other 900. New links are not added to the redirect pool during the trial.

This is synthetic traffic. It is not a recorded production traffic trace. Every successful redirect records a click, and every creation uses the normal validation and insertion path. Redirects are not followed, so the test never loads the destination website.

Each concurrent client waits for its response and immediately sends another request. There is no simulated reading time between requests. Concurrency therefore means active load clients with up to one request each in flight. It does not mean registered users or visitors per day. This test also reduces its offered request rate when responses slow down; it is not a fixed arrival rate test.

## Trial settings

The recorded matrix uses 1, 8, 32, and 64 concurrent clients. Each combination runs three times, with two seconds of warmup and eight seconds of measured request starts. Outstanding requests drain before the warmup barrier and after the measurement deadline. Reported throughput divides successful measured requests by the elapsed time including that final drain.

Uvicorn runs one process, without reload or access logging, using asyncio and h11. Its default synchronous route thread limit is unchanged. The load generator uses one process at concurrency 1 and four processes at the higher levels. API, load generator, and Redis share the same machine.

Connections use HTTP/1.1 keepalive. Client timeouts are 30 seconds. Response status codes, redirect destinations, and mapping fields are checked. Failed attempts count toward errors and latency samples. They are not silently discarded. Latency includes HTTP client work and local network transport, rather than timing storage calls alone.

Mode order and concurrency order are shuffled with seed 20261023. Dataset setup, process startup, health checks, and preflight checks are outside the timed phases. Every trial checks duplicate rejection, creation, lookup, redirect, click counting, and deletion before load. Afterward, saved row totals must equal seed rows plus successful warmup and measured creations; click totals must equal successful warmup and measured redirects.

SQLite uses the application's defaults: a new connection per operation, rollback journal mode `delete`, and `synchronous=2` (`FULL`). No WAL, connection pool, batching, or reduced durability settings are added. Redis persistence is disabled because it holds disposable cache entries. The application cache lifetime stays at 60 seconds. Redis hit and miss counters in each raw result cover both warmup and measurement.

## Reproducing the run

The recorded run used Linux and Python 3.12.14. From the project root, create a Python environment and install the benchmark dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r benchmarks/requirements.txt
.venv/bin/python benchmarks/run.py --output benchmarks/results/new-run --concurrency 1 8 32 64 --repeats 3 --seconds 8 --warmup 2
.venv/bin/python benchmarks/summarize.py benchmarks/results/new-run
```

Use a new output directory for every run. The runner refuses to overwrite an existing result set. It creates temporary SQLite databases and starts its own Redis server on an unused localhost port. It stops the processes and removes the temporary databases afterward. It never uses the application's normal database or Redis port.

The recorded Redis server is version 6.2.14, supplied by the `redislite` 6.2.912183 wheel. The runner launches that wheel's actual `redis-server` executable directly. It does not use an in-process Redis substitute. If `redis-server` is already on PATH, that binary takes precedence. To choose a particular build explicitly, add `--redis-server /absolute/path/to/redis-server`. Its version and binary hash are saved in the manifest. Windows users can run this benchmark in WSL.

## Reading the results

The recorded data is in `results/2026-10-23`. `manifest.json` contains versions, source hashes, machine limits, exact settings, and trial order. Every trial JSON contains timing, request counts, statuses, errors, raw latency samples, and state checks. `summary.csv` and `summary.md` are generated directly from those files.

There are 36 completed trials and 216,983 measured attempts. At 32 concurrent clients, median successful throughput was 1,853.5 requests/s for the dictionary, 403.1 for SQLite, and 416.5 for SQLite with Redis. These are measurements at a common load level, not maximum capacities. At this level, the Redis and SQLite throughput ranges overlap. The runs do not establish a large throughput benefit from the cache.

Redis served 34,977 cache hits and 7,002 misses across its trials, including warmup, for a hit ratio of 83.3%. It was being used. However, the API still commits a SQLite click update on every redirect. The cache removes a mapping read and adds a Redis round trip; it does not remove that write.

The first Redis trial at concurrency 64 recorded one HTTP `500` and one HTTP client `ReadError`. The retained API error log in `server_errors` shows `sqlite3.OperationalError: database is locked` in `record_click`. The other measured trials had no errors. All trials passed the final row and click checks.

The summary reports the median throughput and the median of each latency percentile across the three runs. The throughput range shows the lowest and highest repeated run. Error counts combine the measured phases of all three runs. A p95 of 100 ms means 95% of measured attempts in that trial took no more than 100 ms.

These short runs compare the setups on one machine. They do not establish maximum user capacity, long-term stability, performance over the public internet, or behavior across multiple API workers. The dictionary also gives up persistence, so higher throughput alone would not make it an equivalent replacement for SQLite.

## Mapping lookup experiment

A separate experiment calls the existing `find_link_with_cache` helper directly. It excludes HTTP handling, redirects, expiry checks in the redirect handler, and SQLite click updates. It uses the same storage choices as the HTTP wrapper. Each trial reads all 1,000 mappings once before timing, so Redis has a warm cache and SQLite has already accessed every row.

There is one sequential caller. Each case runs three times for five seconds, with mode order shuffled. The same seeded sequence chooses from the 100 hot rows with probability 80% and the other 900 rows with probability 20%. Timing includes the Python loop and validation of every returned mapping. Raw JSON stores timing for batches of 100 lookups. All nine trials had zero errors and left the stored rows and click counts unchanged.

The recorded results are in [results/2026-10-23-lookup](results/2026-10-23-lookup/summary.md). Median throughput was 19,501.5 lookups/s for SQLite and 13,958.7 for SQLite with a warm Redis cache. Redis avoided the timed SQLite mapping reads, but it did not speed up this small local lookup. This outcome is retained alongside the HTTP benchmark.

Run the supplementary experiment from the project root:

```bash
.venv/bin/python benchmarks/lookup.py --output benchmarks/results/new-lookup-run --seconds 5 --repeats 3
```

The runner starts its own Redis server and uses temporary databases. The source API files are unchanged. The supplementary figures measure mapping function calls, so they cannot be substituted for full API throughput or maximum users. This experiment is not evidence that moving click counts out of SQLite would preserve the current durability or stale mapping checks; that would be a separate implementation change.
