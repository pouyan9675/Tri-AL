"""Storage benchmark: bulk-load synthetic trials, then time queries, search and an update.

    uv run python bench/storage_bench.py               # 50,000 trials
    uv run python bench/storage_bench.py --trials 5000

The trials are synthetic, with sizes and value mixes roughly like ClinicalTrials.gov's, so
the numbers show how storage behaves rather than how the real data does. The real-data
benchmark comes with milestone 3. Results are in bench/README.md.
"""

import argparse
import hashlib
import itertools
import json
import os
import platform
import random
import sqlite3
import statistics
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from trial_al.schema import Intervention, Location, MeshTerm, Outcome, Sponsor, TrialRecord
from trial_al.storage import SQLiteStorage, TrialQuery
from trial_al.storage.countries import COUNTRIES

STATUSES = {
    "COMPLETED": 55,
    "UNKNOWN": 15,
    "RECRUITING": 10,
    "TERMINATED": 6,
    "NOT_YET_RECRUITING": 4,
    "ACTIVE_NOT_RECRUITING": 4,
    "WITHDRAWN": 3,
    "ENROLLING_BY_INVITATION": 1,
    "SUSPENDED": 1,
    "WITHHELD": 1,
}
PHASES = {
    "NA": 40,
    None: 20,
    "PHASE2": 12,
    "PHASE1": 9,
    "PHASE3": 7,
    "PHASE4": 7,
    "PHASE1_PHASE2": 3,
    "PHASE2_PHASE3": 1,
    "EARLY_PHASE1": 1,
}
_MEDICAL_WORDS = (
    "alzheimer dementia amyloid tau cognitive memory placebo randomized double blind "
    "cohort efficacy safety tolerability biomarker plasma cerebrospinal fluid infusion "
    "oral dose patients participants baseline week month outcome primary secondary "
    "adverse events treatment therapy disease cancer diabetes hypertension stroke "
    "depression pain heart kidney liver lung breast prostate vaccine antibody inhibitor "
    "receptor mild moderate severe chronic acute clinical trial study assessment score "
    "scale change from visit"
)
MEDICAL = _MEDICAL_WORDS.split()


