from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent
from agent_carbon.store.db import SQLiteStore


def _events():
    return [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 287, 0, 0,
                       "2026-06-27T10:00:00.000Z", "projA", "sess-A", "u1"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:10:00.000Z", "projA", "sess-A", "u2"),
    ]


def _engine():
    return EcoLogitsEngine(ModelResolver({}))


def test_ingest_is_idempotent(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    n1 = store.ingest(_events(), _engine(), Config())
    n2 = store.ingest(_events(), _engine(), Config())  # rejoue
    assert n1 == 2
    assert n2 == 0  # aucun nouveau
    assert len(store.rows_for_report(None)) == 2


def test_session_duration_computed(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    store.ingest(_events(), _engine(), Config())
    assert store.session_count() == 1
    assert store.total_duration_seconds() == 600.0  # 10 min entre u1 et u2


def test_intensity_by_model(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    # 1 h de temps actif (3600 s), 600 tokens de sortie
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1", active_seconds=3600.0),
    ]
    store.ingest(events, _engine(), Config())
    data = store.intensity_by_model()
    assert len(data) == 1
    d = data[0]
    assert d["model"] == "claude-opus-4-8"
    assert abs(d["hours"] - 1.0) < 0.01
    assert d["tokens"] == 600
    assert d["gwp"] > 0


def test_intensity_excludes_events_without_active_time(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),  # active_seconds=0
    ]
    store.ingest(events, _engine(), Config())
    assert store.intensity_by_model() == []


def test_rows_for_report_filters_by_session(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "projA", "sess-A", "u1"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T11:00:00.000Z", "projB", "sess-B", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    assert len(store.rows_for_report()) == 2
    only_a = store.rows_for_report(session_id="sess-A")
    assert len(only_a) == 1
    assert only_a[0]["project"] == "projA"


def test_impact_columns_persisted(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    store.ingest(_events(), _engine(), Config())
    row = store.rows_for_report(None)[0]
    assert row["gwp_min"] > 0 and row["gwp_max"] >= row["gwp_min"]
    assert row["wcf_max"] > 0
