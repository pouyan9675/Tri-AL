"""The core's migrations for ``trials.db`` and ``app.db``. Frozen once released: add, don't edit."""

import itertools
from datetime import UTC, datetime

from sqlalchemy import Connection

from tri_al.storage import docs
from tri_al.storage.countries import COUNTRIES, EXTRA_COUNTRIES
from tri_al.storage.migrations import Migration, run_script

COMPONENT = "core"

_TRIALS_1 = """\
CREATE TABLE countries (
    code TEXT NOT NULL PRIMARY KEY,
    alpha3 TEXT,
    name TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE conditions (
    id INTEGER NOT NULL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE mesh_terms (
    id INTEGER NOT NULL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    term TEXT NOT NULL
);

CREATE TABLE interventions (
    id INTEGER NOT NULL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE sponsors (
    id INTEGER NOT NULL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE trials (
    id INTEGER NOT NULL PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    official_title TEXT,
    status TEXT,
    phase TEXT,
    study_type TEXT,
    primary_purpose TEXT,
    start_date TEXT,
    primary_completion_date TEXT,
    completion_date TEXT,
    first_posted TEXT,
    last_update TEXT,
    enrollment INTEGER,
    enrollment_type TEXT,
    arms_count INTEGER,
    has_results BOOLEAN NOT NULL,
    lead_sponsor_id INTEGER REFERENCES sponsors (id),
    lead_sponsor_class TEXT,
    min_age_days INTEGER,
    max_age_days INTEGER,
    sex TEXT,
    healthy_volunteers BOOLEAN,
    location_scope TEXT,
    num_sites INTEGER NOT NULL,
    content_hash BLOB,
    ingested_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX trials_status ON trials (status);
CREATE INDEX trials_phase_status ON trials (phase, status);
CREATE INDEX trials_start_date ON trials (start_date);
CREATE INDEX trials_last_update ON trials (last_update);
CREATE INDEX trials_lead_sponsor_class ON trials (lead_sponsor_class);

CREATE TABLE trial_text (
    trial_id INTEGER NOT NULL PRIMARY KEY REFERENCES trials (id) ON DELETE CASCADE,
    brief_summary TEXT,
    description TEXT,
    eligibility_criteria TEXT
);

CREATE TABLE trial_outcomes (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    measure TEXT NOT NULL,
    description TEXT,
    time_frame TEXT,
    PRIMARY KEY (trial_id, position)
);

CREATE TABLE trial_docs (
    trial_id INTEGER NOT NULL PRIMARY KEY REFERENCES trials (id) ON DELETE CASCADE,
    doc BLOB NOT NULL
);

CREATE TABLE trial_conditions (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    condition_id INTEGER NOT NULL REFERENCES conditions (id),
    position INTEGER NOT NULL,
    PRIMARY KEY (trial_id, condition_id)
) WITHOUT ROWID;
CREATE INDEX trial_conditions_by_condition ON trial_conditions (condition_id, trial_id);

CREATE TABLE trial_mesh (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    mesh_term_id INTEGER NOT NULL REFERENCES mesh_terms (id),
    kind TEXT NOT NULL,
    ancestor BOOLEAN NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (trial_id, mesh_term_id, kind)
) WITHOUT ROWID;
CREATE INDEX trial_mesh_by_term ON trial_mesh (mesh_term_id, kind, trial_id);

CREATE TABLE trial_interventions (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    intervention_id INTEGER NOT NULL REFERENCES interventions (id),
    type TEXT,
    position INTEGER NOT NULL,
    PRIMARY KEY (trial_id, intervention_id)
) WITHOUT ROWID;
CREATE INDEX trial_interventions_by_intervention
    ON trial_interventions (intervention_id, trial_id);

CREATE TABLE intervention_aliases (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    intervention_id INTEGER NOT NULL REFERENCES interventions (id),
    alias TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (trial_id, intervention_id, alias)
) WITHOUT ROWID;

CREATE TABLE trial_sponsors (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    sponsor_id INTEGER NOT NULL REFERENCES sponsors (id),
    role TEXT NOT NULL,
    sponsor_class TEXT,
    position INTEGER NOT NULL,
    PRIMARY KEY (trial_id, sponsor_id)
) WITHOUT ROWID;
CREATE INDEX trial_sponsors_by_sponsor ON trial_sponsors (sponsor_id, trial_id);

CREATE TABLE trial_countries (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    country_code TEXT NOT NULL REFERENCES countries (code),
    position INTEGER NOT NULL,
    PRIMARY KEY (trial_id, country_code)
) WITHOUT ROWID;
CREATE INDEX trial_countries_by_country ON trial_countries (country_code, trial_id);

CREATE TABLE locations (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    facility TEXT,
    city TEXT,
    state TEXT,
    country_code TEXT REFERENCES countries (code),
    status TEXT,
    lat FLOAT,
    lon FLOAT,
    PRIMARY KEY (trial_id, position)
) WITHOUT ROWID;

CREATE TABLE runs (
    id INTEGER NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    checkpoint TEXT,
    summary TEXT
);

CREATE TABLE trial_changes (
    id INTEGER NOT NULL PRIMARY KEY,
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL REFERENCES runs (id),
    field TEXT NOT NULL,
    old TEXT,
    new TEXT
);
CREATE INDEX trial_changes_by_trial ON trial_changes (trial_id, run_id);

CREATE TABLE stats (
    chart_id TEXT NOT NULL PRIMARY KEY,
    data_version INTEGER NOT NULL,
    payload BLOB NOT NULL,
    computed_at TEXT NOT NULL
);

CREATE TABLE meta (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
INSERT INTO meta (key, value) VALUES ('data_version', '0');

-- What trials_fts indexes, one row per trial. FTS5 reads this view when it rebuilds, checks
-- or deletes a row, so the ORDER BYs keep each row's text identical between reads. FTS5
-- can't read virtual tables (json_each and friends) through a view, which is why outcomes
-- are rows in trial_outcomes rather than JSON.
CREATE VIEW trials_fts_content AS
SELECT
    t.id AS id,
    t.title AS title,
    t.official_title AS official_title,
    (SELECT group_concat(c.name, ' ' ORDER BY tc.position)
       FROM trial_conditions AS tc JOIN conditions AS c ON c.id = tc.condition_id
      WHERE tc.trial_id = t.id) AS conditions,
    (SELECT group_concat(i.name, ' ' ORDER BY ti.position)
       FROM trial_interventions AS ti JOIN interventions AS i ON i.id = ti.intervention_id
      WHERE ti.trial_id = t.id) AS interventions,
    (SELECT group_concat(a.alias, ' ' ORDER BY a.intervention_id, a.position)
       FROM intervention_aliases AS a
      WHERE a.trial_id = t.id) AS other_names,
    x.brief_summary AS summary,
    x.description AS description,
    x.eligibility_criteria AS eligibility,
    (SELECT group_concat(concat_ws(' ', o.measure, o.description), ' ' ORDER BY o.position)
       FROM trial_outcomes AS o
      WHERE o.trial_id = t.id) AS outcomes
FROM trials AS t
LEFT JOIN trial_text AS x ON x.trial_id = t.id;

CREATE VIRTUAL TABLE trials_fts USING fts5(
    title, official_title, conditions, interventions, other_names,
    summary, description, eligibility, outcomes,
    content = 'trials_fts_content',
    content_rowid = 'id',
    tokenize = 'porter unicode61 remove_diacritics 2'
);
-- Column weights for ORDER BY rank, in the column order above.
INSERT INTO trials_fts (trials_fts, rank)
VALUES ('rank', 'bm25(10.0, 5.0, 8.0, 8.0, 6.0, 3.0, 1.0, 1.0, 1.5)');

-- Condition, intervention and sponsor names for fuzzy lookup; ref is the row's id.
CREATE VIRTUAL TABLE names_fts USING fts5(
    name, kind UNINDEXED, ref UNINDEXED,
    tokenize = 'trigram remove_diacritics 1'
);
"""


