# Mapping lookup experiment

This calls the existing find_link_with_cache helper directly. It excludes HTTP, redirect responses and SQLite click writes. All 1000 mappings are read once before timing, so Redis begins with a warm cache. Each case uses one caller, the same seeded sequence and three repeated trials of five seconds by default. Results are medians across trials. Timing includes Python loop work and result validation. The raw JSON includes batch timings and counts of actual storage helper calls.

| Storage | Successful lookups/s | Mean microseconds/lookup | Errors |
| --- | ---: | ---: | ---: |
| Python dictionary | 1,098,939.3 | 0.91 | 0 |
| SQLite | 19,501.5 | 51.28 | 0 |
| SQLite + Redis, warm cache | 13,958.7 | 71.64 | 0 |

These are mapping lookups per second, not HTTP requests per second or maximum users. The original mixed HTTP benchmark remains the measure of the full API.

To repeat this experiment from the project root:

```bash
.venv/bin/python benchmarks/lookup.py --output benchmarks/results/new-lookup-run --seconds 5 --repeats 3
```

Dependency setup and isolation details are in [the benchmark instructions](../../README.md).
