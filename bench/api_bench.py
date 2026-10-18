"""API benchmark on a real database: every §10 target, measured over HTTP (design §10).

    uv run python bench/api_bench.py                    # data/trials.db, with the index
    uv run python bench/api_bench.py --compare-sql      # also the filtered requests in SQLite alone
    uv run python bench/api_bench.py --data-dir /path   # another data directory

It runs the app in uvicorn on a free port, as ``tri-al serve`` does, waits for the trial
index, then times each kind of request. Times are server times from the ``Server-Timing``
header (until the response starts, gzip included); client times over loopback add about a
millisecond. Filtered requests and searches are cold: each filter or query is asked for
once, so nothing comes from the result cache.
"""

import argparse
import platform
import random
import socket
import statistics
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import httpx2 as httpx
import uvicorn
from fastapi import FastAPI

from tri_al.api import create_app
from tri_al.config import load_config
from tri_al.plugins import load_plugins
from tri_al.stats import TrialIndex
from tri_al.storage import SQLiteStorage

TARGETS = {
    "precomputed": 20.0,
    "dashboard": 50.0,
    "filtered": 300.0,
    "detail": 30.0,
    "search": 150.0,
}

FILTERS: list[list[tuple[str, str]]] = [
    [("status", "RECRUITING")],
    [("status", "COMPLETED")],
    [("phase", "PHASE3")],
    [("phase", "PHASE2"), ("phase", "PHASE3")],
    [("study_type", "INTERVENTIONAL")],
    [("sponsor_class", "INDUSTRY")],
    [("has_results", "true")],
    [("countries", "US")],
    [("countries", "CN")],
    [("countries", "DE"), ("countries", "FR")],
    [("conditions", "Alzheimer Disease")],
    [("conditions", "Breast Cancer")],
    [("conditions", "Healthy")],
    [("mesh", "D003704")],  # Dementia, with narrower terms
    [("mesh", "D009369")],  # Neoplasms: about a quarter of all trials
    [("interventions", "Placebo")],
    [("interventions", "Donepezil")],
    [("intervention_types", "DRUG")],
    [("intervention_types", "BEHAVIORAL")],
    [("sponsors", "National Cancer Institute (NCI)")],
    [("start", "2020..2023")],
    [("last_update", "2026..")],
    [("enrollment", "1000..")],
    [("q", "alzheimer")],
    [("q", "cancer")],
    [("q", "study")],  # in 94% of trials
    [("status", "RECRUITING"), ("countries", "US")],
    [("conditions", "Alzheimer Disease"), ("status", "RECRUITING"), ("phase", "PHASE3")],
    [("intervention_types", "DRUG"), ("sponsor_class", "INDUSTRY"), ("has_results", "true")],
    [("q", "amyloid"), ("start", "2015..")],
    [("countries", "US"), ("phase", "PHASE3"), ("status", "COMPLETED"), ("has_results", "true")],
    [("mesh", "D000544"), ("countries", "JP")],
]

QUERIES = [
    "donepezil",
    "lecanemab",
    "aducanumab amyloid",
    "tau pet",
    "alzheimer",
    "mild cognitive impairment",
    "dementia caregivers",
    "parkinson",
    "breast cancer",
    "lung cancer immunotherapy",
    "pembrolizumab",
    "covid-19 vaccine",
    "diabetes",
    "insulin",
    "obesity semaglutide",
    "depression",
    "hypertension",
    "asthma children",
    "stroke rehabilitation",
    "hiv",
    "pain",
    "exercise",
    "sleep",
    "cancer",
    "placebo",
    "randomized",
    "safety",
    "patients",
    "study",
    "the",
]


@contextmanager
def running(app: FastAPI) -> Iterator[str]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


class Timer:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def get(
        self,
        path: str,
        params: Sequence[tuple[str, str]] = (),
        headers: dict[str, str] | None = None,
    ) -> tuple[float, float, httpx.Response]:
        """``(server ms, client ms, response)``."""
        started = time.perf_counter()
        response = self.client.get(path, params=list(params), headers=headers)
        client_ms = (time.perf_counter() - started) * 1000
        if response.status_code not in (200, 304):
            raise RuntimeError(f"{path} {params}: {response.status_code} {response.text[:200]}")
        server_ms = float(response.headers["server-timing"].split("dur=")[1])
        return server_ms, client_ms, response


def p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def summary(values: Sequence[float]) -> str:
    return (
        f"{statistics.median(values):.1f} ms median, {p95(values):.1f} ms p95, "
        f"{max(values):.1f} ms max (n={len(values)})"
    )


def describe(params: Sequence[tuple[str, str]]) -> str:
    return " & ".join(f"{key}={value}" for key, value in params)