def _trials_1(conn: Connection) -> None:
    run_script(conn, _TRIALS_1)
    conn.exec_driver_sql(
        "INSERT INTO countries (code, alpha3, name) VALUES (?, ?, ?)", list(COUNTRIES)
    )


_TRIALS_2 = """\
CREATE TABLE doc_dicts (
    id INTEGER NOT NULL PRIMARY KEY,
    dict BLOB NOT NULL,
    created_at TEXT NOT NULL
);
ALTER TABLE trial_docs ADD COLUMN dict_id INTEGER REFERENCES doc_dicts (id);
"""


def _trials_2(conn: Connection) -> None:
    """Compress raw documents with zstd instead of storing JSONB; add non-ISO countries.

    Real raw JSON is about 10 GB for 607k studies as JSONB, and about 2 GB compressed.
    Documents already stored are recompressed here without a dictionary.
    """
    run_script(conn, _TRIALS_2)
    encoder = docs.Encoder()
    rows = conn.exec_driver_sql("SELECT trial_id, json(doc) FROM trial_docs").all()
    if rows:
        conn.exec_driver_sql(
            "UPDATE trial_docs SET doc = ? WHERE trial_id = ?",
            [(encoder.encode(doc.encode()), trial_id) for trial_id, doc in rows],
        )
    conn.exec_driver_sql(
        "INSERT INTO countries (code, alpha3, name) VALUES (?, ?, ?)", list(EXTRA_COUNTRIES)
    )


