"""Run isolated dictionary, SQLite and SQLite + real Redis HTTP trials.

Run from the project root. This starts and stops its own Redis server on a
free localhost port. It never connects to the application's normal Redis or
uses its normal database. Trial databases and process logs are temporary.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx
from redis import Redis

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = ("sniplinkLearning_Uv.py", "storage_practice.py",
                "cache_practice.py", "expiry_practice.py")


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def locate_redis(explicit_path):
    if explicit_path:
        return str(Path(explicit_path).resolve())
    on_path = shutil.which("redis-server")
    if on_path:
        return on_path
    spec = importlib.util.find_spec("redislite")
    if spec and spec.origin:
        bundled = Path(spec.origin).parent / "bin" / "redis-server"
        if bundled.is_file():
            return str(bundled)
    raise RuntimeError("Install redis-server or redislite, or pass --redis-server /path/to/redis-server")


def environment(redis_binary):
    def read_optional(path):
        source = Path(path)
        return source.read_text().strip() if source.is_file() else None

    return {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cpu_quota": read_optional("/sys/fs/cgroup/cpu.max"),
        "memory_limit_bytes": read_optional("/sys/fs/cgroup/memory.max"),
        "sqlite": sqlite3.sqlite_version,
        "packages": {package: importlib.metadata.version(package) for package in
                     ("fastapi", "pydantic", "uvicorn", "httpx", "redis")},
        "redis_server": subprocess.check_output([redis_binary, "--version"], text=True).strip(),
        "redis_binary_sha256": hashlib.sha256(Path(redis_binary).read_bytes()).hexdigest(),
        "filesystem": subprocess.check_output(
            ["stat", "-f", "-c", "%T", str(ROOT)], text=True).strip() if shutil.which("stat") else None,
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in SOURCE_NAMES},
    }


def wait_healthy(process, client):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("API process exited during startup")
        try:
            if client.get("/health").json() == {"status": "ok"}:
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.05)
    raise RuntimeError("API startup timed out")


def preflight(client, seed_count):
    code = "benchmark_probe"
    url = "https://example.com/probe"
    created = client.post("/links", json={"short_code": code, "original_url": url})
    assert created.status_code == 201, created.text
    assert created.json()["expires_at"] is None
    assert client.post("/links", json={"short_code": code, "original_url": url}).status_code == 409
    lookup = client.get(f"/links/{code}")
    assert lookup.json() == {"short_code": code, "original_url": url}
    redirected = client.get(f"/r/{code}")
    assert redirected.status_code == 302 and redirected.headers["location"] == url
    assert client.get(f"/links/{code}/stats").json()["count"] == 1
    assert client.delete(f"/links/{code}").status_code == 200
    assert client.get(f"/r/{code}").status_code == 404
    generated = client.post("/links", json={"original_url": url})
    assert generated.status_code == 201
    assert client.delete(f"/links/{generated.json()['short_code']}").status_code == 200
    state = client.get("/_benchmark/state").json()
    assert state["rows"] == seed_count and state["clicks"] == 0, state
    return state


def run_trial(mode, concurrency, repeat, args, work, redis_port, redis_client):
    trial = f"{mode}_c{concurrency:03d}_r{repeat}"
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(SNIP_BENCH_MODE=mode, SNIP_BENCH_SEEDS=str(args.seed_count),
               SNIP_BENCH_DB=str(work / f"{trial}.db"),
               SNIP_BENCH_REDIS_PORT=str(redis_port), PYTHONUNBUFFERED="1")
    api_process = None
    output_path = args.output / f"{trial}.json"
    try:
        # This client points only to the server started by this runner.
        redis_client.flushdb()
        redis_client.config_resetstat()
        with (work / f"{trial}.api.log").open("w") as api_log:
            api_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "benchmarks.server:app", "--host", "127.0.0.1",
                 "--port", str(port), "--workers", "1", "--loop", "asyncio", "--http", "h11",
                 "--no-access-log", "--log-level", "error"],
                cwd=ROOT, env=env, stdout=api_log, stderr=subprocess.STDOUT,
            )
            with httpx.Client(base_url=url, timeout=30, follow_redirects=False, trust_env=False) as client:
                wait_healthy(api_process, client)
                before = preflight(client, args.seed_count)
                redis_client.flushdb()
                redis_client.config_resetstat()
                with (work / f"{trial}.load.log").open("w") as load_log:
                    subprocess.run(
                        [sys.executable, str(ROOT / "benchmarks" / "load.py"),
                         "--url", url, "--concurrency", str(concurrency),
                         "--seconds", str(args.seconds), "--warmup", str(args.warmup),
                         "--seed", str(args.seed + repeat), "--seed-count", str(args.seed_count),
                         "--processes", str(args.client_processes), "--output", str(output_path)],
                        cwd=ROOT, env=env, stdout=load_log, stderr=subprocess.STDOUT,
                        check=True, timeout=args.seconds + args.warmup + 150,
                    )
                data = json.loads(output_path.read_text(encoding="utf-8"))
                after = client.get("/_benchmark/state").json()
                expected_rows = args.seed_count + sum(
                    data[phase]["successes"].get("create", 0) for phase in ("warmup", "measure"))
                expected_clicks = sum(data[phase]["successes"].get("redirect", 0)
                                      for phase in ("warmup", "measure"))
                integrity = {"expected_rows": expected_rows, "actual_rows": after["rows"],
                             "expected_clicks": expected_clicks, "actual_clicks": after["clicks"]}
                integrity["passed"] = after["rows"] == expected_rows and after["clicks"] == expected_clicks
                stats = redis_client.info("stats")
                data.update(mode=mode, concurrency=concurrency, repeat=repeat,
                            state_before=before, state_after=after, integrity=integrity,
                            redis_stats_warmup_and_measure={key: stats[key] for key in
                                                          ("keyspace_hits", "keyspace_misses", "total_commands_processed")})
                output_path.write_text(json.dumps(data), encoding="utf-8")
                if not integrity["passed"]:
                    raise RuntimeError(f"State verification failed: {integrity}")
                measured = data["measure"]
                print(f"{trial}: {measured['successful_rps']:.1f} successful req/s, "
                      f"p95 {measured['p95_ms']:.2f} ms, "
                      f"errors {sum(measured['errors'].values())}/{measured['requests']}, state OK", flush=True)
                return {"trial": trial, "mode": mode, "concurrency": concurrency, "repeat": repeat,
                        "file": output_path.name}
    except BaseException:
        for suffix in ("api", "load"):
            log_path = work / f"{trial}.{suffix}.log"
            if log_path.exists():
                print(log_path.read_text(encoding="utf-8")[-6000:], file=sys.stderr)
        raise
    finally:
        stop(api_process)
        api_log_path = work / f"{trial}.api.log"
        if api_log_path.exists() and api_log_path.stat().st_size:
            error_folder = args.output / "server_errors"
            error_folder.mkdir(exist_ok=True)
            shutil.copyfile(api_log_path, error_folder / api_log_path.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-server")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 8, 32, 64])
    parser.add_argument("--modes", choices=["dict", "sqlite", "redis"], nargs="+",
                        default=["dict", "sqlite", "redis"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--warmup", type=float, default=2)
    parser.add_argument("--seed-count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--client-processes", type=int, default=4)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a new or empty output directory so results cannot be overwritten")
    args.output.mkdir(parents=True, exist_ok=True)
    binary = locate_redis(args.redis_server)
    metadata = {"environment": environment(binary),
                "config": vars(args) | {"output": str(args.output)},
                "workload": {"redirect_percent": 90, "lookup_percent": 5, "create_percent": 5,
                             "hot_set_size": 100, "hot_probability": 0.8,
                             "cache_ttl_seconds": 60, "transport": "localhost HTTP/1.1 keepalive",
                             "api_workers": 1, "uvicorn_loop": "asyncio", "uvicorn_http": "h11"},
                "trials": []}
    manifest = args.output / "manifest.json"
    manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    rng = random.Random(args.seed)
    redis_process = None
    with tempfile.TemporaryDirectory(prefix="sniplink_bench_") as temporary:
        work = Path(temporary)
        port = free_port()
        try:
            with (work / "redis.log").open("w") as log:
                redis_process = subprocess.Popen(
                    [binary, "--bind", "127.0.0.1", "--port", str(port), "--save", "",
                     "--appendonly", "no", "--dir", str(work), "--loglevel", "warning"],
                    stdout=log, stderr=subprocess.STDOUT,
                )
                redis_client = Redis(host="127.0.0.1", port=port,
                                     socket_connect_timeout=1, socket_timeout=1)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        if redis_client.ping():
                            break
                    except Exception:
                        if redis_process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Dedicated Redis server could not start")
                        time.sleep(0.05)
                metadata["redis_runtime_version"] = redis_client.info("server")["redis_version"]
                for repeat in range(1, args.repeats + 1):
                    levels = args.concurrency.copy()
                    rng.shuffle(levels)
                    for concurrency in levels:
                        modes = args.modes.copy()
                        rng.shuffle(modes)
                        for mode in modes:
                            metadata["trials"].append(run_trial(mode, concurrency, repeat, args, work,
                                                               port, redis_client))
                            manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        finally:
            stop(redis_process)
    metadata["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Completed {len(metadata['trials'])} trials. Raw results: {args.output}", flush=True)


if __name__ == "__main__":
    main()
