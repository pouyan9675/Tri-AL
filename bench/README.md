# Benchmarks

- [Real data](#real-data-milestone-3): a full install of ClinicalTrials.gov and a real update
  (milestone 3), with the database size by table.
- [Storage benchmark](#storage-benchmark-milestone-2): synthetic trials against the SQLite
  storage layer (milestone 2).

## Real data (milestone 3)

```bash
uv run trial-al install                            # download the bulk zip and build data/trials.db
uv run trial-al install --from-file ctg-studies.json.zip  # or use a zip you downloaded
uv run trial-al update                             # fetch what changed since the last update
uv run python bench/db_report.py data/trials.db    # size by table, from SQLite's dbstat
```

2026-10-17, ClinicalTrials.gov's 2026-10-16 release (607,349 studies), on the same Apple
Silicon Mac as below (M4 Pro, 12 CPUs, 24 GB, macOS 26.6), Python 3.13.9 from uv, SQLite
3.50.4, 8 worker processes.

### Install

| Stage | Time | |
|---|---:|---|
| Download | 1m43s | 2.77 GB at 26.9 MB/s |
| Load | 6m13s | read the zip, parse, hash and normalize in 8 workers, write batches of 5,000: about 1,630 trials/s |
| Index | 4m11s | secondary indexes, both full-text indexes, `ANALYZE` |
| Enrich, stats | 0s | empty until milestone 4 |
| Check | 2m43s | `quick_check` 71s, `trials_fts` integrity-check 84s, `names_fts` 4s |
| Swap | 0s | rename `trials.db.new` over `trials.db` |
| **Total** | **14m50s** | 607,349 trials, none failed; peak memory 1.8 GB |

The run summary records `load` as 7m56s: the download happens inside the load stage, since
the source downloads when the pipeline first asks for studies. Download time is now noted
separately (`notes.ctgov.download.seconds`).

### Update

| Update | Time |
|---|---:|
| Real, right after the install: 2,606 studies posted since 2026-10-15 (3 pages), all unchanged | 3.7s |
| 2,606 trials rewritten in one transaction (a copy with their hashes cleared), cold cache | 16.6s: fetch 3.7s, write 9.8s, commit 3.1s |
| The same, warm cache | 10.2s: fetch 3.2s, write 5.2s, commit 1.8s |
| 26,554-trial sample database: 2,498 new trials from the same real update | 5.0s: fetch 3.5s, write 1.3s |

The install's data is the 2026-10-16 release and ClinicalTrials.gov doesn't publish on
weekends, so on a Saturday the real update rightly finds nothing new; the hash check skips all
2,606. The forced rewrite times the write path at a busy day's size instead. Both are far
inside the 2-minute target (design §10).

### Database size

`trials.db` after the install: **9.10 GB**.

| Table | Size | Share | Rows |
|---|---:|---:|---:|
| `trial_docs` | 2,528 MB | 27.8% | 607,349 |
| `trial_text` | 2,524 MB | 27.7% | 607,349 |
| `trials_fts` | 1,410 MB | 15.5% | 607,349 |
| `trial_outcomes` | 1,265 MB | 13.9% | 3,799,088 |
| `trials` | 357 MB | 3.9% | 607,349 |
| `trial_mesh` | 352 MB | 3.9% | 6,967,028 |
| `locations` | 331 MB | 3.6% | 3,545,192 |
| `names_fts` | 124 MB | 1.4% | 775,638 |
| `interventions` | 46 MB | 0.5% | 538,071 |
| `trial_sponsors` | 41 MB | 0.4% | 967,780 |
| `trial_interventions` | 35 MB | 0.4% | 1,008,786 |
| `trial_conditions` | 28 MB | 0.3% | 1,093,214 |
| `trial_countries` | 20 MB | 0.2% | 786,023 |
| `intervention_aliases` | 17 MB | 0.2% | 481,798 |
| `conditions` | 11 MB | 0.1% | 134,523 |
| `sponsors` | 8 MB | 0.1% | 103,044 |
| `mesh_terms` | 1 MB | 0.0% | 22,669 |
| everything else | < 1 MB | | |

Sizes include each table's indexes; the full-text rows include their shadow tables. Plus
2.77 GB for the downloaded zip in `data/downloads/`, which a rebuild can reuse (or delete it).

### What the numbers say

- **Raw documents were the problem, and compression fixed it.** The studies are 10.5 GB of
  JSON. Stored as SQLite JSONB, as milestone 2 did (93% of the JSON size on a sample),
  `trial_docs` would be about 9.8 GB and the database about 16.4 GB. Compressed one by one
  with zstd against a dictionary trained on the first 5,000 documents, they're 19% of the
  JSON size: 2.5 GB (design §15, decision 6). On the sample, zlib managed 27% at a quarter
  of the speed, and plain zstd 29%.
- **Text is now as big as the raw documents.** `trial_text` and `trial_outcomes` hold 3.8 GB
  of summaries, descriptions, eligibility criteria and outcomes that the full-text index
  reads through its content view. Compressing them would save about 2.7 GB, but the
  full-text index would have to become contentless (no snippets, and a rebuild re-reads
  every trial in Python). Left as an option.
- **Page size doesn't matter:** a 26,554-study sample came to 407 MB with 4 KB pages, 410 MB
  with 8 KB and 397 MB with 16 KB, so the default stays.
- **The single writer is the bottleneck.** During the load the main process ran at about
  98% CPU, reading the zip and writing, while the 8 workers sat near 25%. Normalizing costs
  about 77 µs per study on one core. The load ran at 2,600 trials/s on the sample and
  1,630/s on the full set. Milestone 6's performance pass could read the zip on another
  thread and compress documents in the workers.
- **The check costs 18% of the install.** The full-text integrity check (84s) re-reads every
  trial's text through the content view right after the index was rebuilt from that same
  view, so it mostly guards against bugs; it stays for now, and is the first thing to drop if
  the install budget gets tight.
- **The sample predicted the full run well:** 26,554 studies (the first 120 MB of the zip)
  took 20.7s and 403 MB, which projected 9.2 GB; the full database is 9.1 GB.

## Storage benchmark (milestone 2)

`storage_bench.py` measures the SQLite storage layer from milestone 2. It generates
synthetic `TrialRecord`s, bulk-loads them, then times reads, queries, full-text search and
an update the size of a busy day (1,500 changed trials in one transaction).

```bash
uv run python bench/storage_bench.py                  # 50,000 trials
uv run python bench/storage_bench.py --trials 5000    # quicker
uv run python bench/storage_bench.py --keep /tmp/b.db # keep the database to inspect
```

The trials are made up. Their sizes and value mixes are roughly ClinicalTrials.gov's: 1–3
conditions, up to 12 MeSH terms, 0–3 interventions, 1–3 sponsors, a long tail of sites,
summaries of 300–1,500 characters, descriptions on 60% of trials, and raw JSON that repeats
the text. The real-data benchmark (`bench/` dataset script, §10 targets) comes with
milestones 3 and 4.

### Results

2026-10-17, 50,000 trials in batches of 5,000, on an Apple Silicon Mac (arm64, 12 CPUs,
macOS 26.6), Python 3.13.9 from uv, SQLite 3.50.4. Medians and p95s are over 50 runs
(200 for `get_trial`).

| What | Result |
|---|---|
| Bulk load: insert | 7.2 s |
| Bulk load: indexes + FTS + ANALYZE | 11.1 s |
| Bulk load: total | 18.3 s (2,727 trials/s) |
| Database size | 866 MB |
| `get_trial` (random id) | 0.49 ms median, 0.52 ms p95 |
| `count_trials(status=RECRUITING)` | 0.27 ms median, 0.29 ms p95 |
| `count_trials(phase=PHASE2/PHASE3)` | 0.44 ms median, 0.49 ms p95 |
| `query_trials(status=RECRUITING, limit=100)` | 0.32 ms median, 0.33 ms p95 |
| `query_trials(phase=PHASE3, status=COMPLETED, limit=100)` | 0.34 ms median, 0.36 ms p95 |
| `search`: a word in 868 trials (1.7%), top 20 | 1.44 ms median, 1.47 ms p95 |
| `search`: a word in 5,000 trials (10%), top 20 | 7.75 ms median, 7.86 ms p95 |
| `search`: a word in all 50,000 trials, top 20 | 147 ms median, 149 ms p95 |
| `lookup_names('alz')` | 6.00 ms median, 6.09 ms p95 |
| Update: upsert 1,500 changed trials in one transaction | 1.14 s |

The script prints this table; the search rows name whatever words it picked, by how many
trials contain them.

### What the numbers say

- **Search time grows with the number of matching trials.** Ranking (`ORDER BY rank`, bm25
  with column weights) scores every match before taking the top 20: about 1.5–3 µs per
  matching trial. Rare and mid-frequency words are fast, but a word in nearly every trial
  ("study", "patients") would take roughly 1.8 s at 607k trials, far over the §10 target
  of 150 ms p95. Milestone 4 needs a plan for very common words, such as ranking only
  titles and conditions for broad queries, capping the candidates, or dropping stopwords.
- **Bulk load** runs at about 2,700 trials/s, so 607k synthetic trials would take about
  4 minutes. Building indexes and full-text search after the load takes 60% of that. Real
  trials have more locations and bigger raw JSON, so milestone 3 measures the real number.
- **Size:** at 20,000 trials, raw JSON (`trial_docs`) is 36% of the file, `trial_text` 30%,
  the full-text index 16% and outcomes 8%. Real raw JSON is larger than the synthetic kind,
  so `trial_docs` will dominate; milestone 3 should check the real size before keeping
  every raw document.
- **Reads and filters** are well under a millisecond, and the daily update shape (1,500
  trials) takes about a second, well inside the 2-minute budget.