_TRIALS_3 = """\
ALTER TABLE doc_dicts ADD COLUMN kind TEXT NOT NULL DEFAULT 'doc';

CREATE TABLE trial_text_3 (
    trial_id INTEGER NOT NULL PRIMARY KEY REFERENCES trials (id) ON DELETE CASCADE,
    text BLOB NOT NULL,
    dict_id INTEGER REFERENCES doc_dicts (id)
);

-- Contentless: the index keeps no copy of the text. The pipeline feeds it as it writes
-- each trial, and contentless_delete lets it drop a trial's row by rowid alone.
CREATE VIRTUAL TABLE trials_fts_3 USING fts5(
    title, official_title, conditions, interventions, other_names,
    summary, description, eligibility, outcomes,
    content = '',
    contentless_delete = 1,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
INSERT INTO trials_fts_3 (trials_fts_3, rank)
VALUES ('rank', 'bm25(10.0, 5.0, 8.0, 8.0, 6.0, 3.0, 1.0, 1.0, 1.5)');
INSERT INTO trials_fts_3 (
    rowid, title, official_title, conditions, interventions, other_names,
    summary, description, eligibility, outcomes
)
SELECT
    id, title, official_title, conditions, interventions, other_names,
    summary, description, eligibility, outcomes
FROM trials_fts_content;
"""

_TRIALS_3_SWAP = """\
DROP TABLE trials_fts;
DROP VIEW trials_fts_content;
DROP TABLE trial_outcomes;
DROP TABLE trial_text;
ALTER TABLE trial_text_3 RENAME TO trial_text;
ALTER TABLE trials_fts_3 RENAME TO trials_fts;
INSERT INTO trials_fts (trials_fts) VALUES ('optimize');
"""

_TEXT_BATCH = 5_000


def _trials_3(conn: Connection) -> None:
    """Make the full-text index contentless and keep each trial's text compressed.

    The external-content index read its text from plain copies in ``trial_text`` and
    ``trial_outcomes``, 3.8 GB at 607k trials; compressed, the text is about 1 GB. The
    index is filled from the old copies here, before they go.
    """
    run_script(conn, _TRIALS_3)
    ids = conn.exec_driver_sql("SELECT id FROM trials ORDER BY id").scalars().all()
    encoder: docs.Encoder | None = None
    for batch in itertools.batched(ids, _TEXT_BATCH, strict=False):
        low, high = batch[0], batch[-1]
        texts = {
            row[0]: row[1:]
            for row in conn.exec_driver_sql(
                "SELECT trial_id, brief_summary, description, eligibility_criteria "
                "FROM trial_text WHERE trial_id BETWEEN ? AND ?",
                (low, high),
            )
        }
        outcomes: dict[int, list[docs.PackedOutcome]] = {}
        for trial_id, kind, measure, description, time_frame in conn.exec_driver_sql(
            "SELECT trial_id, kind, measure, description, time_frame FROM trial_outcomes "
            "WHERE trial_id BETWEEN ? AND ? ORDER BY trial_id, position",
            (low, high),
        ):
            outcomes.setdefault(trial_id, []).append((kind, measure, description, time_frame))
        packed = []
        for trial_id in batch:
            summary, description, eligibility = texts.get(trial_id, (None, None, None))
            trial_text = docs.TrialText(
                summary, description, eligibility, tuple(outcomes.get(trial_id, ()))
            )
            packed.append((trial_id, trial_text.pack()))
        if encoder is None:
            encoder = docs.Encoder()
            if content := docs.train([blob for _, blob in packed]):
                dict_id = conn.exec_driver_sql(
                    "INSERT INTO doc_dicts (dict, created_at, kind) VALUES (?, ?, ?) RETURNING id",
                    (content, datetime.now(UTC).isoformat(), docs.TEXT),
                ).scalar_one()
                encoder = docs.Encoder(dict_id, content)
        conn.exec_driver_sql(
            "INSERT INTO trial_text_3 (trial_id, text, dict_id) VALUES (?, ?, ?)",
            [(trial_id, encoder.encode(blob), encoder.dict_id) for trial_id, blob in packed],
        )
    run_script(conn, _TRIALS_3_SWAP)


_APP_1 = """\
CREATE TABLE jobs (
    id INTEGER NOT NULL PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER,
    message TEXT,
    payload TEXT,
    result TEXT,
    heartbeat TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX jobs_by_status ON jobs (status, id);
CREATE UNIQUE INDEX jobs_one_running_data_job ON jobs (status)
    WHERE status = 'running' AND type IN ('install', 'update', 'rebuild');

CREATE TABLE enricher_state (
    enricher TEXT NOT NULL PRIMARY KEY,
    version TEXT NOT NULL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;
"""

_APP_2 = """\
ALTER TABLE jobs ADD COLUMN stage TEXT;
ALTER TABLE jobs ADD COLUMN unit TEXT;
ALTER TABLE jobs ADD COLUMN error TEXT;
ALTER TABLE jobs ADD COLUMN origin TEXT NOT NULL DEFAULT 'api';
ALTER TABLE jobs ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN worker TEXT;
ALTER TABLE jobs ADD COLUMN updated_at TEXT;
CREATE INDEX jobs_by_update ON jobs (updated_at);
"""

TRIALS_MIGRATIONS = (
    Migration(1, "initial trials schema", _trials_1),
    Migration(2, "compressed raw documents; Kosovo and former countries", _trials_2),
    Migration(3, "contentless full-text index; compressed trial text", _trials_3),
)
APP_MIGRATIONS = (
    Migration(1, "initial app schema", _APP_1),
    Migration(2, "job stages, errors, origin and cancelling", _APP_2),
)
