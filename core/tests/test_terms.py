"""Term analyses (``tri_al.terms``) on a small registry where every answer can be worked out.

Twelve Alzheimer's trials (two only through a narrower familial form), thirty others about
hypertension, and a second registry of sixty for the analyses that need text vectors.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tri_al import embeddings
from tri_al.api import create_app
from tri_al.api import models as m
from tri_al.config import Config
from tri_al.plugins import LoadedPlugins
from tri_al.plugins.registry import Contributions
from tri_al.schema import Intervention, MeshKind, MeshTerm, Sponsor, TrialRecord
from tri_al.stats import TrialIndex
from tri_al.storage import SQLiteReader, SQLiteStorage
from tri_al.terms import (
    Scope,
    TermTotals,
    TermVectorCache,
    attrition,
    durations,
    find_term,
    lookup_terms,
    narrower_terms,
    overview,
    pipeline,
    profile,
    readouts,
    related,
    scope_for,
    similar,
    themes,
    timeline,
)
from tri_al.terms.outcomes import reason_kind
from tri_al.terms.related import communities
from tri_al.terms.semantic import kmeans, silhouette, theme_count
from tri_al.testing.fixtures import minimal_trial

AD = MeshTerm("D000544", "Alzheimer Disease", "condition")
AD_ANCESTOR = replace(AD, ancestor=True)
FAMILIAL = MeshTerm("C000001", "Familial Alzheimer Disease", "condition")
AGITATION = MeshTerm("D011595", "Psychomotor Agitation", "condition")
DEPRESSION = MeshTerm("D003863", "Depression", "condition")
HYPERTENSION = MeshTerm("D006973", "Hypertension", "condition")
DONANEMAB = MeshTerm("C000729112", "donanemab", "intervention")
LECANEMAB = MeshTerm("C000612089", "lecanemab", "intervention")
ASPIRIN = MeshTerm("D001241", "Aspirin", "intervention")

AS_OF = date(2026, 10, 16)


def trial(source_id: str, *terms: MeshTerm, **fields: Any) -> TrialRecord:
    defaults: dict[str, Any] = {
        "source_id": source_id,
        "title": f"Trial {source_id}",
        "status": "COMPLETED",
        "phase": "PHASE2",
        "study_type": "INTERVENTIONAL",
        "start_date": date(2020, 1, 1),
        "start_date_type": "ACTUAL",
        "primary_completion_date": date(2022, 1, 1),
        "primary_completion_date_type": "ACTUAL",
        "first_posted": date(2019, 12, 1),
        "last_update": date(2025, 1, 1),
        "enrollment": 100,
        "min_age_days": 18 * 365 + 4,
        "sex": "ALL",
        "allocation": "RANDOMIZED",
        "masking": "DOUBLE",
        "mesh_terms": list(terms),
        "sponsors": [Sponsor(f"Sponsor {source_id}", "lead", "OTHER")],
        "countries": ["US"],
    }
    return replace(minimal_trial(), **{**defaults, **fields})


def alzheimers() -> list[TrialRecord]:
    return [
        trial(
            "AD1",
            AD,
            AGITATION,
            DONANEMAB,
            phase="PHASE3",
            status="RECRUITING",
            start_date=date(2025, 1, 1),
            primary_completion_date=date(2027, 3, 1),
            primary_completion_date_type="ESTIMATED",
            first_posted=date(2026, 9, 1),
            last_update=AS_OF,
            sponsors=[Sponsor("Lilly", "lead", "INDUSTRY")],
            enrollment=1800,
            min_age_days=60 * 365,
            interventions=[Intervention("Placebo")],
        ),
        trial(
            "AD2",
            AD,
            AGITATION,
            DONANEMAB,
            phase="PHASE3",
            status="TERMINATED",
            why_stopped="Stopped for futility at the interim analysis.",
            sponsors=[Sponsor("Lilly", "lead", "INDUSTRY")],
            min_age_days=60 * 365,
        ),
        trial("AD3", AD, AGITATION, DONANEMAB, min_age_days=55 * 365),
        trial(
            "AD4",
            AD,
            AGITATION,
            DONANEMAB,
            has_results=True,
            results_first_posted=date(2022, 6, 1),
            min_age_days=55 * 365,
        ),
        trial(
            "AD5",
            AD,
            DONANEMAB,
            phase="PHASE1",
            status="ACTIVE_NOT_RECRUITING",
            start_date=date(2024, 6, 1),
            primary_completion_date=date(2026, 12, 1),
            primary_completion_date_type="ESTIMATED",
            min_age_days=50 * 365,
        ),
        trial("AD6", AD, LECANEMAB, phase="PHASE3", min_age_days=50 * 365),
        trial(
            "AD7",
            AD,
            LECANEMAB,
            phase="PHASE3",
            status="WITHDRAWN",
            why_stopped="A business decision; there were no safety concerns.",
            min_age_days=50 * 365,
        ),
        trial(
            "AD8",
            AD,
            LECANEMAB,
            phase="PHASE3",
            status="RECRUITING",
            start_date=date(2023, 1, 1),
            primary_completion_date=date(2025, 1, 1),
            primary_completion_date_type="ESTIMATED",
            min_age_days=50 * 365,
        ),
        trial(
            "AD9",
            AD,
            ASPIRIN,
            phase=None,
            study_type="OBSERVATIONAL",
            allocation=None,
            masking=None,
            min_age_days=65 * 365,
        ),
        trial("AD10", FAMILIAL, AD_ANCESTOR, min_age_days=30 * 365),
        trial("AD11", FAMILIAL, AD_ANCESTOR, min_age_days=30 * 365, phase="PHASE1"),
        trial("AD12", AD, DEPRESSION, phase="PHASE4", min_age_days=50 * 365),
    ]


def others() -> list[TrialRecord]:
    trials = []
    for i in range(30):
        terms = [HYPERTENSION, *([ASPIRIN] if i < 20 else []), *([DEPRESSION] if i >= 20 else [])]
        trials.append(
            trial(
                f"HT{i}",
                *terms,
                phase=("PHASE1", "PHASE2", "PHASE3", "PHASE4")[i % 4],
                status="TERMINATED" if i % 10 == 0 else "COMPLETED",
                why_stopped="Slow accrual" if i % 10 == 0 else None,
                start_date=date(2016 + i % 8, 1, 1),
                enrollment=50,
                masking="NONE",
                min_age_days=18 * 365 + 4,
            )
        )
    return trials


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SQLiteStorage]:
    with SQLiteStorage.open(tmp_path / "data" / "trials.db") as storage:
        storage.upsert_batch(alzheimers() + others())
        yield storage


@pytest.fixture
def reader(storage: SQLiteStorage) -> Iterator[SQLiteReader]:
    with storage.read() as reader:
        yield reader


@pytest.fixture
def index(reader: SQLiteReader) -> TrialIndex:
    return TrialIndex.build(reader.connection, reader.data_version())


def scope(reader: SQLiteReader, index: TrialIndex, code: str = "D000544", **kwargs: Any) -> Scope:
    drugs = {DONANEMAB.code, LECANEMAB.code, ASPIRIN.code}
    kind: MeshKind = "intervention" if code in drugs else "condition"
    found = scope_for(reader, index, kind, code, **kwargs)
    assert found is not None
    return found


# --- finding terms -----------------------------------------------------------------------


def test_finding_terms(reader: SQLiteReader, index: TrialIndex) -> None:
    conn = reader.connection
    assert find_term(conn, "intervention", AD.code) is None  # not an intervention
    assert find_term(conn, "condition", "D999999") is None
    totals = TermTotals.read(conn, index, "condition")
    found = lookup_terms(conn, totals, "alzheimer", 10)
    # The exact name first: with the familial trials, through the ancestor, it has 12.
    assert [(t.term, t.trials) for t in found] == [
        ("Alzheimer Disease", 12),
        ("Familial Alzheimer Disease", 2),
    ]
    assert [t.code for t in lookup_terms(conn, totals, "d000544", 10)] == ["D000544"]
    assert [t.term for t in lookup_terms(conn, totals, "DEPRESS", 10)] == ["Depression"]
    # With no query, the terms most trials are tagged with themselves: Alzheimer's has 10.
    top = lookup_terms(conn, totals, None, 2)
    assert [(t.term, t.trials) for t in top] == [("Hypertension", 30), ("Depression", 11)]


def test_narrower_terms_come_through_ancestors(reader: SQLiteReader, index: TrialIndex) -> None:
    found = narrower_terms(scope(reader, index))
    # Familial AD's trials carry Alzheimer Disease as an ancestor. Agitation appears only
    # beside it, but as a term of its own, so it isn't narrower.
    assert [(t.code, t.trials) for t in found.values()] == [(FAMILIAL.code, 2)]
    assert narrower_terms(scope(reader, index, AGITATION.code)) == {}


# --- activity -----------------------------------------------------------------------------


def test_overview(reader: SQLiteReader, index: TrialIndex) -> None:
    ad = scope(reader, index)
    out = overview(ad, narrower_terms(ad))
    assert (out.trials, out.registry_trials, out.within, out.direct) == (12, 12, 42, 10)
    assert (out.active, out.completed, out.stopped) == (3, 7, 2)
    assert (out.with_results, out.industry, out.countries) == (1, 2, 1)
    assert out.lead_sponsors == 11  # Lilly twice
    assert out.as_of == AS_OF
    assert [n.term for n in out.narrower] == ["Familial Alzheimer Disease"]


def test_timeline(reader: SQLiteReader, index: TrialIndex) -> None:
    out = timeline(scope(reader, index))
    years = {year.year: year for year in out.years}
    assert min(years) == 2020
    assert max(years) == 2026
    assert out.partial
    in_2020 = years[2020]
    # Nine Alzheimer's trials started in 2020 (the others in 2023-2025), and 4 others did.
    assert in_2020.trials == 9
    assert in_2020.phases == [1, 3, 3, 1, 1]
    assert in_2020.share == pytest.approx(9 / 13, abs=1e-4)
    assert years[2025].new_sponsors == 0  # Lilly's first trial started in 2020
    assert sum(year.new_sponsors for year in out.years) == 11
    assert [w.months for w in out.momentum] == [3, 6, 12]
    assert out.momentum[0].trials == 1  # AD1, first posted in September 2026


def test_readouts(reader: SQLiteReader, index: TrialIndex) -> None:
    out = readouts(scope(reader, index))
    assert out.as_of == AS_OF
    assert [r.trial.source_id for r in out.trials] == ["AD5", "AD1"]  # soonest first
    assert all(r.estimated for r in out.trials)
    assert (out.total, out.overdue) == (2, 1)  # AD8's date has passed
    assert out.quarters[0].quarter == "2026-Q4"
    assert out.quarters[0].phases == [1, 0, 0, 0, 0]  # AD5, phase 1


# --- relations ----------------------------------------------------------------------------


def test_related_terms_by_lift(reader: SQLiteReader, index: TrialIndex) -> None:
    ad = scope(reader, index)
    out = related(ad, list(narrower_terms(ad)))
    # Agitation is only ever with Alzheimer's; the term itself and its narrower familial form
    # are left out; depression (1 of 12 against 10 of 30) is tested but less common here.
    assert [t.term for t in out.conditions] == ["Psychomotor Agitation"]
    assert [t.term for t in out.interventions] == ["donanemab", "lecanemab"]
    agitation = out.conditions[0]
    assert (agitation.trials, agitation.elsewhere) == (4, 0)
    assert agitation.lift > 1
    assert out.tested == 3  # terms on 3 or more of its trials: agitation and the two drugs
    # The network: the term first, then its related terms, joined by trials they share.
    assert [n.term for n in out.nodes] == [
        "Alzheimer Disease",
        "Psychomotor Agitation",
        "donanemab",
        "lecanemab",
    ]
    assert out.nodes[0].center
    assert out.nodes[0].group == -1
    assert [(e.source, e.target, e.trials) for e in out.edges] == [(1, 2, 4)]
    assert out.nodes[1].group == out.nodes[2].group != out.nodes[3].group


def test_communities_merge_what_goes_together() -> None:
    # Two triangles joined by one thin edge.
    edges = [(0, 1, 5.0), (1, 2, 5.0), (0, 2, 5.0), (3, 4, 5.0), (4, 5, 5.0), (3, 5, 5.0)]
    groups = communities(6, [*edges, (2, 3, 1.0)])
    assert groups[:3] == [0, 0, 0]
    assert groups[3:] == [1, 1, 1]
    assert communities(3, []) == [0, 1, 2]


def test_pipeline(reader: SQLiteReader, index: TrialIndex) -> None:
    out = pipeline(scope(reader, index))
    assert out.kind == "intervention"
    rows = {row.term: row for row in out.rows}
    donanemab = rows["donanemab"]
    assert donanemab.trials == 5
    assert dict(zip(out.phases, donanemab.phases, strict=True)) == {
        "EARLY_PHASE1": 0,
        "PHASE1": 1,
        "PHASE1_PHASE2": 0,
        "PHASE2": 2,
        "PHASE2_PHASE3": 0,
        "PHASE3": 2,
        "PHASE4": 0,
    }
    assert (donanemab.highest, donanemab.active) == ("PHASE3", 2)
    assert rows["Aspirin"].highest is None  # an observational trial
    funnel = {row.phase: row for row in out.funnel}
    assert funnel["PHASE3"].trials == 5
    assert (funnel["PHASE3"].active, funnel["PHASE3"].stopped) == (2, 2)
    assert funnel[None].trials == 1


# --- outcomes -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("Slow accrual", "enrollment"),
        ("Stopped for futility at the interim analysis.", "efficacy"),
        ("Business decision, not due to safety concerns", "decision"),
        ("Serious adverse events in two participants", "safety"),
        ("Enrollment halted by the COVID-19 pandemic", "covid"),
        ("Lack of funding", "funding"),
        ("The PI left the institution", "feasibility"),
        ("See the detailed description", "other"),
    ],
)
def test_reason_kinds(reason: str, kind: str) -> None:
    assert reason_kind(reason)[0] == kind


def test_attrition(reader: SQLiteReader, index: TrialIndex) -> None:
    out = attrition(scope(reader, index))
    phase3 = next(row for row in out.phases if row.group == "phase3")
    # Phase 3: AD2 terminated and AD7 withdrawn of AD2, AD6, AD7 (AD1, AD8 still run).
    assert (phase3.closed, phase3.stopped) == (3, 2)
    assert phase3.rate == pytest.approx(2 / 3, abs=1e-4)
    # The others' phase 3 trials are HT2, HT6, ... HT26; HT10 was terminated.
    assert phase3.baseline_closed == 7
    assert phase3.baseline_rate == pytest.approx(1 / 7, abs=1e-4)
    assert out.observed == 2
    # Phase by phase at the others' rates: phase 1, 1 trial at 2/8; phase 3, 3 at 1/7; the
    # others' phase 2 and 4 trials never stopped, and none of theirs lacks a phase.
    assert out.expected == pytest.approx(0.25 + 3 / 7, abs=0.05)
    assert {reason.key: reason.trials for reason in out.reasons} == {"efficacy": 1, "decision": 1}
    assert (out.stopped, out.read, out.stated) == (2, 2, 2)
    assert out.reasons[0].examples[0].source_id in {"AD2", "AD7"}


def test_durations(reader: SQLiteReader, index: TrialIndex) -> None:
    out = durations(scope(reader, index))
    every = next(curve for curve in out.completion if curve.group == "all")
    # Started trials, less the two stopped ones; AD1, AD5 and AD8 are still running.
    assert (every.trials, every.events) == (10, 7)
    assert every.median == pytest.approx(24.0, abs=0.1)  # 2020 to 2022
    assert [c.group for c in out.completion] == [
        "phase1",
        "phase2",
        "phase3",
        "phase4",
        "other",
        "all",
    ]
    assert out.results.trials == 7  # finished interventional trials (AD2 terminated, too)
    assert out.results.events == 1
    assert [share.months for share in out.results_at] == [12, 24, 36]


def test_profile_weights_the_baseline_to_the_terms_phases(
    reader: SQLiteReader, index: TrialIndex
) -> None:
    out = profile(scope(reader, index))
    rows = {row.key: row for row in out.rows}
    assert rows["min_age"].value == pytest.approx(50, abs=0.1)
    assert rows["min_age"].baseline == pytest.approx(18, abs=0.1)
    assert rows["min_age"].difference is not None
    assert rows["min_age"].difference > 0.8
    # The others are all open-label: none blinded, whatever the weights.
    assert rows["blinded"].baseline == 0
    assert rows["blinded"].value == 1  # all 11 interventional ones (AD9 is observational)
    assert rows["children"].value == 0  # every minimum age is 18 or over
    assert rows["placebo"].value == pytest.approx(1 / 11, abs=1e-3)
    assert out.enrollment[2].low == 51
    assert out.enrollment[2].share == pytest.approx(11 / 12, abs=1e-3)
    assert sum(b.baseline for b in out.enrollment) == pytest.approx(1)
    assert (out.trials, out.baseline_trials) == (12, 30)


def test_a_filter_narrows_the_scope(reader: SQLiteReader, index: TrialIndex) -> None:
    phase3 = index.coded("phase").values == index.coded("phase").code_of("PHASE3")
    within = index.present & phase3
    ad = scope(reader, index, within=within)
    assert overview(ad, {}).trials == 5
    assert readouts(ad).total == 1


# --- meaning: vectors ---------------------------------------------------------------------


class Engine:
    name = "fake"
    model = "designed"
    max_tokens = 64


def store_vectors(storage: SQLiteStorage, vectors: dict[str, list[float]]) -> None:
    with storage.transaction() as tx, storage.read() as reader:
        conn = tx.connection
        model = embeddings.model_for(conn, Engine(), 4)  # type: ignore[arg-type]
        ids = {source_id: reader.find_ids(source_id)[0][1] for source_id in vectors}
        embeddings.store(
            conn,
            model,
            [ids[s] for s in vectors],
            np.array(list(vectors.values()), np.float32),
        )


@pytest.fixture
def themed(tmp_path: Path) -> Iterator[SQLiteStorage]:
    """Sixty trials of one condition in two kinds, by their titles and vectors; others for
    similar terms."""
    rng = np.random.default_rng(1)
    topic = MeshTerm("D000001", "Topic", "condition")
    near = MeshTerm("D000002", "Near Topic", "condition")
    far = MeshTerm("D000003", "Far Topic", "condition")
    drug = MeshTerm("D000004", "Exercise Drug", "intervention")
    trials, vectors = [], {}
    for i in range(60):
        exercise = i % 2 == 0
        source_id = f"T{i}"
        trials.append(
            trial(
                source_id,
                topic,
                *([drug] if exercise else []),
                title=(
                    f"Aerobic exercise program walking {i}"
                    if exercise
                    else f"Antibody infusion dosing {i}"
                ),
                start_date=date(2025 if exercise else 2015, 1, 1),
            )
        )
        base = [1.0, 0.2, 0.0, 0.0] if exercise else [0.0, 0.2, 1.0, 0.0]
        vectors[source_id] = list(np.array(base) + rng.normal(0, 0.05, 4))
    for i in range(6):
        trials.append(trial(f"N{i}", near))
        vectors[f"N{i}"] = list(np.array([0.5, 0.2, 0.5, 0.0]) + rng.normal(0, 0.05, 4))
        trials.append(trial(f"F{i}", far))
        vectors[f"F{i}"] = list(np.array([0.0, -1.0, 0.0, 1.0]) + rng.normal(0, 0.05, 4))
    with SQLiteStorage.open(tmp_path / "themed" / "trials.db") as storage:
        storage.upsert_batch(trials)
        store_vectors(storage, vectors)
        yield storage


def test_themes_split_the_trials_by_meaning(themed: SQLiteStorage) -> None:
    with themed.read() as reader:
        index = TrialIndex.build(reader.connection, reader.data_version())
        topic = scope_for(reader, index, "condition", "D000001")
        assert topic is not None
        out = themes(topic, [])
    assert (out.trials, out.embedded, out.sampled) == (60, 60, 60)
    assert len(out.themes) == 2
    assert sorted(theme.size for theme in out.themes) == [30, 30]
    labels = {theme.label for theme in out.themes}
    assert any("exercise" in label or "aerobic" in label for label in labels), labels
    assert any("antibody" in label or "infusion" in label for label in labels), labels
    exercise = next(t for t in out.themes if "exercise" in t.words or "aerobic" in t.words)
    assert exercise.growth > 1  # all its trials started in 2025, the others in 2015
    assert [term.term for term in exercise.terms] == ["Exercise Drug"]
    assert len(out.points) == 60
    assert {point.cluster for point in out.points} == {0, 1}
    assert all(-2 < point.x < 2 and -2 < point.y < 2 for point in out.points)


def test_themes_need_vectors(reader: SQLiteReader, index: TrialIndex) -> None:
    out = themes(scope(reader, index), [])
    assert (out.embedded, out.themes, out.points) == (0, [], [])


def test_similar_terms_by_their_average_vector(themed: SQLiteStorage) -> None:
    with themed.read() as reader:
        index = TrialIndex.build(reader.connection, reader.data_version())
        topic = scope_for(reader, index, "condition", "D000001")
        assert topic is not None
        vectors = TermVectorCache().get(reader.connection, index)
        assert vectors is not None
        out = similar(topic, vectors, [])
    assert out.embedded == 60
    # "Near Topic" sits between the topic's two kinds of trial, "Far Topic" elsewhere.
    assert [t.term for t in out.same] == ["Near Topic", "Far Topic"]
    assert out.same[0].similarity > out.same[1].similarity
    assert (out.same[0].trials, out.same[0].shared) == (6, 0)
    assert [t.term for t in out.other] == ["Exercise Drug"]
    assert out.other[0].shared == 30


def test_kmeans_and_silhouette() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal([1, 0, 0], 0.05, (20, 3))
    b = rng.normal([0, 0, 1], 0.05, (20, 3))
    points = np.vstack([a, b]).astype(np.float32)
    points /= np.linalg.norm(points, axis=1, keepdims=True)
    labels, centres = kmeans(points, 2)
    assert len(set(labels[:20])) == 1
    assert len(set(labels[20:])) == 1
    assert labels[0] != labels[20]
    assert centres.shape == (2, 3)
    assert silhouette(points, labels) > 0.8
    assert [theme_count(n) for n in (30, 200, 1_000, 100_000)] == [2, 2, 4, 8]


# --- the API ------------------------------------------------------------------------------


@pytest.fixture
def client(storage: SQLiteStorage, tmp_path: Path) -> Iterator[TestClient]:
    config = Config.model_validate({"data": {"dir": str(tmp_path / "data")}})
    loaded = LoadedPlugins(plugins=[], settings={}, contributions=Contributions())
    app = create_app(config, loaded, config_file=tmp_path / "tri-al.toml", use_index=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


ENDPOINTS: list[tuple[str, type[m._Out]]] = [
    ("", m.TermOverviewOut),
    ("/timeline", m.TermTimelineOut),
    ("/readouts", m.TermReadoutsOut),
    ("/related", m.TermRelatedOut),
    ("/pipeline", m.TermPipelineOut),
    ("/attrition", m.TermAttritionOut),
    ("/durations", m.TermDurationsOut),
    ("/profile", m.TermProfileOut),
    ("/themes", m.TermThemesOut),
    ("/similar", m.TermSimilarOut),
]


@pytest.mark.parametrize(("path", "model"), ENDPOINTS)
def test_the_term_endpoints(client: TestClient, path: str, model: type[m._Out]) -> None:
    response = client.get(f"/api/terms/condition/D000544{path}", params={"phase": "PHASE3"})
    assert response.status_code == 200, response.text
    model.model_validate(response.json())
    etag = response.headers["etag"]
    again = client.get(
        f"/api/terms/condition/D000544{path}",
        params={"phase": "PHASE3"},
        headers={"If-None-Match": etag},
    )
    assert again.status_code == 304
    assert client.get(f"/api/terms/condition/D999999{path}").status_code == 404
    assert client.get(f"/api/terms/drug/D000544{path}").status_code == 422


def test_the_endpoints_apply_the_filter(client: TestClient) -> None:
    overview = m.TermOverviewOut.model_validate(
        client.get("/api/terms/condition/D000544", params={"phase": "PHASE3"}).json()
    )
    assert (overview.trials, overview.registry_trials) == (5, 12)
    pipeline = m.TermPipelineOut.model_validate(
        client.get("/api/terms/intervention/C000729112/pipeline").json()
    )
    assert pipeline.kind == "condition"
    assert {row.term for row in pipeline.rows} == {"Alzheimer Disease", "Psychomotor Agitation"}


def test_finding_terms_endpoint(client: TestClient) -> None:
    found = m.TermsOut.model_validate(
        client.get("/api/terms", params={"kind": "condition", "q": "alz"}).json()
    )
    assert [t.code for t in found.terms] == ["D000544", "C000001"]
    top = m.TermsOut.model_validate(
        client.get("/api/terms", params={"kind": "intervention", "limit": 1}).json()
    )
    assert [t.term for t in top.terms] == ["Aspirin"]
    assert client.get("/api/terms", params={"kind": "sponsor"}).status_code == 422
    assert client.get("/api/terms").status_code == 422
