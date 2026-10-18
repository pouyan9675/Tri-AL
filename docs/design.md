# Tri-AL v2 — System Design

Status: **draft; decisions recorded in [§15](#15-decisions)** (2026-10-17, branch `v2`; milestones 1–4 built). Scope: the base platform only. AI features come later and plug into the extension points listed in [§12](#12-extension-points-reserved-for-ai).

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

No Redis and no separate database server. The cache lives in memory in each API worker, keyed by `data_version`. Each API worker also keeps an in-memory column index of every trial for counting under filters (§5.5), about 60 MB at 607k trials.

## 4. Repository layout

One repo managed as a uv workspace:

```
core/                 Python package `tri-al` (src/tri_al/…)
  src/tri_al/
    schema/  storage/  pipeline/  jobs/  stats/  plugins/  config/  access/  api/  cli/
    filters.py        TrialFilter, the one filter language (§5.5)
    search.py         search providers and how their results merge
    testing/          contract test suites that plugins reuse
  tests/
plugins/
  ctgov/              tri-al-ctgov       ClinicalTrials.gov source (installed by default)
  charts/             tri-al-charts      default dashboard charts (installed by default; built in milestone 4)
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
- **Reads in one snapshot:** `SQLiteStorage.read()` gives a reader whose every query runs in one read transaction, so an API request sees one commit: its data version, data and precomputed stats always agree, even while an update commits.
- **API workers don't migrate:** `serve` applies pending migrations once at startup; API workers open `trials.db` with `SQLiteStorage.attach`, which refuses a database that still needs migrations.
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
- **Entry points:** `Pipeline.run_install(progress, from_file=, force=)` and `Pipeline.run_update(progress)`, built from the loaded plugins with `Pipeline.from_plugins`. Both return a `RunSummary` (counts per source, seconds per stage, failures, the source's notes). `progress` receives `Progress(stage, done, total, unit, message)` reports, often; a job throttles them to `app.db` (§5.4), and stops a run by raising from the callback.
- **Reconcile:** an optional weekly job pages through just the NCT IDs to catch studies that were removed.

### 5.4 Jobs
- **Storage:** the `jobs` table in `app.db`: type, status (`queued`, `running`, `succeeded`, `failed`, `cancelled`), stage, progress, total, unit, message, error, payload, result (the run summary), origin (`api`, `schedule`, `cli`, `plugin`), cancel_requested, worker, heartbeat, and timestamps (`tri_al.jobs.JobQueue`).
- **Claiming:** the worker claims the oldest job that can run with `UPDATE … WHERE id = (SELECT … WHERE status='queued' …) RETURNING`.
- **One data job at a time:** install, update and rebuild are data jobs. Queuing one while another is queued or running is refused (the API answers 409 with that job), `claim` skips them while one runs, and a partial unique index allows only one running. `tri-al install` and `tri-al update` record themselves as running jobs too, so a shell command and the server never write at once, and the server shows their progress.
- **Progress:** the pipeline reports often; `JobProgress` writes to `app.db` at most twice a second. A report that comes too soon is held, and a heartbeat thread writes it half a second later, so each stage's last state still lands. Progress stays visible during the data transaction, since `app.db` is another file.
- **Heartbeat and crash recovery:** a running job's row gets a heartbeat at least every 5 seconds. When the worker starts, and every minute after, it fails running jobs whose heartbeat is over 60 seconds old ("the process running it stopped").
- **Cancelling:** `POST /api/jobs/{id}/cancel` cancels a queued job at once; a running one stops at its next progress report (`JobCancelled`), and its transaction rolls back.
- **Scheduler:** between jobs the worker queues an update when `update.schedule` says one is due: `off`, `hourly`, `daily` (the default), `weekly`, `daily at 06:30` or `every 6 hours`. Due means the last successful install or update is that old; after a failed one it waits an hour. It never queues one before the first install.
- **Plugin jobs:** `registry.add_job(JobType(name, run))`. They never count as data jobs.

### 5.5 Stats engine
- **Chart specs** come from plugins (`tri_al.stats.Chart`, §7): `id`, `title`, `widget`, `query(ctx, filter) → rows`, a `precompute` flag, a layout hint (`width` and `height` on a four-column grid, and `order`), and which row keys the widget reads (`x`, `y`). Rows are JSON-compatible dicts; the front end only draws them.
- **Default view:** every chart marked `precompute`, and every facet, is computed with no filter in the update's own transaction (the pipeline's stats stage) and stored in the `stats` table with its data version. Readers get the new stats with the new data. An update that changes nothing skips this unless the stored stats are for another version. A chart that raises is left out and listed in the run summary's `stats_errors`; it is computed on request instead. On the full dataset the stage takes 2.7 s.
- **Counting, two ways:** charts and facets ask questions of `Counts` (how many trials, how many per status, the top conditions, distinct interventions, trials per day, …), so each is written once. `SqlCounts` answers in SQLite, for the pipeline's precompute. `IndexCounts` answers from the API worker's `TrialIndex`.
- **The trial index:** SQLite answers a narrow filter quickly, but a broad one makes it visit hundreds of thousands of rows per chart: "top conditions among completed trials" takes about 450 ms, and the facets for one broad filter 1–8 s. Each API worker therefore keeps the columns that filters, facets and charts use in numpy arrays (coded trial columns, dates, enrollment, and the condition, intervention, sponsor and country links), 58 MB at 607k trials, built in 2.6 s from one snapshot in a background thread. A filter becomes a boolean mask; each count is one vectorized pass (the same question takes 6 ms). MeSH, text queries and plugin filter fields are asked of SQLite and turned into masks. The index belongs to one data version; after an update the worker builds the next one and answers from SQLite meanwhile. It also pages the trial list: its sort orders match SQLite's, cursors included, which the tests check.
- **Filtered views** are computed on request and kept in a per-worker LRU cache bounded by bytes (64 MB), keyed by `(what, filter, data_version)`; masks are cached the same way, so a list, its facets and its charts share one. The first request for a new data version empties the cache.
- **One filter language everywhere:** `TrialFilter` (`tri_al.filters`) is used by the trial list, charts, facets and search. It covers:
  - status, phase, study type; conditions (by name) and MeSH terms (by code, narrower terms included); interventions and intervention types; sponsors (lead or collaborator) and the lead sponsor's class; countries
  - date ranges on start, completion, first posted and last update; an enrollment range; has-results
  - a text query (every word must match)
  - filter fields that plugins declare (`FilterField`, a SQL condition)

  Within a field, any value matches; across fields, all must. Filters are frozen with sorted values, so equal filters are equal cache keys. Storage turns a filter into SQL (`tri_al.storage.filtering`); the index evaluates it in memory.
- **Facets** (the counts beside each filter option) are stats with a filter applied. Each facet ignores its own field, so choosing one status still shows what the others would add. The core's facets: status, phase, study type, lead sponsor type, results, intervention type, country, condition, intervention and sponsor.

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
- **Browser protections stay on, even without login** (`tri_al.access.browser`):
  - **Host:** every request's `Host` must be one of the server's names (the local names, `server.host` if it's a specific address, and `server.allowed_hosts`; `"*"` turns the check off). It applies to reads too, since a DNS-rebinding page could otherwise read through a name it controls.
  - **Custom header:** requests that change something (POST, PUT, PATCH, DELETE) must send `X-Tri-AL`. Another origin can't add it without a CORS preflight, which the server never approves.
  - **Origin:** when such a request has an `Origin`, its host must be one of the server's names; `Sec-Fetch-Site: cross-site` is refused.

  This stops other websites open in the same browser from triggering actions on the local server (CSRF and DNS rebinding).
- **Access hook:** every route calls a single `require(action)` check: `read` for every read, and `jobs.update`, `jobs.cancel` and `plugins.edit` for changes. The core's policy (`AllowAll`) allows everything. An optional `auth` plugin could later replace it with `registry.set_access_policy(policy)`, where `policy.allows(request, action)`, for login and roles on shared servers, with no route changes.

### 5.9 API
FastAPI (`tri_al.api`). Data responses are JSON from orjson with a weak `ETag` made of the data version and the build (an unchanged request gets a 304 before any work) and `Cache-Control: no-cache`; responses over 1 KB are gzipped (level 5). Jobs, plugins and events change without the data version, so they are `no-store`. Every response carries `Server-Timing: app;dur=…`.

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | Version, data_version, trial count, last install or update, source cursors, enabled plugins |
| `GET /api/trials` | List with `TrialFilter`, `sort` (`-last_update` by default; also start date, first posted, enrollment, id) and **keyset cursor** pagination (`next_cursor`, opaque; no OFFSET). The first page carries `total` |
| `GET /api/trials/{source_id}` | Trial detail (`?source=` if the id is in several registries) |
| `GET /api/trials/{source_id}/changes` | Change history, newest first |
| `GET /api/search?q=` | Full-text search, merged across search providers, within the filter. Hits carry snippets; `names` adds matching conditions, interventions and sponsors for jumping to a filter |
| `GET /api/facets` | Counts for filter options under the current filter, and the filter's total |
| `GET /api/dashboard` | Dashboard manifest: charts (with layout and row keys) and facets |
| `GET /api/stats/{chart_id}` | Chart rows, precomputed (no filter) or filtered |
| `GET /api/events` | SSE stream: `hello`, then `data_version` changes and `job` changes |
| `POST /api/jobs/update`, `GET /api/jobs[/{id}]`, `POST /api/jobs/{id}/cancel` | Start an update (202, or 409 with the job already queued or running), job status, cancel |
| `GET/PATCH /api/plugins[/{name}]` | List plugins; PATCH enables, disables or changes settings by editing `tri-al.toml` (checked against the plugin's settings model first; applies on the next start) |
| `/api/x/<plugin>/…` | Routes plugins add with `registry.add_routes` |

Filter fields are query parameters named as in `TrialFilter`, repeated for several values (`status=RECRUITING&status=COMPLETED`; names may contain commas). Ranges are `from..to` with either end open (`start=2020..2023`, `enrollment=1000..`). Plugin filter fields use their own names.

- **Events:** each API worker runs one poller while anyone listens. Every half second it reads the data version from `trials.db` and the jobs changed since its last look from `app.db`, and passes changes to every open stream; a quiet stream gets a keep-alive comment every 15 seconds. A poll reports each changed job once as it is then, so a job that finishes between two polls skips straight to its end.
- **Workers:** handlers are plain functions run in FastAPI's thread pool (SQLite releases the GIL); `server.workers` (default 1) sets the API processes, each with its own cache and index.

The OpenAPI schema is at `/api/openapi.json` (docs at `/api/docs`), with an operation id per route (`listTrials`, `getChartData`, …) and typed response models (`tri_al.api.models`), so `web/` generates a TypeScript client from it. Handlers return orjson bytes rather than the models; the tests check that every response validates against its model.

### 5.10 CLI (Typer)
`tri-al install | update | rebuild | serve | worker | backup | doctor | bench`, plus `tri-al plugins list|enable|disable`.

- `serve` applies pending migrations, then starts the API workers (uvicorn) and one job worker process together; `--host`, `--port`, `--workers` and `--no-job-worker` override the config. `worker` runs the job worker alone.
- `install` and `update` run in the shell but record themselves as jobs, so the server shows them and won't start another (§5.4).
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
| `trial_text` | A trial's brief summary, description, eligibility criteria and outcomes (kind, measure, description, time frame), packed as one JSON array and compressed with zstd against a text dictionary (`dict_id`). See "Text" below |
| `trial_docs` | Raw study JSON, byte for byte, compressed with zstd against a shared dictionary (`dict_id`); kept apart so `trials` stays narrow. See "Raw documents" below |
| `doc_dicts` | The zstd dictionaries, with their kind (`doc` or `text`), kept for good |
| `conditions`, `trial_conditions` | Conditions and links to trials |
| `mesh_terms`, `trial_mesh` | MeSH terms (by descriptor code) and ancestors from `derivedSection`; the link has kind = condition or intervention, and an ancestor flag |
| `interventions`, `trial_interventions`, `intervention_aliases` | Interventions, links (with the intervention type), and each trial's other names for them |
| `sponsors`, `trial_sponsors` | Sponsors and links (with role = lead or collaborator, and the sponsor class) |
| `countries`, `trial_countries` | Countries (seeded with ISO 3166-1 codes, plus Kosovo `XK` and the former Serbia and Montenegro `CS`, Yugoslavia `YU` and Netherlands Antilles `AN`, which registries still use; the alpha-2 code is the key) and links |
| `locations` | trial_id, position, facility, city, state, country_code, status, lat/lon |
| `trial_changes` | trial_id, run_id, field, old, new: replaces v1's `simple_history` and its `first_*` fields |
| `runs` | Install and update runs: stage checkpoints and summary |
| `stats` | chart_id (`facet:<field>` for facets), data_version, payload (the rows as JSON), computed_at |
| `meta` | `data_version`, update cursor, schema info, `bulk_load_started` |
| `trials_fts` | FTS5 (porter/unicode61) over titles, conditions, interventions and their other names, summary, description, eligibility and outcomes. **Contentless** (`content=''`, `contentless_delete=1`): it keeps only the index, and the writer feeds it each trial's text as it writes. See "Search" below |
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
- **Text** is read by the trial detail and for snippets only, so it is compressed like the raw documents (with its own dictionary, trained on the first batch of at least 1,000 trials): 28% of its JSON size; 1.23 GB at 607k trials with its B-tree pages, instead of 3.8 GB as plain columns. Storage still returns complete trials by itself, without the source plugin (§15, decision 10).
- **Search** ranks with BM25 and column weights (titles count most). Ranking costs about 2 µs a match, so a query ranks at most the 20,000 most recently registered matches (`SEARCH_CANDIDATES`): exact for queries with fewer matches, about 50 ms for a word in nearly every trial (§15, decision 11). Snippets come from the hits' unpacked text, put into a small in-memory FTS5 table per thread with the same tokenizer, whose `snippet()` marks the same stemmed words; the hits' snippets cost about 8 ms for 20.
- **`trials` indexes** cover the dashboard's main filters: `status`, `(phase, status)` (which also serves `phase` alone), `start_date`, `last_update`, `lead_sponsor_class`.
- **Raw documents** are compressed one by one with zstd (level 3) against a 110 KB dictionary that the first batch of at least 1,000 documents trains (`storage/docs.py`). A document is still quick to read alone, and real ones shrink to 19% of their JSON size. As SQLite JSONB they'd be about 10 GB at 607k studies, more than every other table together; compressed they're about 2.5 GB (§15, decision 6). The storage no longer checks that `raw` is JSON; the pipeline has parsed it already.
- **The change log** records these fields when an update changes them, old and new as JSON text: title, status, phase, study_type, primary_purpose, the start and completion dates, enrollment and its type, arms_count, has_results, lead sponsor, ages, sex, healthy_volunteers, conditions, interventions, countries and num_sites (`pipeline/changes.py`). `last_update` changes with every version, so it isn't logged.

`app.db` holds `jobs`, `enricher_state` and `_migrations`. Plugin state stays in `tri-al.toml` (§5.6).

Size at 607,349 trials (2026-10-16 release), after migration 3 and `VACUUM`: **6.46 GB**, down from 9.10 GB: raw documents 2.53 GB, the full-text index 1.41 GB, text 1.23 GB, everything else 1.3 GB (bench/README.md has the table).

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
class Chart:                           # tri_al.stats
    id: str
    title: str
    widget: Literal["bar", "line", "area", "pie", "stat", "table", "map"]
    query: Callable[[ChartContext, TrialFilter], list[dict]]   # ctx.conn, ctx.counts(filter)
    precompute: bool = True
    layout: Layout = Layout()          # width and height on a 4-column grid, order
    x: str = "label"                   # the row keys the widget reads
    y: str = "value"

@dataclass
class FilterField:                     # tri_al.filters
    name: str                          # also its query parameter
    title: str
    clause: Callable[[tuple[str, ...]], ColumnElement[bool]]   # a condition on trials

class SearchProvider(Protocol):        # tri_al.search; core ships the FTS5 provider
    name: str
    def search(self, conn: Connection, q: str, filter: TrialFilter, limit: int) -> ProviderResult: ...

@dataclass
class JobType:                         # tri_al.jobs
    name: str
    run: Callable[[JobContext], dict | None]   # ctx.job, ctx.progress, ctx.config

class AccessPolicy(Protocol):          # tri_al.access
    def allows(self, request: Request, action: str) -> bool: ...
```

v1's `customize.py` (`@column` functions plus `Database.columns`) becomes an `Enricher`. Its output goes into the plugin's own table instead of being injected into the `Trial` model.

Charts get a `ChartContext` rather than a bare connection so they can be counted from the in-memory index (§5.5); search providers get the request's read connection. Several providers' results merge by reciprocal rank fusion, since their scores don't compare.

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
1. `POST /api/jobs/update` adds a job to the queue (or the schedule does, or `tri-al update` records one and runs it itself). The worker claims it; a second update gets a 409 with the first.
2. Fetch pages changed since `cursor − 1 day` (typically 1–2 pages), normalize, and check hashes.
3. In one transaction on `trials.db`:
   - upsert the changed trials, their links, text, full-text index and raw docs
   - write the change log
   - run enrichers on the changed trials
   - rebuild the precomputed stats
   - bump `data_version` and the cursor

   Then commit.
4. Fire `update.finished` for any plugin listening. The job's result records new, updated and unchanged counts.
5. Job progress reaches `app.db` at most twice a second all along, and `/api/events` streams it. API workers see the new `data_version`: their caches miss, they build the next trial index in the background, and SSE tells open browsers, whose dashboards re-fetch (each response's ETag changes with the data version).

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
- **Widget registry:** maps a widget type to a component. The dashboard is drawn from `/api/dashboard`, and unknown widget types render a placeholder. Plugins add charts as specs, not as React code; the default charts are the backend `charts` plugin's (built in milestone 4), so the front end only renders them.
- **Live updates:** an `EventSource` on `/api/events` refreshes queries and shows job progress.
- **Serving:** in production, the built SPA is served by FastAPI on the same port. In development, the Vite dev server proxies `/api`.

## 10. Performance

Targets on the full dataset, measured on the reference machine:

| What | Target | Measured in milestone 4 (607,349 trials) |
|---|---|---|
| `GET /api/stats/{id}` (precomputed) | p95 < 20 ms | 0.8 ms |
| Whole dashboard (all chart calls) | < 50 ms server time | 5.0 ms (p95 of manifest + 7 charts) |
| Filtered list, facets or chart | p95 < 300 ms | 23.5 ms (32 filters, cold; 150 ms max) |
| Trial detail | p95 < 30 ms | 1.5 ms |
| Full-text search | p95 < 150 ms | 83 ms (30 queries, cold; 103 ms max) |
| Daily update (~1,500 changed) | < 2 min end to end (milestone 3: 2,606 trials rewritten in 10–17 s) |
| Full install | < 18 min end to end, download included (milestone 3: 14m50s, of which the download took 1m43s) |
| Front end | initial JS < 200 KB gzip; dashboard interactive < 1.5 s on a cold load |

How we get there:
- **Little work per request:** precomputed stats, an in-memory trial index per API worker for filtered counts (§5.5), narrow hot tables, covering indexes, capped search ranking and keyset pagination.
- **Fast fetches:** bulk fetch with one request per 1,000 trials.
- **Fast install:** a process pool for parsing, a single batched writer, and indexes built after the load.
- **Cheap repeat requests:** orjson, ETags/304 and an in-memory cache keyed by data version.
- **Small, lazy front end:** route-level code splitting and a lazy map chunk.

**Benchmarks** live in `bench/` (`api_bench.py` measures the API targets; results in bench/README.md). A fixed sample (about 50k studies, fetched by script, not committed) runs on every PR, and the full dataset runs nightly. A regression of more than 20% fails CI.

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
| Admin dashboard charts (map, phases, status, conditions, updates, stat tiles) | `charts` plugin (backend, milestone 4): totals, trials by country (map) and top countries, by phase, by status, top conditions, recently updated |
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
   - Build: worker, scheduler, SSE, stats engine, `TrialFilter`, facets, all core endpoints, the access hook and browser protections, and the backend `charts` plugin with v1's dashboard set. Search reworked: contentless full-text index, compressed text, capped ranking (migration 3).
   - Done when: the API benchmarks meet §10 on the full dataset.
   - Done 2026-10-17: `tri_al.jobs`, `tri_al.stats` (with the in-memory trial index), `tri_al.api`, `tri_al.access`, `tri-al serve` and `tri-al worker`, and `tri-al-charts`. Every API target is met on 607,349 trials (§10); `trials.db` went from 9.10 to 6.46 GB; `POST /api/jobs/update` ran a real update with live SSE progress in 6.4 s.
5. **Front end.**
   - Build: app shell, dashboard renderer (drawing the `charts` plugin's specs), trial explorer, detail page, ⌘K, settings page with the update button.
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

6. **Raw documents are compressed with zstd.** Real study JSON is 10.5 GB; as SQLite JSONB it would be about 9.8 GB of a 16.4 GB database. Each document is compressed on its own (level 3) against a 110 KB dictionary trained on the first batch, kept in `doc_dicts`: 19% of the JSON size, 2.5 GB, and still quick to read one document (`storage/docs.py`, migration 2). It needs `backports.zstd` on Python 3.13 (the standard library's `compression.zstd` from 3.14). Not chosen: zlib (standard library, but 27% and a quarter of the speed); dropping `resultsSection` (35% of the bytes, but the planned demographics plugin reads it); dropping text that other tables repeat (the document would no longer be the original). Next, if size matters: compress `trial_text` and `trial_outcomes` too and make `trials_fts` contentless, about 2.7 GB less but no snippets. (Done in milestone 4, with snippets kept: decision 10.)
7. **Sources choose what the content hash covers** (`Source.hashable`), because ClinicalTrials.gov stamps every study with the release date (`versionHolder`); hashing it would make each daily update rewrite every study it fetches.
8. **`install` doesn't replace an existing database** unless `--force`, because a fresh database starts the change log over. Carrying the log across a rebuild is left for the `rebuild` command.
9. **Countries outside ISO 3166-1** that ClinicalTrials.gov uses get codes: Kosovo `XK` (user-assigned, widely used) and the former Serbia and Montenegro `CS`, Yugoslavia `YU` and Netherlands Antilles `AN` (reserved by ISO 3166-3). Puerto Rico and other territories keep their own codes, so a trial in the US and Puerto Rico has `location_scope = BOTH`.

Decided in milestone 4 (2026-10-17):

10. **Text is stored once more, compressed, not as plain columns.** The external-content index read 3.8 GB of plain text copies. The index is now contentless and fed at write time, and each trial's text is one zstd blob (1.23 GB in all). Chosen by the user over keeping raw documents only (about 5.3 GB in all), where reading a trial's text would need the source plugin to parse its document: storage stays source-agnostic, so a Postgres backend or another registry needs nothing new. Snippets unpack only the hits.
11. **Broad searches rank only the newest 20,000 matches.** Ranking every match of a word in 572k trials took 1.5 s. Chosen by the user over ranking titles and names only, which measured 420 ms for "study" and still needed a cap. Queries with up to 20,000 matches are ranked exactly; broader ones rank the most recently registered matches, and say so (`capped`). Name lookups cap the same way, at 5,000 names.
12. **The existing database converts by migration, not reinstall** (the user's choice): migration 3 builds the new index from the old text and drops the plain tables (4m24s on the full database), and `VACUUM INTO` gives back the space (42 s). Runs and the change log are kept. Other installs get the migration at their next `serve` or `update`; the freed space is reused, and a later `compact` command could vacuum it.
13. **Filtered stats come from an in-memory index in each API worker, with numpy as a core dependency.** SQLite took 1–8 s for the facets of one broad filter (every completed trial, every trial in the US), which no SQL shape or index fixed: the work is visiting hundreds of thousands of link rows. The index (58 MB, built in 2.6 s per data version) answers the same in 8–40 ms. Not chosen: precomputing facets for single-value filters (over 1,000 queries per update, and still nothing for combinations); splitting queries across threads (slower: the merge holds the GIL); Python sets and bitmaps without numpy (too slow for high-cardinality facets).
14. **The Host check covers every request,** not only changing ones, since DNS rebinding is also a way to read; `server.allowed_hosts` names other hosts.
15. **The default charts are a backend plugin built in milestone 4** (design had them in milestone 5), so milestone 5 only renders specs from `/api/dashboard`.