def bench_filtered(timer: Timer, charts: list[str], label: str) -> dict[str, list[float]]:
    times: dict[str, list[float]] = {"list": [], "facets": [], "chart": []}
    slowest: list[tuple[float, str]] = []
    for params in FILTERS:
        list_ms, _, response = timer.get("/api/trials", params)
        times["list"].append(list_ms)
        facets_ms, _, _ = timer.get("/api/facets", params)
        times["facets"].append(facets_ms)
        chart_ms = [timer.get(f"/api/stats/{chart}", params)[0] for chart in charts]
        times["chart"] += chart_ms
        total = response.json()["total"]
        slowest.append(
            (max(list_ms, facets_ms, *chart_ms), f"{describe(params)} ({total:,} trials)")
        )
        print(
            f"  {label}: {describe(params):70} {total:>8,} trials  list {list_ms:6.1f}  "
            f"facets {facets_ms:6.1f}  charts max {max(chart_ms):6.1f} ms",
            file=sys.stderr,
        )
    times["slowest"] = [ms for ms, _ in sorted(slowest, reverse=True)[:3]]
    print(f"  {label} slowest: {sorted(slowest, reverse=True)[:3]}", file=sys.stderr)
    return times


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=30)
    parser.add_argument(
        "--compare-sql", action="store_true", help="also time filters without the index"
    )
    args = parser.parse_args()

    config = load_config()
    if args.data_dir is not None:
        config = config.model_copy(
            update={"data": config.data.model_copy(update={"dir": args.data_dir})}
        )
    loaded = load_plugins(config)
    trials_db = config.data.trials_db
    rows: list[tuple[str, str, str]] = []

    with SQLiteStorage.attach(trials_db) as storage, storage.read() as reader:
        started = time.perf_counter()
        index = TrialIndex.build(reader.connection, reader.data_version())
        build = time.perf_counter() - started
        trials = index.trials
        source_ids = [
            sid
            for (sid,) in reader.connection.exec_driver_sql("SELECT source_id FROM trials").all()
        ]
    rows.append(
        (
            "Trial index: build",
            f"{build:.2f} s for {trials:,} trials, {index.nbytes / 1e6:.0f} MB",
            "",
        )
    )
    del index

    app = create_app(config, loaded)
    state = app.state.tri_al
    with running(app) as url, httpx.Client(base_url=url, timeout=60) as client:
        timer = Timer(client)
        with state.read() as reader:
            state.stats().wait_for_index(reader.data_version())
        dashboard = timer.get("/api/dashboard")[2].json()
        charts = [chart["id"] for chart in dashboard["charts"]]

        # Precomputed charts, one at a time.
        precomputed = [
            timer.get(f"/api/stats/{chart}")[0] for _ in range(args.repeat) for chart in charts
        ]
        rows.append(
            (
                "`GET /api/stats/{id}`, precomputed",
                summary(precomputed),
                f"p95 < {TARGETS['precomputed']:.0f} ms",
            )
        )

        # The whole dashboard: the manifest and every chart, one after another.
        passes = []
        for _ in range(args.repeat):
            passes.append(
                timer.get("/api/dashboard")[0]
                + sum(timer.get(f"/api/stats/{c}")[0] for c in charts)
            )
        rows.append(
            (
                f"Whole dashboard (manifest + {len(charts)} charts), server time",
                summary(passes),
                f"< {TARGETS['dashboard']:.0f} ms",
            )
        )

        # 304s.
        etag = timer.get("/api/trials")[2].headers["etag"]
        not_modified = [
            timer.get("/api/trials", headers={"If-None-Match": etag})[0] for _ in range(args.repeat)
        ]
        rows.append(("Unchanged request (304)", summary(not_modified), ""))

        # Filtered: each filter once, cold.
        filtered = bench_filtered(timer, charts, "index")
        everything = filtered["list"] + filtered["facets"] + filtered["chart"]
        rows.append(
            (
                f"Filtered list (first page + total), {len(FILTERS)} filters",
                summary(filtered["list"]),
                "",
            )
        )
        rows.append(("Filtered facets (all 10)", summary(filtered["facets"]), ""))
        rows.append((f"Filtered chart ({len(charts)} per filter)", summary(filtered["chart"]), ""))
        rows.append(
            (
                "Filtered list, facets or chart, together",
                summary(everything),
                f"p95 < {TARGETS['filtered']:.0f} ms",
            )
        )

        # Paging deep into a broad list.
        cursor = None
        pages = []
        for _ in range(20):
            params = [("status", "COMPLETED"), ("limit", "50")] + (
                [("cursor", cursor)] if cursor else []
            )
            ms, _, response = timer.get("/api/trials", params)
            pages.append(ms)
            cursor = response.json()["next_cursor"]
        rows.append(("Paging: 20 pages of 50 through completed trials", summary(pages), ""))

        # Detail.
        rng = random.Random(4)
        detail = [timer.get(f"/api/trials/{sid}")[0] for sid in rng.sample(source_ids, 200)]
        rows.append(
            (
                "`GET /api/trials/{id}`, 200 random trials",
                summary(detail),
                f"p95 < {TARGETS['detail']:.0f} ms",
            )
        )

        # Search: each query once, cold.
        searches = []
        for query in QUERIES:
            ms, _, response = timer.get("/api/search", [("q", query)])
            searches.append(ms)
            result = response.json()
            print(
                f"  search {query!r:30} {ms:6.1f} ms  candidates {result['candidates']:>6}"
                f"{' (capped)' if result['capped'] else ''}",
                file=sys.stderr,
            )
        rows.append(
            (
                f"`GET /api/search`, {len(QUERIES)} queries from rare to everywhere",
                summary(searches),
                f"p95 < {TARGETS['search']:.0f} ms",
            )
        )

    if args.compare_sql:
        sql_app = create_app(config, loaded, use_index=False)
        with running(sql_app) as url, httpx.Client(base_url=url, timeout=300) as client:
            sql = bench_filtered(Timer(client), charts, "sql")
        everything = sql["list"] + sql["facets"] + sql["chart"]
        rows.append(
            (
                "Same filters in SQLite alone (no index): list, facets or chart",
                summary(everything),
                "for comparison",
            )
        )
        rows.append(("  of which facets (all 10)", summary(sql["facets"]), ""))

    print(f"\n{trials:,} trials; {platform.platform()}; Python {platform.python_version()}\n")
    print("| What | Result | Target |")
    print("|---|---|---|")
    for what, result, target in rows:
        print(f"| {what} | {result} | {target} |")


if __name__ == "__main__":
    main()
