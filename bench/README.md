# Benchmarks

- [Front end](#front-end-milestone-5): the bundle budget and the dashboard's cold load
  (milestone 5).
- [API](#api-milestone-4): every §10 API target on the full database, the search rework and
  the database after it (milestone 4).
- [Real data](#real-data-milestone-3): a full install of ClinicalTrials.gov and a real update
  (milestone 3), with the database size by table.
- [Storage benchmark](#storage-benchmark-milestone-2): synthetic trials against the SQLite
  storage layer (milestone 2).

## Front end (milestone 5)

```bash
cd web && npm run build && npm run budget          # bundle sizes from Vite's manifest
npx playwright test cold-load                      # cold loads of the dashboard (tri-al serve)
```

`npm run budget` counts gzip (level 9) sizes from the build: **initial JS** is the entry
chunk and every chunk it imports statically, which every page needs before it can draw;
each page's own chunks load after it. `cold-load.spec.ts` starts `tri-al serve` with the
built front end on `data/trials.db` and loads `/` five times in new browser contexts (empty
cache), after one warm-up; "interactive" is when every chart from `/api/dashboard` has drawn,
the map included, from the start of navigation. It also runs once with the CPU slowed 4×.

2026-10-18, 607,349 trials, the M4 Pro Mac below, Google Chrome 155, one API worker.

| What | Result | Target (§10) |
|---|---|---|
| Initial JS (entry + static imports), gzip | **158.1 KB** | < 200 KB |
| CSS, gzip | 19.4 KB | |
| Dashboard chunk (Recharts and the widgets), gzip | 118.9 KB | |
| Map widget chunk (d3-geo, its own), gzip; world shapes (a separate JSON file) | 11.7 KB; 39.5 KB | |
| Trials, trial, settings, ⌘K chunks, gzip | 31.3, 15.2, 15.8, 10.3 KB | |
| Dashboard interactive, cold load (5 runs) | 446 ms median, **474 ms max** | < 1.5 s |
| First contentful paint | 132 ms median | |
| JS fetched by then, as sent (server gzip, level 5) | 319 KB in 38 requests | |
| Dashboard interactive with the CPU slowed 4× (one run each time) | 1.09–1.41 s over three runs | |

Kept out of the first load on purpose: each page (route-level chunks), Recharts (only the
dashboard needs it), the map and its shapes, the ⌘K palette (fetched when the browser is
idle), and the toaster (mounted when idle). Two changes during the milestone took the entry
from 145 to 125 KB: toasts load lazily, and the header's theme control became a single
button instead of a dropdown, so Radix's menu left the entry.

## API (milestone 4)

```bash
uv run python bench/api_bench.py                  # data/trials.db, with the trial index
uv run python bench/api_bench.py --compare-sql    # also every filter in SQLite alone (~4 min)
```

`api_bench.py` runs the app in uvicorn on a free port, as `tri-al serve` does, waits for the
in-memory trial index, then times each kind of request over HTTP. Times are server times
from the `Server-Timing` header (until the response starts, gzip included); loopback adds
about a millisecond. Filtered requests and searches are cold: each of 32 filters and 30
queries is asked for once, so nothing comes from the result cache. The filters run from
rare (122 trials) to nearly everything (`q=study`, 572,381), alone and combined; the
queries from rare words to `the`.

2026-10-17, 607,349 trials (the 2026-10-16 release), same Mac as below, one API worker.

| What | Result | Target (§10) |
|---|---|---|
| `GET /api/stats/{id}`, precomputed (7 charts × 30) | 0.6 ms median, **0.8 ms p95** | p95 < 20 ms |
| Whole dashboard: manifest + 7 charts, server time | 4.8 ms median, **5.0 ms p95** | < 50 ms |
| Filtered list (first page and total), 32 filters | 5.3 ms median, 30.6 ms p95, 150 ms max | |
| Filtered facets (all 10 at once), 32 filters | 18.6 ms median, 36.5 ms p95, 37 ms max | |
| Filtered chart (7 per filter) | 2.7 ms median, 11.1 ms p95, 18 ms max | |
| Filtered list, facets or chart, all together (288) | 3.4 ms median, **23.5 ms p95**, 150 ms max | p95 < 300 ms |
| `GET /api/trials/{id}`, 200 random trials | 1.1 ms median, **1.5 ms p95** | p95 < 30 ms |
| `GET /api/search`, 30 queries | 53 ms median, **83 ms p95**, 103 ms max (`the`) | p95 < 150 ms |
| Unchanged request (304) | 0.6 ms median | |
| Paging 20 pages of 50 through completed trials | 4.1 ms median, 4.5 ms p95 | |
| Trial index: build per API worker | 2.65 s, 58 MB | |
| *For comparison:* the same filters in SQLite alone | 154 ms median, 1,871 ms p95, 8,261 ms max | |
| *For comparison:* facets in SQLite alone | 1,415 ms median, 3,794 ms p95 | |

The slowest filtered request is the list for `q=study` (150 ms): a text filter has to ask
the full-text index for every matching trial, 572k of them. MeSH filters and text filters
read those ids from SQLite in bulk on the raw cursor (a first version, through SQLAlchemy's
rows, took 118 ms for "Neoplasms" and 201 ms for `q=study`).

### What the numbers say

- **Precomputed is free:** a chart with no filter is one primary-key read of its stored
  JSON, wrapped in bytes without parsing: under a millisecond, and the dashboard's eight
  calls take 5 ms together. A 304 costs the same.
- **The index is what makes filters fast.** SQLite alone needs 1–8 s for the facets of one
  broad filter: "top conditions among completed trials" visits 600k link rows, and no SQL
  shape or index changed that (splitting the query across threads was slower still, as the
  merge holds the GIL). The in-memory index counts the same in 6 ms; all ten facets for
  any of the 32 filters take at most 37 ms. It agrees with SQLite exactly (the tests compare
  every count and every page, cursors included).
- **Search is fast for every word now.** Ranking ranks at most the 20,000 newest matches,
  so a word in nearly every trial costs about 50–80 ms instead of 1.5 s, and rare words are
  ranked exactly. Snippets for 20 hits take about 8 ms. `the` is slowest (103 ms): its
  doclist is the longest of all.
- **Name lookups** for ⌘K were the hidden cost of common words: "the" is inside about a
  fifth of all names, and sorting them by length took 76 ms. Lookups now sort the first
  5,000 matches (1–14 ms), and `/api/search` skips them for words under three letters,
  which the trigram index can't help with.

### The search rework and the database

Migration 3 made `trials_fts` contentless and compressed each trial's text (design §15,
decisions 10–12). On the full database:

| Step | Time |
|---|---:|
| Migration 3: build the contentless index from the old text, compress 607k texts, drop the plain tables | 4m24s |
| `VACUUM INTO` a compact copy | 42s |
| `quick_check` and the full-text `integrity-check` of the copy | 74s |

`trials.db` went from **9.10 GB to 6.46 GB**:

| Table | Size | Share | Rows |
|---|---:|---:|---:|
| `trial_docs` | 2,528 MB | 39.1% | 607,349 |
| `trials_fts` | 1,412 MB | 21.8% | 607,349 |
| `trial_text` | 1,230 MB | 19.0% | 607,349 |
| `trials` | 354 MB | 5.5% | 607,349 |
| `trial_mesh` | 329 MB | 5.1% | 6,967,028 |
| `locations` | 296 MB | 4.6% | 3,545,192 |
| `names_fts` | 124 MB | 1.9% | 775,638 |
| `interventions` | 43 MB | 0.7% | 538,071 |
| `trial_sponsors` | 37 MB | 0.6% | 967,780 |
| `trial_interventions` | 33 MB | 0.5% | 1,008,786 |
| `trial_conditions` | 26 MB | 0.4% | 1,093,214 |
| `trial_countries` | 18 MB | 0.3% | 786,023 |
| `intervention_aliases` | 15 MB | 0.2% | 481,798 |
| `conditions` | 11 MB | 0.2% | 134,523 |
| `sponsors` | 8 MB | 0.1% | 103,044 |
| everything else | < 2 MB | | |

- The plain text and outcome rows (`trial_text` 2,524 MB and `trial_outcomes` 1,265 MB
  before) became one compressed blob per trial: 1,230 MB. The packed text compresses to 28%
  of its JSON size; the rest is B-tree pages around blobs averaging 2 KB.
- The contentless index is the same size as the external-content one (1,412 vs 1,410 MB):
  an index never held the text, only its view did.
- A future install writes the index as it loads (it can't be rebuilt from a view any more),
  and its check stage no longer re-reads all text for the full-text `integrity-check`
  (84 s in milestone 3). Not measured yet: the next full install will tell.

### A real update through the API

`tri-al serve` on the full database, `POST /api/jobs/update` (Saturday 2026-10-17, so all
2,606 studies posted since 2026-10-15 were unchanged), followed on `/api/events`:

| Time | Event |
|---:|---|
| 0.0 s | `job` queued |
| 0.5 s | running: `fetch`, "ctgov: changed since 2026-10-15" |
| 2.0 s | `fetch` 1,000 of 2,606 trials |
| 3.5 s | `fetch` 2,000 of 2,606 trials |
| 4.0 s | `write` 0 of 0 |
| 5.0 s | `stats` |
| 7.1 s | succeeded (`commit`) |

The job took 6.4 s: fetch 3.7 s, stats 2.7 s (the first precompute of all 7 charts and 10
facets on this database; an update that changes nothing skips it once the stats are
current).

## Real data (milestone 3)

```bash
uv run tri-al install                            # download the bulk zip and build data/trials.db
uv run tri-al install --from-file ctg-studies.json.zip  # or use a zip you downloaded
uv run tri-al update                             # fetch what changed since the last update
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
