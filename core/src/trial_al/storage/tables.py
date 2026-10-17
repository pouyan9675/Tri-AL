"""SQLAlchemy Core tables for ``trials.db`` and ``app.db`` (docs/design.md §6).

These describe the schema for building queries; the migrations in ``core_migrations``
create it. ``test_schema`` checks that the two agree, so change both together (with a new
migration). The full-text tables and their content view aren't here: queries on them are
plain SQL.
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BLOB,
    Boolean,
    Column,
    Dialect,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    and_,
    text,
)


class ISODate(TypeDecorator[date]):
    """A date stored as ``YYYY-MM-DD`` text, which sorts and compares correctly."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: date | None, dialect: Dialect) -> str | None:
        return None if value is None else value.isoformat()

    def process_result_value(self, value: Any | None, dialect: Dialect) -> date | None:
        return None if value is None else date.fromisoformat(value)


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime stored as ISO 8601 text in UTC."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime {value!r}; use an aware one, e.g. in UTC")
        return value.astimezone(UTC).isoformat()

    def process_result_value(self, value: Any | None, dialect: Dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)


trials_metadata = MetaData()
app_metadata = MetaData()


def _trial_id(*, primary_key: bool = False) -> Column[int]:
    return Column(
        "trial_id",
        Integer,
        ForeignKey("trials.id", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=False,
    )


def _position() -> Column[int]:
    """Where the item was in the record's list, so reads return the source's order."""
    return Column("position", Integer, nullable=False)


# --- trials.db: entities -------------------------------------------------------------------

countries = Table(
    "countries",
    trials_metadata,
    Column("code", Text, primary_key=True),  # ISO 3166-1 alpha-2
    Column("alpha3", Text),
    Column("name", Text, nullable=False),
    sqlite_with_rowid=False,
)

conditions = Table(
    "conditions",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
)

mesh_terms = Table(
    "mesh_terms",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("term", Text, nullable=False),
)

interventions = Table(
    "interventions",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
)

sponsors = Table(
    "sponsors",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
)

# --- trials.db: trials and what belongs to them ---------------------------------------------

trials = Table(
    "trials",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("source", Text, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("official_title", Text),
    Column("status", Text),
    Column("phase", Text),
    Column("study_type", Text),
    Column("primary_purpose", Text),
    Column("start_date", ISODate),
    Column("primary_completion_date", ISODate),
    Column("completion_date", ISODate),
    Column("first_posted", ISODate),
    Column("last_update", ISODate),
    Column("enrollment", Integer),
    Column("enrollment_type", Text),
    Column("arms_count", Integer),
    Column("has_results", Boolean, nullable=False),
    Column("lead_sponsor_id", Integer, ForeignKey("sponsors.id")),
    Column("lead_sponsor_class", Text),
    Column("min_age_days", Integer),
    Column("max_age_days", Integer),
    Column("sex", Text),
    Column("healthy_volunteers", Boolean),
    Column("location_scope", Text),
    Column("num_sites", Integer, nullable=False),
    Column("content_hash", BLOB),
    Column("ingested_at", UTCDateTime, nullable=False),
    UniqueConstraint("source", "source_id"),
    # (phase, status) also serves filters on phase alone.
    Index("trials_status", "status"),
    Index("trials_phase_status", "phase", "status"),
    Index("trials_start_date", "start_date"),
    Index("trials_last_update", "last_update"),
    Index("trials_lead_sponsor_class", "lead_sponsor_class"),
)

trial_text = Table(
    "trial_text",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("brief_summary", Text),
    Column("description", Text),
    Column("eligibility_criteria", Text),
)

trial_outcomes = Table(
    "trial_outcomes",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("measure", Text, nullable=False),
    Column("description", Text),
    Column("time_frame", Text),
)

doc_dicts = Table(
    "doc_dicts",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("dict", BLOB, nullable=False),  # a zstd dictionary (see storage/docs.py)
    Column("created_at", UTCDateTime, nullable=False),
)

trial_docs = Table(
    "trial_docs",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("doc", BLOB, nullable=False),  # the raw document, zstd-compressed
    Column("dict_id", Integer, ForeignKey("doc_dicts.id")),  # NULL: no dictionary
)

trial_conditions = Table(
    "trial_conditions",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("condition_id", Integer, ForeignKey("conditions.id"), primary_key=True),
    _position(),
    Index("trial_conditions_by_condition", "condition_id", "trial_id"),
    sqlite_with_rowid=False,
)

trial_mesh = Table(
    "trial_mesh",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("mesh_term_id", Integer, ForeignKey("mesh_terms.id"), primary_key=True),
    Column("kind", Text, primary_key=True),
    Column("ancestor", Boolean, nullable=False),
    _position(),
    Index("trial_mesh_by_term", "mesh_term_id", "kind", "trial_id"),
    sqlite_with_rowid=False,
)

trial_interventions = Table(
    "trial_interventions",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("intervention_id", Integer, ForeignKey("interventions.id"), primary_key=True),
    Column("type", Text),
    _position(),
    Index("trial_interventions_by_intervention", "intervention_id", "trial_id"),
    sqlite_with_rowid=False,
)

intervention_aliases = Table(
    "intervention_aliases",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("intervention_id", Integer, ForeignKey("interventions.id"), primary_key=True),
    Column("alias", Text, primary_key=True),
    _position(),
    sqlite_with_rowid=False,
)

trial_sponsors = Table(
    "trial_sponsors",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("sponsor_id", Integer, ForeignKey("sponsors.id"), primary_key=True),
    Column("role", Text, nullable=False),
    Column("sponsor_class", Text),
    _position(),
    Index("trial_sponsors_by_sponsor", "sponsor_id", "trial_id"),
    sqlite_with_rowid=False,
)

trial_countries = Table(
    "trial_countries",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("country_code", Text, ForeignKey("countries.code"), primary_key=True),
    _position(),
    Index("trial_countries_by_country", "country_code", "trial_id"),
    sqlite_with_rowid=False,
)

locations = Table(
    "locations",
    trials_metadata,
    _trial_id(primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("facility", Text),
    Column("city", Text),
    Column("state", Text),
    Column("country_code", Text, ForeignKey("countries.code")),
    Column("status", Text),
    Column("lat", Float),
    Column("lon", Float),
    sqlite_with_rowid=False,
)

# --- trials.db: runs, history, stats and bookkeeping ----------------------------------------

runs = Table(
    "runs",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", Text, nullable=False),  # install, update or rebuild
    Column("status", Text, nullable=False),
    Column("started_at", UTCDateTime, nullable=False),
    Column("finished_at", UTCDateTime),
    Column("checkpoint", Text),  # JSON: finished stages, for resuming
    Column("summary", Text),  # JSON
)

trial_changes = Table(
    "trial_changes",
    trials_metadata,
    Column("id", Integer, primary_key=True),
    _trial_id(),
    Column("run_id", Integer, ForeignKey("runs.id"), nullable=False),
    Column("field", Text, nullable=False),
    Column("old", Text),  # JSON
    Column("new", Text),  # JSON
    Index("trial_changes_by_trial", "trial_id", "run_id"),
)

stats = Table(
    "stats",
    trials_metadata,
    Column("chart_id", Text, primary_key=True),
    Column("data_version", Integer, nullable=False),
    Column("payload", BLOB, nullable=False),
    Column("computed_at", UTCDateTime, nullable=False),
)

meta = Table(
    "meta",
    trials_metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
    sqlite_with_rowid=False,
)

ENTITY_TABLES = (conditions, mesh_terms, interventions, sponsors)
LINK_TABLES = (
    trial_text,
    trial_outcomes,
    trial_docs,
    trial_conditions,
    trial_mesh,
    trial_interventions,
    intervention_aliases,
    trial_sponsors,
    trial_countries,
    locations,
)
"""Tables keyed by trial_id that an upsert replaces."""

DEFERRED_INDEXES = tuple(
    index
    for table in (trials, *ENTITY_TABLES, *LINK_TABLES)
    for index in sorted(table.indexes, key=lambda index: str(index.name))
    if not index.unique
)
"""The secondary indexes a bulk load drops first and builds once the data is in."""

# --- app.db ---------------------------------------------------------------------------------

DATA_JOB_TYPES = ("install", "update", "rebuild")

jobs = Table(
    "jobs",
    app_metadata,
    Column("id", Integer, primary_key=True),
    Column("type", Text, nullable=False),
    Column("status", Text, nullable=False),  # queued, running, succeeded, failed, cancelled
    Column("progress", Integer, nullable=False, server_default=text("0")),
    Column("total", Integer),
    Column("message", Text),
    Column("payload", Text),  # JSON
    Column("result", Text),  # JSON
    Column("heartbeat", UTCDateTime),
    Column("created_at", UTCDateTime, nullable=False),
    Column("started_at", UTCDateTime),
    Column("finished_at", UTCDateTime),
    Index("jobs_by_status", "status", "id"),
)
# Only one install, update or rebuild runs at a time (docs/design.md §5.4).
Index(
    "jobs_one_running_data_job",
    jobs.c.status,
    unique=True,
    sqlite_where=and_(jobs.c.status == "running", jobs.c.type.in_(DATA_JOB_TYPES)),
)

enricher_state = Table(
    "enricher_state",
    app_metadata,
    Column("enricher", Text, primary_key=True),
    Column("version", Text, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    sqlite_with_rowid=False,
)
