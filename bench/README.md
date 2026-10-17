# Benchmarks

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

## Results

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

## What the numbers say

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
