"""Measure the existing mapping lookup helper separately from HTTP redirects.

This is a supplementary microbenchmark. It deliberately excludes click writes
to isolate mapping lookup cost. It cannot establish HTTP or user capacity.
The original HTTP benchmark remains the end to end comparison.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
from statistics import median
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redis import Redis
from benchmarks.run import environment, free_port, locate_redis, stop


def child(args):
    os.environ.update(
        SNIP_BENCH_MODE=args.mode,
        SNIP_BENCH_DB=str(args.database),
        SNIP_BENCH_SEEDS="1000",
        SNIP_BENCH_REDIS_PORT=str(args.redis_port),
    )
    # This wrapper selects storage before loading the unchanged API module.
    import benchmarks.server as server
    import sniplinkLearning_Uv as api

    client = Redis(host="127.0.0.1", port=args.redis_port,
                   socket_connect_timeout=1, socket_timeout=1)
    expected = [{"short_code": f"s{i:08d}", "original_url": f"https://example.com/page/{i}",
                 "expires_at": None} for i in range(1000)]
    sql_or_memory_reads = 0
    original_find = api.find_link_details

    def counted_find(code):
        nonlocal sql_or_memory_reads
        sql_or_memory_reads += 1
        return original_find(code)

    api.find_link_details = counted_find
    # Give every case a full untimed pass; Redis consequently has a warm cache.
    for row in expected:
        assert api.find_link_with_cache(row["short_code"]) == row
    sql_or_memory_reads = 0
    client.config_resetstat()
    rng = random.Random(args.seed)
    sequence = [expected[rng.randrange(100) if rng.random() < 0.8
                         else rng.randrange(100, 1000)] for _ in range(20000)]
    lookup = api.find_link_with_cache
    index, operations, errors = 0, 0, 0
    batches = []
    before = server.benchmark_state()
    started = time.perf_counter_ns()
    deadline = started + int(args.seconds * 1_000_000_000)
    while time.perf_counter_ns() < deadline:
        batch_started = time.perf_counter_ns()
        for _ in range(100):
            row = sequence[index]
            index = (index + 1) % len(sequence)
            try:
                if lookup(row["short_code"]) != row:
                    errors += 1
            except Exception:
                errors += 1
            operations += 1
        batches.append([100, time.perf_counter_ns() - batch_started])
    elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
    after = server.benchmark_state()
    stats = client.info("stats")
    result = {
        "mode": args.mode, "repeat": args.repeat, "operations": operations,
        "errors": errors, "elapsed_seconds": elapsed,
        "successful_lookups_per_second": (operations - errors) / elapsed,
        "mean_microseconds_per_attempt": elapsed * 1_000_000 / operations,
        "storage_mapping_reads": sql_or_memory_reads,
        "sqlite_mapping_reads": sql_or_memory_reads if args.mode != "dict" else 0,
        "cache_hits": stats["keyspace_hits"], "cache_misses": stats["keyspace_misses"],
        "state_before": before, "state_after": after,
        "batches_count_and_elapsed_ns": batches,
    }
    result["state_unchanged"] = before == after and after["rows"] == 1000 and after["clicks"] == 0
    assert result["state_unchanged"], result
    args.output.write_text(json.dumps(result), encoding="utf-8")


def main(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError("Use a new output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    binary = locate_redis(args.redis_server)
    manifest = {
        "environment": environment(binary),
        "scope": "Mapping helper only, no HTTP, no click writes, one sequential caller",
        "dataset": {"rows": 1000, "hot_rows": 100, "hot_probability": 0.8},
        "warmup": "One complete untimed lookup pass over all 1000 rows in every trial",
        "requested_seconds_per_trial": args.seconds,
        "repeats": args.repeats, "seed": args.seed,
        "cache_ttl_seconds": 60,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trials": [],
    }
    rng = random.Random(args.seed)
    redis_process = None
    with tempfile.TemporaryDirectory(prefix="sniplink_lookup_") as temporary:
        work = Path(temporary)
        port = free_port()
        try:
            with (work / "redis.log").open("w") as log:
                redis_process = subprocess.Popen(
                    [binary, "--bind", "127.0.0.1", "--port", str(port), "--save", "",
                     "--appendonly", "no", "--dir", str(work), "--loglevel", "warning"],
                    stdout=log, stderr=subprocess.STDOUT,
                )
                client = Redis(host="127.0.0.1", port=port,
                               socket_connect_timeout=1, socket_timeout=1)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        if client.ping():
                            break
                    except Exception:
                        if redis_process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Could not start dedicated Redis")
                        time.sleep(0.05)
                for repeat in range(1, args.repeats + 1):
                    modes = ["dict", "sqlite", "redis"]
                    rng.shuffle(modes)
                    for mode in modes:
                        client.flushdb()
                        path = args.output / f"{mode}_r{repeat}.json"
                        subprocess.run(
                            [sys.executable, str(Path(__file__).resolve()), "--child", "--mode", mode,
                             "--redis-port", str(port), "--database", str(work / f"{mode}_{repeat}.db"),
                             "--output", str(path), "--seconds", str(args.seconds),
                             "--seed", str(args.seed + repeat), "--repeat", str(repeat)],
                            cwd=ROOT, check=True, timeout=args.seconds + 45,
                        )
                        data = json.loads(path.read_text(encoding="utf-8"))
                        manifest["trials"].append(path.name)
                        print(f"{mode} r{repeat}: {data['successful_lookups_per_second']:.1f} lookups/s, "
                              f"errors {data['errors']}, SQLite mapping reads {data['sqlite_mapping_reads']}",
                              flush=True)
        finally:
            stop(redis_process)
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    labels = {"dict": "Python dictionary", "sqlite": "SQLite", "redis": "SQLite + Redis, warm cache"}
    rows = []
    for mode in labels:
        group = [json.loads((args.output / name).read_text())
                 for name in manifest["trials"] if name.startswith(mode + "_")]
        rows.append({"mode": mode, "storage": labels[mode],
                     "median_successful_lookups_per_second": median(d["successful_lookups_per_second"] for d in group),
                     "median_mean_microseconds_per_attempt": median(d["mean_microseconds_per_attempt"] for d in group),
                     "errors": sum(d["errors"] for d in group),
                     "sqlite_mapping_reads": sum(d["sqlite_mapping_reads"] for d in group),
                     "total_attempts": sum(d["operations"] for d in group)})
    (args.output / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    table = ["| Storage | Successful lookups/s | Mean microseconds/lookup | Errors |",
             "| --- | ---: | ---: | ---: |"]
    for row in rows:
        table.append(f"| {row['storage']} | {row['median_successful_lookups_per_second']:,.1f} | "
                     f"{row['median_mean_microseconds_per_attempt']:.2f} | {row['errors']} |")
    report = ("# Mapping lookup experiment\n\n"
              "This calls the existing find_link_with_cache helper directly. It excludes HTTP, "
              "redirect responses and SQLite click writes. All 1000 mappings are read once before timing, "
              "so Redis begins with a warm cache. Each case uses one caller, the same seeded sequence "
              "and three repeated trials of five seconds by default. Results are medians across trials. "
              "Timing includes Python loop work and result validation. The raw JSON includes batch timings "
              "and counts of actual storage helper calls.\n\n" + "\n".join(table) + "\n\n"
              "These are mapping lookups per second, not HTTP requests per second or maximum users. "
              "The original mixed HTTP benchmark remains the measure of the full API.\n")
    (args.output / "summary.md").write_text(report, encoding="utf-8")
    print(report, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--redis-server")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mode", choices=["dict", "sqlite", "redis"])
    parser.add_argument("--redis-port", type=int)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    parsed = parser.parse_args()
    parsed.output = parsed.output.resolve()
    if parsed.seconds <= 0 or parsed.repeats < 1:
        parser.error("Duration and repeats must be positive")
    if parsed.child:
        child(parsed)
    else:
        main(parsed)
