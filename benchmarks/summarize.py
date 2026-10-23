"""Generate tables from raw trials without discarding slow runs or errors."""

import argparse
import csv
import json
from pathlib import Path
from statistics import median

LABELS = {"dict": "Python dictionary", "sqlite": "SQLite", "redis": "SQLite + Redis"}


def summarize(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    expected = len(manifest["config"]["modes"]) * len(manifest["config"]["concurrency"]) * manifest["config"]["repeats"]
    if len(manifest["trials"]) != expected or "finished_at_utc" not in manifest:
        raise RuntimeError("The matrix is incomplete")
    trials = [json.loads((folder / item["file"]).read_text(encoding="utf-8"))
              for item in manifest["trials"]]
    if not all(trial["integrity"]["passed"] for trial in trials):
        raise RuntimeError("A trial failed its state checks")
    rows = []
    for concurrency in sorted(manifest["config"]["concurrency"]):
        for mode in manifest["config"]["modes"]:
            group = [trial for trial in trials if trial["mode"] == mode and trial["concurrency"] == concurrency]
            if len(group) != manifest["config"]["repeats"]:
                raise RuntimeError("Missing repeated trial")
            measured = [trial["measure"] for trial in group]
            rps = [item["successful_rps"] for item in measured]
            row = {
                "concurrent_clients": concurrency, "storage": LABELS[mode], "mode": mode,
                "repeats": len(group), "median_successful_rps": median(rps),
                "min_successful_rps": min(rps), "max_successful_rps": max(rps),
                "median_p50_ms": median(item["p50_ms"] for item in measured),
                "median_p95_ms": median(item["p95_ms"] for item in measured),
                "median_p99_ms": median(item["p99_ms"] for item in measured),
                "total_requests": sum(item["requests"] for item in measured),
                "total_errors": sum(sum(item["errors"].values()) for item in measured),
                "median_measured_seconds_including_drain": median(item["elapsed_seconds"] for item in measured),
                "median_client_cpu_seconds": median(item["client_cpu_seconds"] for item in measured),
                "redis_warmup_and_measure_hits": sum(item["redis_stats_warmup_and_measure"]["keyspace_hits"] for item in group),
                "redis_warmup_and_measure_misses": sum(item["redis_stats_warmup_and_measure"]["keyspace_misses"] for item in group),
            }
            row["error_percent"] = row["total_errors"] / row["total_requests"] * 100
            rows.append(row)
    with (folder / "summary.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = ["| Concurrent clients | Storage | Requests/s | Run range | p50 ms | p95 ms | p99 ms | Errors / requests |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        table.append(
            f"| {row['concurrent_clients']} | {row['storage']} | {row['median_successful_rps']:.1f} | "
            f"{row['min_successful_rps']:.1f} to {row['max_successful_rps']:.1f} | "
            f"{row['median_p50_ms']:.2f} | {row['median_p95_ms']:.2f} | {row['median_p99_ms']:.2f} | "
            f"{row['total_errors']} / {row['total_requests']:,} |")
    (folder / "summary.md").write_text(
        "# HTTP benchmark results\n\n"
        + f"Measured on {manifest['environment']['recorded_at_utc']}.\n\n"
        + "Requests/s and latency percentiles are medians of the repeated trials in each row. "
        + "Run range is the lowest and highest successful throughput across those trials. "
        + "Errors and requests are totals across measured phases. "
        + "Latency samples include failed attempts; requests/s counts successful responses. "
        + "Timing includes draining the requests started before the measurement deadline.\n\n"
        + "\n".join(table) + "\n\n"
        + f"All {len(trials)} trials passed row and click conservation checks. "
        + f"Measured requests: {sum(row['total_requests'] for row in rows):,}. "
        + f"Measured errors: {sum(row['total_errors'] for row in rows):,}.\n",
        encoding="utf-8",
    )
    print((folder / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    summarize(parser.parse_args().folder)
