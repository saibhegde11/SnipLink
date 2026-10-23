"""Closed-loop HTTP load generator, using up to four client processes.

Each simulated client waits for its response before sending its next request.
Warmup drains before a process barrier starts the measured phase. Connections
are kept alive between phases. Latency includes failed requests.
"""

import argparse
import asyncio
from collections import Counter
import json
import math
import multiprocessing as mp
from pathlib import Path
import random
import time
import traceback

import httpx


def percentile(values, percentile_value):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentile_value / 100) - 1)]


def empty_metrics():
    return {"latency_ms": [], "statuses": Counter(), "operations": Counter(),
            "successes": Counter(), "errors": Counter(), "error_examples": []}


async def phase(client, workers, seconds, phase_name, seed, seed_count):
    metrics = empty_metrics()
    started = time.monotonic()
    deadline = started + seconds
    cpu_started = time.process_time()

    async def send(worker):
        # Sequence numbers live across warmup and measurement.
        identity, sequence = worker
        rng = random.Random(seed + identity * 100003 + (phase_name == "measure"))
        while time.monotonic() < deadline:
            selection = rng.randrange(100)
            item = (rng.randrange(100) if rng.random() < 0.8
                    else rng.randrange(100, seed_count))
            code = f"s{item:08d}"
            url = f"https://example.com/page/{item}"
            body = None
            if selection < 90:
                operation, method, path, expected_status = "redirect", "GET", f"/r/{code}", 302
            elif selection < 95:
                operation, method, path, expected_status = "lookup", "GET", f"/links/{code}", 200
            else:
                operation, method, path, expected_status = "create", "POST", "/links", 201
                code = f"n{identity:03x}{sequence:010x}"
                sequence += 1
                body = {"short_code": code, "original_url": url}
            request_started = time.perf_counter()
            problem = None
            status = None
            try:
                response = await client.request(method, path, json=body)
                status = response.status_code
                if status != expected_status:
                    problem = f"HTTP {status}"
                elif operation == "redirect":
                    if response.headers.get("location") != url:
                        problem = "wrong redirect destination"
                else:
                    data = response.json()
                    if data.get("short_code") != code or data.get("original_url") != url:
                        problem = "wrong response mapping"
                    if operation == "create" and data.get("expires_at") is not None:
                        problem = "unexpected expiry"
            except Exception as error:
                problem = type(error).__name__
            elapsed_ms = (time.perf_counter() - request_started) * 1000
            metrics["latency_ms"].append(round(elapsed_ms, 6))
            metrics["statuses"][str(status) if status is not None else "transport_error"] += 1
            metrics["operations"][operation] += 1
            if problem is None:
                metrics["successes"][operation] += 1
            else:
                metrics["errors"][problem] += 1
                if len(metrics["error_examples"]) < 5:
                    metrics["error_examples"].append({"operation": operation, "problem": problem})
        worker[1] = sequence

    await asyncio.gather(*(send(worker) for worker in workers))
    metrics.update(started=started, ended=time.monotonic(),
                   cpu_seconds=time.process_time() - cpu_started)
    return metrics


def child_process(index, identities, config, barrier, result_path):
    async def run():
        workers = [[identity, 0] for identity in identities]
        limits = httpx.Limits(max_connections=len(workers),
                             max_keepalive_connections=len(workers),
                             keepalive_expiry=60)
        async with httpx.AsyncClient(base_url=config["url"], limits=limits,
                                    timeout=30, follow_redirects=False,
                                    trust_env=False) as client:
            barrier.wait(timeout=90)
            warmup = await phase(client, workers, config["warmup"], "warmup",
                                 config["seed"], config["seed_count"])
            # All processes finish outstanding warmup requests before timing.
            barrier.wait(timeout=90)
            measured = await phase(client, workers, config["seconds"], "measure",
                                   config["seed"], config["seed_count"])
        return {"index": index, "warmup": warmup, "measure": measured}

    try:
        result = asyncio.run(run())
    except BaseException:
        result = {"fatal_error": traceback.format_exc()}
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")


def combine(processes, phase_name):
    combined = empty_metrics()
    for process in processes:
        metrics = process[phase_name]
        combined["latency_ms"].extend(metrics["latency_ms"])
        for key in ("statuses", "operations", "successes", "errors"):
            combined[key].update(metrics[key])
        combined["error_examples"].extend(metrics["error_examples"])
    elapsed = max(p[phase_name]["ended"] for p in processes) - min(
        p[phase_name]["started"] for p in processes)
    requests = len(combined["latency_ms"])
    successful = sum(combined["successes"].values())
    combined.update(
        elapsed_seconds=elapsed, requests=requests, successful_requests=successful,
        successful_rps=successful / elapsed, attempted_rps=requests / elapsed,
        error_rate=(requests - successful) / requests if requests else 0,
        p50_ms=percentile(combined["latency_ms"], 50),
        p95_ms=percentile(combined["latency_ms"], 95),
        p99_ms=percentile(combined["latency_ms"], 99),
        client_cpu_seconds=sum(p[phase_name]["cpu_seconds"] for p in processes),
        process_elapsed_seconds=[p[phase_name]["ended"] - p[phase_name]["started"]
                                 for p in processes],
    )
    return combined


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--warmup", type=float, default=2)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--seed-count", type=int, default=1000)
    parser.add_argument("--processes", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seed_count < 101 or args.concurrency < 1 or args.seconds <= 0 or args.warmup <= 0:
        parser.error("Need at least 101 seed rows, positive times and concurrency")
    count = min(args.processes, args.concurrency)
    context = mp.get_context("spawn")
    barrier = context.Barrier(count)
    children = []
    partial_paths = []
    config = vars(args) | {"output": str(args.output)}
    try:
        for index in range(count):
            path = args.output.with_suffix(f".part{index}.json")
            partial_paths.append(path)
            identities = list(range(index, args.concurrency, count))
            child = context.Process(target=child_process,
                                    args=(index, identities, config, barrier, str(path)))
            children.append(child)
            child.start()
        deadline = time.monotonic() + args.seconds + args.warmup + 120
        for child in children:
            child.join(timeout=max(0, deadline - time.monotonic()))
            if child.is_alive() or child.exitcode != 0:
                raise RuntimeError(f"Load process failed or timed out: {child.pid}")
        processes = [json.loads(path.read_text(encoding="utf-8")) for path in partial_paths]
        for process in processes:
            if "fatal_error" in process:
                raise RuntimeError(process["fatal_error"])
        result = {"config": config, "client_processes": count,
                  "warmup": combine(processes, "warmup"),
                  "measure": combine(processes, "measure")}
        args.output.write_text(json.dumps(result), encoding="utf-8")
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(timeout=5)
        for path in partial_paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