class Generator:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        syllables = ["ba", "co", "di", "fe", "ga", "hi", "jo", "ka", "lu", "me", "no", "pa"]
        syllables += ["qui", "ro", "sa", "te", "vi", "xa", "ze", "tri", "ol", "an", "ex", "um"]
        made_up = {
            "".join(self.rng.choices(syllables, k=self.rng.randint(2, 4))) for _ in range(6000)
        }
        # Zipf-like: a few words are very common, most are rare.
        self.words = MEDICAL + sorted(made_up)
        self.cum_weights = list(
            itertools.accumulate(1 / (rank + 1) for rank in range(len(self.words)))
        )
        self.conditions = [self.phrase(1, 4).title() for _ in range(8000)]
        self.interventions = ["Placebo"] + [self.phrase(1, 3).title() for _ in range(20000)]
        self.sponsors = [self.phrase(2, 5).title() + " Inc." for _ in range(5000)]
        self.mesh = [(f"D{n:06d}", self.phrase(1, 3).title()) for n in range(3000)]
        self.countries = [code for code, _, _ in COUNTRIES]

    def phrase(self, low: int, high: int) -> str:
        count = self.rng.randint(low, high)
        return " ".join(self.rng.choices(self.words, cum_weights=self.cum_weights, k=count))

    def text(self, chars: int) -> str:
        words: list[str] = []
        length = 0
        while length < chars:
            sentence = self.phrase(6, 18).capitalize() + "."
            words.append(sentence)
            length += len(sentence) + 1
        return " ".join(words)

    def pick[T](self, options: dict[T, int]) -> T:
        return self.rng.choices(list(options), list(options.values()))[0]

    def skewed(self, items: Sequence[str]) -> str:
        """Mostly items near the front, sometimes any of them."""
        return items[int(len(items) * self.rng.random() ** 3)]

    def trial(self, n: int) -> TrialRecord:
        rng = self.rng
        start = date(2000, 1, 1) + timedelta(days=rng.randint(0, 9500))
        countries = ["US"] if rng.random() < 0.35 else []
        countries += rng.sample(self.countries, rng.choice([0, 1, 1, 1, 2, 3]))
        countries = list(dict.fromkeys(countries))
        sites = int(rng.paretovariate(1.1)) if countries else 0
        brief_summary = self.text(rng.randint(300, 1500))
        description = self.text(rng.randint(500, 6000)) if rng.random() < 0.6 else None
        eligibility = self.text(rng.randint(400, 3000))
        raw = json.dumps(
            {
                "protocolSection": {
                    "identificationModule": {"nctId": f"NCT{n:08d}"},
                    "descriptionModule": {
                        "briefSummary": brief_summary,
                        "detailedDescription": description,
                    },
                    "eligibilityModule": {"eligibilityCriteria": eligibility},
                    "armsInterventionsModule": {"armGroups": [self.text(300) for _ in range(3)]},
                }
            },
            separators=(",", ":"),
        ).encode()
        return TrialRecord(
            source="ctgov",
            source_id=f"NCT{n:08d}",
            title=self.phrase(5, 14).capitalize(),
            official_title=self.phrase(10, 30).capitalize() if rng.random() < 0.9 else None,
            status=self.pick(STATUSES),
            phase=self.pick(PHASES),
            study_type="INTERVENTIONAL" if rng.random() < 0.78 else "OBSERVATIONAL",
            primary_purpose="TREATMENT",
            start_date=start,
            primary_completion_date=start + timedelta(days=rng.randint(100, 1500)),
            completion_date=start + timedelta(days=rng.randint(200, 2500)),
            first_posted=start - timedelta(days=rng.randint(0, 100)),
            last_update=start + timedelta(days=rng.randint(0, 3000)),
            enrollment=int(rng.lognormvariate(4, 1.3)),
            enrollment_type=rng.choice(["ACTUAL", "ESTIMATED"]),
            arms_count=rng.randint(1, 4),
            has_results=rng.random() < 0.12,
            min_age_days=18 * 365 if rng.random() < 0.8 else None,
            max_age_days=rng.choice([None, 65 * 365, 85 * 365]),
            sex=rng.choice(["ALL", "ALL", "ALL", "FEMALE", "MALE"]),
            healthy_volunteers=rng.random() < 0.2,
            brief_summary=brief_summary,
            description=description,
            eligibility_criteria=eligibility,
            outcomes=[
                Outcome(
                    "primary" if i < 2 else "secondary",
                    self.phrase(3, 10).capitalize(),
                    self.text(rng.randint(0, 400)) or None,
                    f"{rng.randint(1, 104)} weeks",
                )
                for i in range(rng.randint(1, 7))
            ],
            conditions=[self.skewed(self.conditions) for _ in range(rng.randint(1, 3))],
            mesh_terms=[
                MeshTerm(code, term, "condition", ancestor=i > 1)
                for i, (code, term) in enumerate(rng.sample(self.mesh, rng.randint(0, 12)))
            ],
            interventions=[
                Intervention(
                    self.skewed(self.interventions),
                    rng.choice(["DRUG", "DRUG", "BEHAVIORAL", "DEVICE", "BIOLOGICAL", "OTHER"]),
                    tuple(self.phrase(1, 2).title() for _ in range(rng.choice([0, 0, 1, 2]))),
                )
                for _ in range(rng.randint(0, 3))
            ],
            sponsors=[
                Sponsor(self.skewed(self.sponsors), "lead", rng.choice(["INDUSTRY", "OTHER"]))
            ]
            + [
                Sponsor(self.skewed(self.sponsors), "collaborator", "OTHER")
                for _ in range(rng.choice([0, 0, 1, 2]))
            ],
            countries=countries,
            locations=[
                Location(
                    self.phrase(2, 5).title() + " Hospital",
                    self.phrase(1, 2).title(),
                    None,
                    rng.choice(countries),
                    "RECRUITING",
                    rng.uniform(-60, 70),
                    rng.uniform(-180, 180),
                )
                for _ in range(min(sites, 2000))
            ],
            raw=raw,
            content_hash=hashlib.blake2b(raw, digest_size=16).digest(),
        )


def words_by_share(storage: SQLiteStorage, trials: int) -> list[tuple[str, int]]:
    """Indexed words found in about 0.1%, 1%, 10% and all of the trials.

    Ranking costs time for every matching trial, so how common the word is decides how long
    a search takes. Picking words by share keeps the numbers comparable across runs.
    """
    picked = []
    with storage.engine.connect() as conn:
        conn.execute(
            text("CREATE VIRTUAL TABLE temp.bench_vocab USING fts5vocab(main, trials_fts, row)")
        )
        for share in (0.001, 0.01, 0.1, 1.0):
            word, docs = conn.execute(
                text(
                    "SELECT term, doc FROM temp.bench_vocab WHERE term GLOB '[a-z][a-z]*'"
                    " ORDER BY abs(doc - :target) LIMIT 1"
                ),
                {"target": share * trials},
            ).one()
            if (word, docs) not in picked:
                picked.append((str(word), int(docs)))
        conn.execute(text("DROP TABLE temp.bench_vocab"))
    return picked


