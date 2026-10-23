# HTTP benchmark results

Measured on 2026-10-23T17:11:56.537904+00:00.

Requests/s and latency percentiles are medians of the repeated trials in each row. Run range is the lowest and highest successful throughput across those trials. Errors and requests are totals across measured phases. Latency samples include failed attempts; requests/s counts successful responses. Timing includes draining the requests started before the measurement deadline.

| Concurrent clients | Storage | Requests/s | Run range | p50 ms | p95 ms | p99 ms | Errors / requests |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Python dictionary | 658.2 | 598.9 to 663.5 | 1.45 | 1.89 | 2.28 | 0 / 15,366 |
| 1 | SQLite | 309.4 | 301.8 to 314.0 | 3.13 | 3.86 | 5.38 | 0 / 7,404 |
| 1 | SQLite + Redis | 303.2 | 290.7 to 305.1 | 3.25 | 4.03 | 5.01 | 0 / 7,193 |
| 8 | Python dictionary | 1667.5 | 1635.8 to 1923.9 | 4.77 | 6.85 | 8.02 | 0 / 41,839 |
| 8 | SQLite | 408.3 | 405.1 to 410.8 | 5.07 | 85.21 | 236.40 | 0 / 9,932 |
| 8 | SQLite + Redis | 407.7 | 388.8 to 424.9 | 5.29 | 83.55 | 235.03 | 0 / 9,872 |
| 32 | Python dictionary | 1853.5 | 1803.4 to 2107.8 | 16.66 | 26.33 | 39.77 | 0 / 46,181 |
| 32 | SQLite | 403.1 | 397.0 to 416.4 | 12.64 | 365.13 | 891.19 | 0 / 9,957 |
| 32 | SQLite + Redis | 416.5 | 401.8 to 421.7 | 11.31 | 341.72 | 1036.28 | 0 / 10,274 |
| 64 | Python dictionary | 1617.1 | 1545.6 to 1635.0 | 22.05 | 120.51 | 189.91 | 0 / 38,528 |
| 64 | SQLite | 405.8 | 394.5 to 406.6 | 67.10 | 588.67 | 1289.22 | 0 / 10,018 |
| 64 | SQLite + Redis | 409.1 | 407.0 to 414.5 | 70.61 | 520.66 | 1242.12 | 2 / 10,419 |

All 36 trials passed row and click conservation checks. Measured requests: 216,983. Measured errors: 2.
