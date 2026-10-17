# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Tri-AL is a Django 3.2 app that mirrors ClinicalTrials.gov data into a local SQLite database (`db.sqlite3`) and visualizes it. The domain focus is Alzheimer's trials (see `Trial` docstring and `panels/utils/pipeline.py`). The UI is the Django admin, heavily customized into a Plotly dashboard; a REST API under `/api/` serves a separate front-end (`alzwb-front-end`, listed in `.gitmodules` but not actually committed as a submodule).

## Setup and commands

`visual/settings.py` reads `visual/config.yml` at import time, so **every** command (`manage.py`, `data_manager.py`, tests) fails until it exists:

```bash
pip install -r requirements.txt
cp visual/sample-config.yml visual/config.yml   # then fill in secret_key, email, recipients
mkdir -p data/cache/plot staticfiles            # downloads, chart cache, STATICFILES_DIRS
```

Use Python 3.9 or 3.10: the code uses `tuple[...]` annotations (3.9+) and `import imp` (removed in 3.12), and the pinned numpy/pandas don't support newer versions.

Database:
- `./initdb.sh` is destructive: it deletes `panels/migrations/`, regenerates it, migrates, loads `panels/fixtures/Country.json`, and runs `createsuperuser`.
- On an existing checkout, prefer `python manage.py migrate && python manage.py loaddata panels/fixtures/Country.json` to keep the tracked migration.

Data management (`data_manager.py <action>`):
- `import -i data/AllPublicXML`: bulk-load ClinicalTrials.gov XML files; skips NCT IDs already in the DB.
- `update`: download trials updated since the newest `Trial.last_update`, insert or update them, then email recipients.
- `export [-o file.csv]`, `cleardata` (deletes all trials, agents, conditions, sponsors and logs), `terminal` (IPython shell with Django set up), `manual` (scratch hook for one-off scripts).

Run and test:
```bash
python manage.py runserver        # dashboard at http://localhost:8000/admin
python manage.py test             # panels/tests.py is currently empty
python manage.py test panels.tests.SomeTestCase.test_method
```
No linter or formatter is configured.

## Architecture

**Layout.** `visual/` is the Django project (settings, root urls). `panels/` is the only app and holds everything else: models, admin, REST API (`panels/api/`), templates, and the ingestion/processing code in `panels/utils/`.

**Ingestion has two paths that both end in `processor.data_mapper`:**
1. Bulk import: `XMLFastParser` (`panels/utils/parser.py`) parses each XML file into a dict, then `processor.build_columns`, then `processor.data_mapper`. The mapper creates the `Trial` and get-or-creates related `Agent`/`Condition`/`Country`/`Sponsor` rows.
2. Incremental update: `downloader.download_trials` saves a CSV of recently updated trials to `data/update.csv`. `processor.generate_data` then fetches each trial's full record in 20 threads (`downloader.get_trial` → `FullStudyParser`) and builds derived columns. `processor.build_objects` sends new trials to `data_mapper` and existing ones to `TrialComparator.update_database` (`panels/utils/comparator.py`, driven by its `updatable_fields` map). Afterwards `UpdatesLog` rows are written and `notification.notify_update` sends email.

All three parsers return the same nested dict shape (`NCTID`, `Date.{Start,Completion,...}`, `Sponsors.{Lead,All}`, `Outcome.{Primary,...}`, `Summary`, `Age`, `Agents`, `Countries`, `Locations`, ...). `data_mapper` and `TrialComparator` index into it directly, so renaming a parser key means updating both of them.

`update` is broken: the downloader's endpoints are retired (`/api/query/full_studies` returns 404, and `/ct2/results/download_fields` redirects to the new site). Bulk import still works because `AllPublicXML.zip` redirects to `/api/legacy/public-xml`. Checked 2026-10-17. The replacement is API v2 (`/api/v2/studies`); see `docs/design.md` on the `v2` branch.

**User-defined columns.** `panels/utils/customize.py` is the extension point. Methods on `Functions` decorated with `@column('name')` run per row in `build_columns`. `Database.columns` fields are injected into the `Trial` model with `vars().update(...)`, so adding one needs a migration.

**Models.** Choice fields store short codes (e.g. phase `'23'`, status `'R'`). Map ClinicalTrials.gov display strings with `Trial.get_char`, `Trial.get_display` and `Agent.get_type_choice`. `Trial` has `simple_history` (`HistoricalTrial`).

**Admin is the main UI.** `/admin/` is served by a custom `MyAdminSite` instance, `my_site`, in `panels/admin.py`, not `admin.site`. Register models on `my_site`. Extra admin pages (newsletter, advanced search, minority, ajax search) are added in `MyAdminSite.get_urls`, with templates in `panels/templates/admin/`.

**Dashboard charts** come from `Plotter` in `panels/utils/plot/charts.py` and are pickled to `data/cache/plot/*.pkl`. A cache file is rebuilt when its mtime date is older than the newest trial's `last_update`. The directory is not auto-created; if it is missing, the admin index crashes.

**REST API** (`panels/api/`): function views marked `@csrf_exempt` with DRF serializers; CORS allows all origins. `/api/pipeline/<year>` and `/api/trial/biomarker/excel` return Excel files built by `panels/utils/pipeline.py`. `/api/publication/` references `Publication`/`PublicationSerializer`, which do not exist (the same goes for `PublicationAdmin`), so that endpoint raises `NameError`.

**Email.** `panels/utils/notification/notification.py` sends mail over SMTP using the `email` block of `config.yml`. Templates are in `panels/templates/notification/`.

## Deployment

`.github/workflows/deploy.yml` runs on a self-hosted runner on every push or PR to `main`. Using the runner's own `venv`, it runs `pip install`, `collectstatic`, `makemigrations`, `migrate`, then `manage.py test`. Model changes are migrated on deploy, but commit the migration anyway. `schedulers/update-db.sh` is the cron entry point that runs `data_manager.py update` on that host.
