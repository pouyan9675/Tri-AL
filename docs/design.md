# Tri-AL v2 — System Design

Status: **draft; decisions recorded in [§15](#15-decisions)** (2026-10-17, branch `v2`). Scope: the base platform only. AI features come later and plug into the extension points listed in [§12](#12-extension-points-reserved-for-ai).

## 1. Goals

- **Fast:** speed targets are written down ([§10](#10-performance)) and checked in CI.
- **Minimal core:** the core is only what every install needs; everything else is a plugin.
- **One-command install** that downloads the data, builds the stats, and leaves a working platform.
- **In-app Update button**, plus a scheduled daily update; both run the same background job.
- **Modern UI:** React + shadcn/ui.

Not goals for the base: AI features, running on several servers, many people editing at once, and Postgres (possible later as a storage plugin).

## 2. Facts the design depends on

Checked against the live API on 2026-10-17:

| Fact | Value |
|---|---|
| Total studies | 607,349 |
| API | ClinicalTrials.gov API v2, version 2.0.5; data refreshed daily |
| Change rate | About 700–1,600 studies updated per weekday, 0 on weekends |
| Paging | `pageSize` up to 1,000 (larger values are capped), cursor via `nextPageToken` |
| Incremental query | `filter.advanced=AREA[LastUpdatePostDate]RANGE[<date>,MAX]` |
| Bulk download | `GET /api/v2/studies/download?format=json.zip` → `ctg-studies.json.zip`, about 2.7 GB. Streamed with no `Content-Length`, and `Range` is ignored (a Range request gets 200 and the whole file), so an interrupted download can't resume |
| Bulk zip layout | One compact JSON file per study, in 100 folders by the last two digits of the NCT number (`35/NCT02807935.json`). Each file is the same JSON the API returns for that study |
| Study shape | `protocolSection` (13 modules), `resultsSection`, `documentSection`, `derivedSection` (MeSH browse terms for conditions and interventions), `hasResults` |
| Enums | Uppercase codes, e.g. `PHASE3`, `ACTIVE_NOT_RECRUITING` |
| Record size | Median 9.9 KB, average 17.3 KB, 99th percentile 150 KB, a few over 500 KB (`/api/v2/stats/size`); 10.5 GB of JSON in all. `resultsSection` is 35% of the bytes |
| Release date | Every study's `derivedSection.miscInfoModule.versionHolder` is the date of the data release, so it changes in all 607k studies every day |
| Countries | 226 `LocationCountry` names. Four have no ISO 3166-1 code: Kosovo, Serbia and Montenegro, Federal Republic of Yugoslavia, Netherlands Antilles |
| v1's endpoints | `/api/query/full_studies` returns 404; `/ct2/...` redirects to the new site. `AllPublicXML.zip` still redirects to `/api/legacy/public-xml`. |

So a daily update is **1–2 API pages**. The data is tiny next to what SQLite can handle.

## 3. Architecture

```
                   ┌───────────────────────────── tri-al serve ──────────────────────────────┐
 browser ──HTTP──▶ │  API (FastAPI, N uvicorn workers)          Worker process (1)           │
  React SPA ◀─SSE─ │   reads trials.db, reads/writes app.db      runs jobs: install, update, │
                   │   serves built SPA files                    enrich, schedule            │
                   └───────────────┬───────────────────────────────────────┬─────────────────┘
                                   │ read                                  │ the only writer
                         ┌─────────▼─────────┐                   ┌─────────▼─────────┐
                         │  data/trials.db   │◀──────────────────│ ClinicalTrials.gov│
                         │  trial data+stats │   pipeline writes │ API v2 / bulk zip │
                         └───────────────────┘                   └───────────────────┘
                         ┌───────────────────┐
                         │  data/app.db      │  jobs + progress,
                         │  app state        │  enricher state
                         └───────────────────┘
```

**Two SQLite files, on purpose:**
- **`trials.db`** holds only data that comes from sources. Only the pipeline writes to it, inside the worker. A rebuild can build a new file and swap it in.
- **`app.db`** holds state the app changes (jobs, enricher state). Job progress keeps updating while an update holds the write lock on `trials.db`, because it's in a different file and so a different lock.
- **Plugin on/off state and settings** live in `tri-al.toml` (§5.6), not in either database.

No Redis and no separate database server. The cache lives in memory in each API worker, keyed by `data_version`.

## 4. Repository layout

One repo managed as a uv workspace:

```
core/                 Python package `tri-al` (src/tri_al/…)
  src/tri_al/
    schema/  storage/  pipeline/  jobs/  stats/  plugins/  config/  access/  api/  cli/
    testing/          contract test suites that plugins reuse
  tests/
plugins/
  ctgov/              tri-al-ctgov       ClinicalTrials.gov source (installed by default)
  charts/             tri-al-charts      default dashboard charts (installed by default)
web/                  React + Vite + TypeScript + Tailwind + shadcn/ui
bench/                benchmark suite and dataset fetch script
docs/
pyproject.toml        workspace root
```

Each plugin is its own package with its own `pyproject.toml`, tests and migrations.

## 5. Core components

### 5.1 Trial schema
- **`TrialRecord`**: a typed record that sources produce and the pipeline stores.
- Internally it's a plain `dataclass(slots=True)`; Pydantic models are used only at the API edge.
- **Identity:** an integer `id` for fast joins, plus a unique `(source, source_id)` pair, e.g. `('ctgov', 'NCT04437511')`. This leaves room for other registries later.

### 5.2 Storage
- **SQLAlchemy Core (no ORM)** for tables and queries. The storage interface (`get_trial`, `query_trials`, `search`, `upsert_batch`, …) is the contract a future Postgres plugin would implement.
- **Database-specific features** (full-text search, JSON) live inside the storage backend.
- **Migrations:** a small built-in runner. Every component (the core and each plugin) ships ordered migrations, tracked in `_migrations(component, version)`. Alembic's per-plugin branches aren't worth the extra complexity.
- **Connection settings (PRAGMAs)** on every connection:
  - `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`
  - `temp_store=MEMORY`, `cache_size=-65536` (64 MB), `mmap_size=1073741824` (1 GB)
- **Python runtime:** Python ≥ 3.13, managed by uv and pinned in `.python-version`. The interpreter's `sqlite3` module must be able to load extensions:
  - macOS's built-in Python can't (checked 2026-10-17: `/Library/Developer/CommandLineTools/usr/bin/python3` has no `enable_load_extension`).
  - uv's CPython 3.13.9 can, and it ships SQLite 3.50.
- **SQLite version:** requires SQLite ≥ 3.45, for JSONB (`group_concat(… ORDER BY …)` needs 3.44 and the trigram tokenizer 3.34).
- **Extension hook:** plugins register SQLite extensions with `registry.add_sqlite_extension(name, load)`, where `load(conn)` is something like `sqlite_vec.load`.
  - Storage loads every registered extension on every new connection (API workers, job worker and CLI), using SQLAlchemy's `connect` event.
  - Each load is wrapped in `enable_load_extension(True)` … `enable_load_extension(False)`, so SQL itself can never call `load_extension()`.
  - A plugin's migrations run only after its extension has loaded.
  - If an enabled plugin's extension fails to load, startup stops with a clear error, rather than failing at the first query.
  - Disabling the plugin leaves its tables in place; only queries on those tables fail ("no such module").
- **Bulk-load settings** (install and rebuild only): `synchronous=OFF`; indexes and full-text search are created after the load; then `ANALYZE` and `PRAGMA optimize`.
  - `meta.bulk_load_started` is set while a bulk load runs. If one doesn't finish, ordinary write transactions refuse to run (the indexes are incomplete) until a bulk load completes, and `doctor` warns.
  - Write transactions use `BEGIN IMMEDIATE`; each bulk-load batch commits on its own.

### 5.3 Pipeline
Install and update use the same stages; only the fetch step differs.

```
fetch ─▶ parse (orjson) ─▶ normalize (source → TrialRecord) ─▶ hash check ─▶ write batch
      ─▶ enrichers (changed trials only) ─▶ rebuild stats ─▶ commit ─▶ bump data_version ─▶ events
```

- **Change detection:** `content_hash` is a 16-byte BLAKE2b hash (from the standard library) of the raw JSON with sorted keys. Trials whose hash hasn't changed are skipped completely. The source decides what goes into the hash (`Source.hashable`, §7): ClinicalTrials.gov leaves out `versionHolder`, the release date every study carries (§2), or every study would look changed after each release. The same study from the bulk zip and from the API hashes the same.
- **Update cursor:** `since = last_seen_update_date − 1 day`. Dates only have day precision, so the overlap guarantees nothing is missed, and the hash check makes the overlap free.
- **Updates are atomic:** the whole update is one `BEGIN IMMEDIATE` transaction on `trials.db`. Readers keep seeing the old data and old stats until the commit, then see the new data and new stats together.
- **Installs are atomic:** an install or rebuild writes `trials.db.new`, checks it, then renames it over `trials.db`.
- **Parallel work:** during install, parsing, hashing and normalizing run in a process pool (spawned, at most 8 workers; about 77 µs per study on one core) while a single writer inserts batches of 5,000 trials. The writer is the bottleneck. Updates (about 1,500 trials) run in one process.
- **Failures:** a study that doesn't parse or normalize is skipped and counted, and the first 100 messages go in the run summary; one odd study doesn't stop an install of 600k.
- **Resuming:** each install stage (`load`, `index`, `enrich`, `stats`, `check`) is checkpointed in the `runs` row inside `trials.db.new`. A re-run skips finished stages. Within the load stage, trials already stored with the same hash are skipped cheaply. The bulk endpoint ignores HTTP `Range` (§2), so an interrupted download starts over; a download that finished (it's written to `.part` and renamed, with its size and SHA-256 in `ctg-studies.json.zip.json`) is reused when an install resumes, and downloaded again for a new install.
- **Entry points:** `Pipeline.run_install(progress, from_file=, force=)` and `Pipeline.run_update(progress)`, built from the loaded plugins with `Pipeline.from_plugins`. Both return a `RunSummary` (counts per source, seconds per stage, failures, the source's notes). `progress` receives `Progress(stage, done, total, unit, message)` reports, often; milestone 4's job throttles them to `app.db`, and can stop a run by raising from the callback.
- **Reconcile:** an optional weekly job pages through just the NCT IDs to catch studies that were removed.

### 5.4 Jobs
- **Storage:** the `jobs` table in `app.db`. Columns: type, status, progress, total, message, payload, heartbeat, and timestamps.
- **Claiming:** the worker claims a job with `UPDATE … WHERE status='queued' … RETURNING`.
- **One data job at a time:** a partial unique index allows only one running job of the kinds install, update or rebuild.
- **Progress:** written to `app.db` at most twice a second, so it stays visible during the data transaction.
- **Crash recovery:** on startup, the worker marks running jobs whose heartbeat has gone stale as failed.
- **Scheduler:** a small built-in scheduler in the worker, configured in `update.schedule` (default: daily).

### 5.5 Stats engine
- **Chart specs** come from plugins: `id`, `title`, `widget`, `query(conn, filters) → rows`, a `precompute` flag, and a layout hint.
- **Default view:** after an update, every chart marked `precompute` is calculated with no filters and stored in the `stats` table in `trials.db`, in the same transaction as the data.
- **Filtered views** are calculated on request and kept in a per-worker in-memory LRU cache keyed by `(chart, filter, data_version)`.
- **One filter language everywhere:** `TrialFilter` is used by the trial list, charts and facets. It covers:
  - status, phase, conditions (including MeSH), interventions, sponsors and sponsor class, countries
  - date ranges, enrollment range, has-results
  - text query
  - filter fields that plugins declare

  Storage turns it into SQL.
- **Facets** (the counts shown beside each filter option) are just stats with a filter applied.

### 5.6 Plugin system
- **Discovery:** Python entry points in the group `tri_al.plugins`. Each plugin exposes a `Plugin` object (name, version, `api_version`, `requires`, settings model) and a `register(registry)` function.
- **Loading:** the core loads the plugins enabled in config, ordered by `requires`. It refuses any plugin whose `api_version` doesn't match.
- **On/off state and settings live in `tri-al.toml`.** Installed plugins are enabled unless their `[plugins.<name>]` section says `enabled = false`, and the rest of that section is the plugin's settings. `tri-al plugins enable|disable` (and later the API) edit the file and keep its comments, and `TRI_AL_PLUGINS__<NAME>__…` variables override it. Plugins load at startup, so changes apply on the next start. No database holds plugin state.
- **Registry API (base):**
  - `add_source`, `add_enricher`, `add_chart`, `add_filter_field`, `add_search_provider`
  - `add_routes(router)`, mounted at `/api/x/<plugin>/`
  - `add_migrations(database, migrations)` for `"trials"` or `"app"`, tracked under the plugin's name; `add_sqlite_extension(name, load)` (see §5.2)
  - `add_job`, `add_cli`, `on(event, handler)`
  - `set_access_policy` (see §5.8)
- **Events:** `update.started(run_id)`, `trials.changed(run_id, ids, kind)` with kind `new` or `updated`, `update.finished(summary)`, `install.finished(summary)`. Each handler gets one event object (`tri_al.pipeline.events`). Handlers run in the process that fires the event, after the data is committed; pipeline events fire in the worker. An install doesn't send `trials.changed`, since every trial is new. A handler that raises is logged and listed in the summary's `handler_errors`; it doesn't stop the run.
- **Rules:**
  - The core never imports plugins.
  - Plugins communicate only through core interfaces and events.
  - Each plugin owns its prefixed tables and its migrations.
  - Every implementation of an interface must pass the core's contract tests (`tri_al.testing`).

### 5.7 Config
- **One file**, `tri-al.toml`, read with the standard library's `tomllib`. Sections: `[server]` (host defaults to `127.0.0.1`), `[data]`, `[update]`, `[plugins.<name>]`.
- **Environment variables** `TRI_AL_*` override it, and secrets come only from the environment.
- **Validation:** each plugin's section is checked against that plugin's settings model.

### 5.8 Access (no login by default)
- **No login by default.** Tri-AL is meant to be installed and used locally, so the base has no users, passwords or roles. Anyone who can reach the app can do everything, including pressing Update.
- **Local only by default:** `serve` binds to `127.0.0.1`. If you bind to any other address without an access plugin, `serve` and `doctor` print a warning.
- **Browser protections stay on, even without login.** Requests that change something (starting an update, changing plugin settings) must send a custom header and pass an Origin check, and the `Host` header must match the configured host. This stops other websites open in the same browser from triggering actions on the local server (CSRF and DNS rebinding).
- **Access hook:** every route that changes something calls a single `require(action)` check. The core's policy allows everything. An optional `auth` plugin could later replace the policy with login and roles for shared servers, with no route changes.

### 5.9 API
All GET responses use orjson, an `ETag` derived from `data_version` (unchanged data returns 304), and gzip.

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | Version, data_version, last update, counts |
| `GET /api/trials` | List with `TrialFilter`, sorting, **keyset cursor** pagination (no OFFSET) |
| `GET /api/trials/{source_id}` | Trial detail |
| `GET /api/trials/{source_id}/changes` | Change history |
| `GET /api/search?q=` | Full-text search, merged across search providers |
| `GET /api/facets` | Counts for filter options under the current filter |
| `GET /api/dashboard` | Dashboard manifest (charts + layout) |
| `GET /api/stats/{chart_id}` | Chart data, precomputed or filtered |
| `GET /api/events` | SSE stream: `data_version` changes, job progress |
| `POST /api/jobs/update`, `GET /api/jobs[/{id}]` | Start an update, job status |
| `GET/PATCH /api/plugins[/{name}]` | List plugins; PATCH enables, disables or changes settings by editing `tri-al.toml` (applies on the next start) |

A TypeScript client for `web/` is generated from the OpenAPI schema.

### 5.10 CLI (Typer)
`tri-al install | update | rebuild | serve | worker | backup | doctor | bench`, plus `tri-al plugins list|enable|disable`.

- `serve` starts the API workers and the job worker together.
- `backup` uses `VACUUM INTO` (an online copy).
- `doctor` checks config, files, versions and plugins. It fails with a fix-it message when:
  - SQLite is older than 3.45
  - the interpreter can't load extensions (it suggests `uv python install`)
  - an enabled plugin's extension doesn't load

  `serve`, `worker` and `install` run the same checks at startup.

## 6. Data model (`trials.db`)

| Table | Contents |
|---|---|
| `trials` | Narrow and fast to scan. See the column groups below this table. |
| `trial_text` | brief_summary, description, eligibility_criteria |
| `trial_outcomes` | trial_id, position, kind (primary, secondary, other), measure, description, time_frame |
| `trial_docs` | Raw study JSON, byte for byte, compressed with zstd against a shared dictionary (`dict_id`); kept apart so `trials` stays narrow. See "Raw documents" below |
| `doc_dicts` | The zstd dictionaries `trial_docs` rows were compressed with, kept for good |
| `conditions`, `trial_conditions` | Conditions and links to trials |
| `mesh_terms`, `trial_mesh` | MeSH terms (by descriptor code) and ancestors from `derivedSection`; the link has kind = condition or intervention, and an ancestor flag |
| `interventions`, `trial_interventions`, `intervention_aliases` | Interventions, links (with the intervention type), and each trial's other names for them |
| `sponsors`, `trial_sponsors` | Sponsors and links (with role = lead or collaborator, and the sponsor class) |
| `countries`, `trial_countries` | Countries (seeded with ISO 3166-1 codes, plus Kosovo `XK` and the former Serbia and Montenegro `CS`, Yugoslavia `YU` and Netherlands Antilles `AN`, which registries still use; the alpha-2 code is the key) and links |
| `locations` | trial_id, position, facility, city, state, country_code, status, lat/lon |
| `trial_changes` | trial_id, run_id, field, old, new: replaces v1's `simple_history` and its `first_*` fields |
| `runs` | Install and update runs: stage checkpoints and summary |
| `stats` | chart_id, data_version, payload |
| `meta` | `data_version`, update cursor, schema info, `bulk_load_started` |
| `trials_fts` | FTS5 (porter/unicode61) over titles, conditions, interventions and their other names, `trial_text` and outcomes. External content: it reads the view `trials_fts_content`, so the text isn't stored twice |
| `names_fts` | FTS5 trigram over condition, intervention and sponsor names (with kind and row id), for fuzzy lookup |

The `trials` table has these columns:
- **Identity:** id, source, source_id
- **Titles:** title, official_title
- **Classification:** status, phase (normalized, e.g. `PHASE2_PHASE3`), study_type, primary_purpose
- **Dates:** start_date, primary_completion_date, completion_date, first_posted, last_update
- **Size and arms:** enrollment, enrollment_type, arms_count, has_results
- **Sponsor:** lead_sponsor_id, lead_sponsor_class
- **Eligibility:** min_age_days, max_age_days, sex, healthy_volunteers
- **Geography:** location_scope (`US`/`NON_US`/`BOTH`), num_sites
- **Bookkeeping:** content_hash, ingested_at

Notes:
- **Dates** are stored as ISO text `YYYY-MM-DD`. Month-only dates become the 1st of the month; the exact original stays in `trial_docs`.
- **Ages** are converted to days, so age ranges are simple numeric filters (v1 stored them as strings). `tri_al.schema.age_in_days` does it, rounding down, with a year of 365.25 days and a month of a twelfth of that (so "12 Months" equals "1 Year"); filters convert with the same function.
- **Link tables** use `WITHOUT ROWID` with primary key `(trial_id, x_id)` plus a reverse index `(x_id, trial_id)`. A `position` column keeps the source's order.
- **Entities are identified by name** (MeSH terms by code). Per-trial details, such as an intervention's type or a sponsor's class, are on the link, so each trial reads back exactly as written. A trial that lists the same entity twice keeps the first.
- **Outcomes are rows, not JSON:** FTS5 can't read virtual tables such as `json_each` through its content view.
- **`trials` indexes** cover the dashboard's main filters: `status`, `(phase, status)` (which also serves `phase` alone), `start_date`, `last_update`, `lead_sponsor_class`.
- **Raw documents** are compressed one by one with zstd (level 3) against a 110 KB dictionary that the first batch of at least 1,000 documents trains (`storage/docs.py`). A document is still quick to read alone, and real ones shrink to 19% of their JSON size. As SQLite JSONB they'd be about 10 GB at 607k studies, more than every other table together; compressed they're about 2.5 GB (§15, decision 6). The storage no longer checks that `raw` is JSON; the pipeline has parsed it already.
- **The change log** records these fields when an update changes them, old and new as JSON text: title, status, phase, study_type, primary_purpose, the start and completion dates, enrollment and its type, arms_count, has_results, lead sponsor, ages, sex, healthy_volunteers, conditions, interventions, countries and num_sites (`pipeline/changes.py`). `last_update` changes with every version, so it isn't logged.

`app.db` holds `jobs`, `enricher_state` and `_migrations`. Plugin state stays in `tri-al.toml` (§5.6).

## 7. Plugin interfaces (base)

```python
class Source(Protocol):                 # tri_al.pipeline; picklable, it's sent to the pool
    name: str
    def fetch_all(self, ctx: FetchContext) -> Iterator[bytes]: ...            # raw study JSON
    def fetch_changed(self, since: date, ctx: FetchContext) -> Iterator[bytes]: ...
    def normalize(self, raw: dict) -> TrialRecord: ...                         # pure, runs in pool
    def hashable(self, raw: dict) -> Any: ...       # what the content hash covers (§5.3)

@dataclass
class FetchContext:
    downloads: Path                    # where a source may keep downloads
    progress: ProgressCallback
    from_file: Path | None             # a local copy of the bulk download (`install --from-file`)
    reuse_download: bool               # a resumed install may reuse a finished download
    total: int | None                  # set by the source: how many studies it will yield
    notes: dict                        # set by the source: facts for the run summary

class Enricher(Protocol):
    name: str
    version: str                       # bump → core schedules a re-run over all trials
    table: Table                       # plugin-owned table keyed by trial_id
    filter_fields: list[FilterField]   # optional: make outputs filterable
    def enrich(self, batch: list[TrialRecord]) -> list[dict]: ...

@dataclass
class Chart:
    id: str
    title: str
    widget: Literal["bar", "line", "area", "pie", "stat", "table", "map"]
    query: Callable[[Connection, TrialFilter], list[dict]]
    precompute: bool = True
    layout: Layout = Layout()

class SearchProvider(Protocol):        # core ships the FTS5 provider
    name: str
    def search(self, q: str, filter: TrialFilter, limit: int) -> list[Hit]: ...
```

v1's `customize.py` (`@column` functions plus `Database.columns`) becomes an `Enricher`. Its output goes into the plugin's own table instead of being injected into the `Trial` model.

## 8. Flows

### Install
1. `uv tool install tri-al`, then `tri-al install [--from-file PATH] [--data-dir ./data] [--force] [--workers N]` (milestone 3; milestone 6 adds `--profile default|minimal` and `--serve`).
2. Write `tri-al.toml` (from prompts or flags). (Milestone 6.)
3. Create `app.db` and run its migrations.
4. Download `ctg-studies.json.zip` into `data/downloads/`, with progress shown and its size and SHA-256 recorded beside it, or read the file given with `--from-file`.
5. Build `trials.db.new`: read the zip member by member (no extraction), in NCT order, so trial ids follow registration order; parse, hash and normalize in a pool; insert in batches with a single writer.
6. Create indexes and full-text search, compute the precomputed stats, run `ANALYZE`, then check: SQLite's `quick_check`, both full-text indexes' `integrity-check`, and at least one trial loaded.
7. Set `data_version` (1, or the old database's plus 1) and each source's update cursor (its latest `last_update`), then rename to `trials.db`. An existing `trials.db` is only replaced with `--force`, which starts the change log over, and only if no other process has it open.
8. Print the URL; `--serve` starts the server straight away. (Milestone 6.)

### Update (button, schedule or CLI)
1. `POST /api/jobs/update` adds a job to the queue. The worker claims it, and the lock rejects a second one.
2. Fetch pages changed since `cursor − 1 day` (typically 1–2 pages), normalize, and check hashes.
3. In one transaction on `trials.db`:
   - upsert the changed trials, their links, text, full-text index and raw docs
   - write the change log
   - run enrichers on the changed trials
   - rebuild the precomputed stats
   - bump `data_version` and the cursor

   Then commit.
4. Fire `update.finished` for any plugin listening. The job's result records new, updated and unchanged counts.
5. API workers see the new `data_version` and drop their caches. SSE tells open browsers, and the dashboards re-fetch.

## 9. Front end

- **Stack:**
  - React, Vite, TypeScript (strict), Tailwind, shadcn/ui
  - TanStack Query (server data and caching), TanStack Router (type-safe, filters synced to the URL), TanStack Table
  - Biome for lint and format
- **Charts:** shadcn Charts (Recharts) for bar, line, area, pie and stat widgets. The `map` widget is a lazy-loaded chunk with its own map library, chosen in milestone 5.
- **Pages:**
  - Dashboard
  - Trials: explorer table plus filter sidebar with facets
  - Trial detail: overview, eligibility, outcomes, locations, changes
  - Settings: update and jobs, plugins
  - A global ⌘K command palette for search
- **Widget registry:** maps a widget type to a component. The dashboard is drawn from `/api/dashboard`, and unknown widget types render a placeholder. Plugins add charts as specs, not as React code.
- **Live updates:** an `EventSource` on `/api/events` refreshes queries and shows job progress.
- **Serving:** in production, the built SPA is served by FastAPI on the same port. In development, the Vite dev server proxies `/api`.

## 10. Performance

Targets on the full dataset, measured on the reference machine:

| What | Target |
|---|---|
| `GET /api/stats/{id}` (precomputed) | p95 < 20 ms |
| Whole dashboard (all chart calls) | < 50 ms server time |
| Filtered list, facets or chart | p95 < 300 ms |
| Trial detail | p95 < 30 ms |
| Full-text search | p95 < 150 ms |
| Daily update (~1,500 changed) | < 2 min end to end (milestone 3: 2,606 trials rewritten in 10–17 s) |
| Full install | < 18 min end to end, download included (milestone 3: 14m50s, of which the download took 1m43s) |
| Front end | initial JS < 200 KB gzip; dashboard interactive < 1.5 s on a cold load |

How we get there:
- **Little work per request:** precomputed stats, narrow hot tables, covering indexes and keyset pagination.
- **Fast fetches:** bulk fetch with one request per 1,000 trials.
- **Fast install:** a process pool for parsing, a single batched writer, and indexes built after the load.
- **Cheap repeat requests:** orjson, ETags/304 and an in-memory cache keyed by data version.
- **Small, lazy front end:** route-level code splitting and a lazy map chunk.

**Benchmarks** live in `bench/`. A fixed sample (about 50k studies, fetched by script, not committed) runs on every PR, and the full dataset runs nightly. A regression of more than 20% fails CI.

## 11. Testing and tooling

- **Python:** ruff for lint and format, mypy (strict on `core`), and pytest. API tests use httpx against the app.
- **Contract tests:** every Source, Enricher, storage backend and SearchProvider must pass the suites in `tri_al.testing`.
- **Fixtures:** a handful of real study JSON files (public data) cover edge cases: results, month-only dates, multiple phases, no locations.
- **Web:** Vitest + Testing Library, plus a Playwright smoke test (install sample → dashboard → filter → detail).
- **CI:** GitHub Actions (hosted runners for PRs; the self-hosted runner for nightly full benchmarks).

## 12. Extension points reserved for AI

Nothing AI-specific is in the base, but these hooks exist so AI features plug in later without changing the core:
- **`Enricher`:** LLM field extraction (MMSE, biomarkers, mechanism of action), with filterable outputs.
- **`SearchProvider`:** semantic and hybrid search behind the same ⌘K box and `/api/search`.
- **`add_routes` and `add_job`:** chat endpoints and embedding backfill jobs.
- **Vector search: a planned plugin built on sqlite-vec.**
  - **Package:** its own plugin (e.g. `tri-al-vectors`), depending on `sqlite-vec`. That's 0 dependencies, version 0.1.9 on 2026-10-17, still pre-1.0. It's loaded through the extension hook (§5.2).
  - **Storage:** its migration creates a `vec0` virtual table in `trials.db` keyed by trial `id`, so vectors change in the same transaction as the trial data.
  - **Filling it:** an embedding `Enricher` fills it for changed trials.
  - **Searching it:** a `SearchProvider` merges its results with FTS5. Filters use the existing tables, with nothing copied into a separate store.
  - **One vector per trial:** title, summary, conditions and interventions.
  - **Size at 607k trials and 1024 dimensions:**

    | Format | Size |
    |---|---|
    | float32 | About 2.5 GB |
    | int8 | About 620 MB |
    | binary | About 78 MB |

    Search the binary vectors first, re-rank the top few hundred at full precision, and measure against the §10 search target.
  - **Fallback:** sqlite-vec 0.1.x scans every vector and has no nearest-neighbor index. If vectors reach the millions (many chunks per trial) and scans miss the target, switch to usearch (3 dependencies, an HNSW index stored in a file) behind the same interface.
  - **Not chosen:**
    - **Chroma:** 28 required dependencies; a separate store outside the update transaction; filter fields would have to be copied into its metadata.
    - **LanceDB:** pulls in pyarrow.
- **To be designed later:** the AI provider interface, and the `VectorIndex` interface that the sqlite-vec and usearch plugins would implement.

## 13. v1 → v2 feature mapping

| v1 | v2 |
|---|---|
| Admin dashboard charts (map, phases, status, conditions, updates, stat tiles) | Core dashboard + `charts` plugin |
| Trial list, advanced search (dates, agents, biomarkers, status, phase) | Trial explorer + `TrialFilter` + facets + ⌘K (core) |
| `simple_history` and `first_*` fields | `trial_changes` (core) |
| `customize.py` columns | `Enricher` plugins |
| Trial edit forms, `reviewed` flag, biomarker curation | Dropped; source data stays read-only |
| Pipeline Excel and biomarker Excel exports | Dropped |
| Race/ethnicity and gender analysis page | **demographics** plugin built from `resultsSection` baseline data (later) |
| Email update notifications | Dropped for now; may return later as a plugin on `update.finished` |
| Newsletter and subscribers | Dropped |
| Admin login | Dropped; no login by default (§5.8) |
| REST API for `alzwb-front-end` | Replaced by the new API; not compatible |
| `/api/publication/` (broken) | Dropped |

## 14. Milestones

Each milestone ends working, tested and measured.

1. **Skeleton.**
   - Build: uv workspace, `core` package, plugin loader with a sample plugin, config, CLI stub, ruff/mypy/pytest, CI.
   - Done when: `tri-al plugins list` shows the sample plugin, and CI is green.
2. **Schema and storage.**
   - Build: `TrialRecord`, SQLite storage, migration runner, `trials.db` and `app.db` tables, full-text search, storage contract tests.
   - Done when: the contract tests pass and a fixture round-trips.
3. **ClinicalTrials.gov plugin and pipeline.**
   - Build: bulk install, incremental update, hash checks, atomic commit and swap, checkpoints, change log.
   - Done when: a full install and a real daily update both work, and the install time is recorded.
   - Done 2026-10-17: the `ctgov` plugin, `tri_al.pipeline` and real `install`/`update` commands. A full install of 607,349 studies took 14m50s and makes a 9.1 GB `trials.db`; a real update fetched 2,606 studies in 3.7s (numbers in bench/README.md).
4. **Jobs, stats and API.**
   - Build: worker, scheduler, SSE, stats engine, `TrialFilter`, facets, all core endpoints, the access hook and browser protections.
   - Done when: the API benchmarks meet §10 on the full dataset.
5. **Front end.**
   - Build: app shell, dashboard renderer, `charts` plugin, trial explorer, detail page, ⌘K, settings page with the update button.
   - Done when: the Playwright smoke test passes and the bundle budget is met.
6. **Install end to end and hardening.**
   - Build: the `uv tool install` + `install` experience, `backup`, `doctor`, a performance pass, docs. A Docker image waits until publishing.
   - Done when: a fresh machine goes from nothing to a working dashboard with one command.

## 15. Decisions

Decided 2026-10-17:

1. **Dataset at install:** install loads all 607k studies. An optional install query (for example, a single condition) is a later feature, not part of the base.
2. **Access:** no login by default, so anyone can install and use Tri-AL locally (§5.8). Login and roles might come later as an optional `auth` plugin.
3. **Dashboard layout:** one shared layout. Per-user layouts might come later.
4. **v1 carry-over:** email notifications, the newsletter, Excel exports and curation are removed. Email may come back later as a plugin. No v1 curated data is imported.
5. **Install method:** `uv tool install`. A Docker image might be added at publishing.

Decided in milestone 3 (2026-10-17):

6. **Raw documents are compressed with zstd.** Real study JSON is 10.5 GB; as SQLite JSONB it would be about 9.8 GB of a 16.4 GB database. Each document is compressed on its own (level 3) against a 110 KB dictionary trained on the first batch, kept in `doc_dicts`: 19% of the JSON size, 2.5 GB, and still quick to read one document (`storage/docs.py`, migration 2). It needs `backports.zstd` on Python 3.13 (the standard library's `compression.zstd` from 3.14). Not chosen: zlib (standard library, but 27% and a quarter of the speed); dropping `resultsSection` (35% of the bytes, but the planned demographics plugin reads it); dropping text that other tables repeat (the document would no longer be the original). Next, if size matters: compress `trial_text` and `trial_outcomes` too and make `trials_fts` contentless, about 2.7 GB less but no snippets.
7. **Sources choose what the content hash covers** (`Source.hashable`), because ClinicalTrials.gov stamps every study with the release date (`versionHolder`); hashing it would make each daily update rewrite every study it fetches.
8. **`install` doesn't replace an existing database** unless `--force`, because a fresh database starts the change log over. Carrying the log across a rebuild is left for the `rebuild` command.
9. **Countries outside ISO 3166-1** that ClinicalTrials.gov uses get codes: Kosovo `XK` (user-assigned, widely used) and the former Serbia and Montenegro `CS`, Yugoslavia `YU` and Netherlands Antilles `AN` (reserved by ISO 3166-3). Puerto Rico and other territories keep their own codes, so a trial in the US and Puerto Rico has `location_scope = BOTH`.
