"""The change log: which tracked fields an update changed (``trial_changes``, design §6).

It replaces v1's ``simple_history`` and its ``first_*`` fields: a field's value when the
trial was first seen is the ``old`` of its earliest change, or its current value if it
never changed. New trials get no rows.
"""

import json
from datetime import date
from typing import Any

from tri_al.schema import TrialRecord, without_repeats

TRACKED_FIELDS = (
    "title",
    "status",
    "phase",
    "study_type",
    "primary_purpose",
    "start_date",
    "primary_completion_date",
    "completion_date",
    "enrollment",
    "enrollment_type",
    "arms_count",
    "has_results",
    "lead_sponsor",
    "min_age_days",
    "max_age_days",
    "sex",
    "healthy_volunteers",
    "conditions",
    "interventions",
    "countries",
    "num_sites",
)
"""What the change log records. ``last_update`` changes with every version, so it isn't."""


def tracked(record: TrialRecord) -> dict[str, Any]:
    """The record's tracked fields as JSON-ready values (dates as ISO text, lists as lists).

    Repeated list items are dropped first, since storage drops them too.
    """
    record = without_repeats(record)
    lead = record.lead_sponsor
    values: dict[str, Any] = {
        name: getattr(record, name)
        for name in TRACKED_FIELDS
        if name not in {"lead_sponsor", "conditions", "interventions", "countries"}
    }
    values |= {
        "lead_sponsor": None if lead is None else lead.name,
        "conditions": record.conditions,
        "interventions": [i.name for i in record.interventions],
        "countries": record.countries,
    }
    return {
        name: value.isoformat() if isinstance(value := values[name], date) else value
        for name in TRACKED_FIELDS
    }


def changes(old: TrialRecord, new: TrialRecord) -> list[tuple[str, str | None, str | None]]:
    """``(field, old, new)`` for each tracked field that differs, values as JSON text."""
    before, after = tracked(old), tracked(new)
    return [
        (name, _json(before[name]), _json(after[name]))
        for name in TRACKED_FIELDS
        if before[name] != after[name]
    ]


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)