def timed(fn: Callable[[], object], repeat: int) -> tuple[float, float]:
    """Median and p95 in milliseconds."""
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return statistics.median(times), times[min(len(times) - 1, int(len(times) * 0.95))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--trials", type=int, default=50_000)
    parser.add_argument("--batch", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--repeat", type=int, default=50)
    parser.add_argument("--keep", type=Path, help="write the database here and keep it")
    args = parser.parse_args()

    print(
        f"Python {platform.python_version()}, SQLite {sqlite3.sqlite_version}, "
        f"{platform.platform()}, {platform.machine()}, {os.cpu_count()} CPUs"
    )

    start = time.perf_counter()
    generator = Generator(args.seed)
    records = [generator.trial(n) for n in range(1, args.trials + 1)]
    links = sum(
        len(r.conditions)
        + len(r.mesh_terms)
        + len(r.interventions)
        + len(r.sponsors)
        + len(r.countries)
        + len(r.locations)
        + len(r.outcomes)
        for r in records
    )
    print(
        f"generated {len(records):,} trials ({links:,} list items) in "
        f"{time.perf_counter() - start:.1f} s (not counted below)"
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = args.keep or Path(tmp) / "trials.db"
        with SQLiteStorage.open(path) as storage:
            rows: list[tuple[str, str]] = []

            start = time.perf_counter()
            with storage.bulk_load() as load:
                for i in range(0, len(records), args.batch):
                    load.upsert_batch(records[i : i + args.batch])
                loaded = time.perf_counter()
            done = time.perf_counter()
            total = done - start
            rows.append(("Bulk load: insert", f"{loaded - start:.1f} s"))
            rows.append(("Bulk load: indexes + FTS + ANALYZE", f"{done - loaded:.1f} s"))
            rows.append(
                ("Bulk load: total", f"{total:.1f} s ({len(records) / total:,.0f} trials/s)")
            )
            size = sum(f.stat().st_size for f in path.parent.glob(path.name + "*"))
            rows.append(("Database size", f"{size / 2**20:,.0f} MB"))

            ids = [r.id for r in storage.query_trials(TrialQuery(limit=args.trials))]
            rng = random.Random(args.seed)
            queries: list[tuple[str, Callable[[], object], int]] = [
                ("get_trial (random id)", lambda: storage.get_trial(rng.choice(ids)), 200),
                (
                    "count_trials(status=RECRUITING)",
                    lambda: storage.count_trials(TrialQuery(status=("RECRUITING",))),
                    args.repeat,
                ),
                (
                    "count_trials(phase=PHASE2/PHASE3)",
                    lambda: storage.count_trials(TrialQuery(phase=("PHASE2", "PHASE3"))),
                    args.repeat,
                ),
                (
                    "query_trials(status=RECRUITING, limit=100)",
                    lambda: storage.query_trials(TrialQuery(status=("RECRUITING",))),
                    args.repeat,
                ),
                (
                    "query_trials(phase=PHASE3, status=COMPLETED, limit=100)",
                    lambda: storage.query_trials(
                        TrialQuery(phase=("PHASE3",), status=("COMPLETED",))
                    ),
                    args.repeat,
                ),
                *(
                    (
                        f"search: a word in {docs:,} trials ({docs / len(ids):.1%}), top 20",
                        lambda word=word: storage.search(word),
                        args.repeat,
                    )
                    for word, docs in words_by_share(storage, len(ids))
                ),
                ("lookup_names('alz')", lambda: storage.lookup_names("alz"), args.repeat),
            ]
            for name, fn, repeat in queries:
                median, p95 = timed(fn, repeat)
                rows.append((name, f"{median:.2f} ms median, {p95:.2f} ms p95"))

            changed = [
                replace(record, title=record.title + " (amended)", status="COMPLETED")
                for record in rng.sample(records, min(1500, len(records)))
            ]
            start = time.perf_counter()
            with storage.transaction() as tx:
                tx.upsert_batch(changed)
            rows.append(
                (
                    f"Update: upsert {len(changed):,} changed trials in one transaction",
                    f"{time.perf_counter() - start:.2f} s",
                )
            )

    width = max(len(name) for name, _ in rows)
    print(f"\n| {'What':<{width}} | Result |\n|{'-' * (width + 2)}|--------|")
    for name, value in rows:
        print(f"| {name:<{width}} | {value} |")


if __name__ == "__main__":
    main()
