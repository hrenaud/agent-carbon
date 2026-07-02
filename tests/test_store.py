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
    assert d["gwp_max"] >= d["gwp_min"] > 0  # bornes exposées (vue détaillée)


def test_intensity_by_model_filters_by_since(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1", active_seconds=3600.0),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-28T10:00:00.000Z", "p", "s", "u2", active_seconds=3600.0),
    ]
    store.ingest(events, _engine(), Config())
    # sans filtre : les 2 events agrégés (2 h, 1200 tokens)
    assert store.intensity_by_model()[0]["tokens"] == 1200
    # avec since : seul le 2e event compte
    data = store.intensity_by_model(since="2026-06-28T00:00:00.000Z")
    assert len(data) == 1
    assert data[0]["tokens"] == 600
    assert abs(data[0]["hours"] - 1.0) < 0.01


def test_intensity_excludes_events_without_active_time(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),  # active_seconds=0
    ]
    store.ingest(events, _engine(), Config())
    assert store.intensity_by_model() == []


def test_intensity_by_client(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s1", "u1",
                       active_seconds=3600.0, client="claude-code"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 300, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s2", "u2",
                       active_seconds=1800.0, client="opencode"),
    ]
    store.ingest(events, _engine(), Config())
    data = store.intensity_by_client()
    assert len(data) == 2
    by_client = {d["client"]: d for d in data}
    assert abs(by_client["claude-code"]["hours"] - 1.0) < 0.01
    assert by_client["claude-code"]["tokens"] == 600
    assert abs(by_client["opencode"]["hours"] - 0.5) < 0.01
    assert by_client["opencode"]["tokens"] == 300
    assert by_client["claude-code"]["gwp"] > 0
    assert by_client["claude-code"]["gwp_max"] >= by_client["claude-code"]["gwp_min"] > 0


def test_intensity_by_client_filters_by_since(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s1", "u1",
                       active_seconds=3600.0, client="claude-code"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 400, 0, 0,
                       "2026-06-28T10:00:00.000Z", "p", "s2", "u2",
                       active_seconds=3600.0, client="claude-code"),
    ]
    store.ingest(events, _engine(), Config())
    assert store.intensity_by_client()[0]["tokens"] == 1000
    data = store.intensity_by_client(since="2026-06-28T00:00:00.000Z")
    assert len(data) == 1
    assert data[0]["tokens"] == 400


def test_intensity_by_client_excludes_events_without_active_time(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 600, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1", client="claude-code"),
    ]
    store.ingest(events, _engine(), Config())
    assert store.intensity_by_client() == []


def test_tokens_by_model_sums_all_token_types(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    # input 100 + output 200 + cache_creation 50 + cache_read 30 = 380 par event
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 50, 30,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 50, 30,
                       "2026-06-27T11:00:00.000Z", "p", "s", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    data = store.tokens_by_model()
    assert len(data) == 1
    d = data[0]
    assert d["model"] == "claude-opus-4-8"
    assert d["tokens"] == 760  # 380 × 2
    assert d["gwp"] > 0
    # bornes min–max exposées (pour la vue détaillée), centrale encadrée
    assert d["gwp_max"] >= d["gwp_min"] > 0
    assert d["gwp_min"] <= d["gwp"] <= d["gwp_max"]


def test_tokens_by_model_filters_by_since(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-28T10:00:00.000Z", "p", "s", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    data = store.tokens_by_model(since="2026-06-28T00:00:00.000Z")
    assert len(data) == 1
    assert data[0]["tokens"] == 300  # seul le 2e event (100+200)


def test_tokens_by_model_since_accepts_date_only(tmp_path):
    # une date seule « YYYY-MM-DD » filtre correctement les timestamps « …T…Z »
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T23:59:00.000Z", "p", "s", "u1"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-28T00:00:01.000Z", "p", "s", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    data = store.tokens_by_model(since="2026-06-28")
    assert len(data) == 1
    assert data[0]["tokens"] == 300  # seul l'event du 28 (100+200)


def test_uncovered_by_model_excludes_synthetic_sums_output(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        # placeholder interne Claude Code : à ignorer (0 token, aucune inférence)
        InferenceEvent("anthropic", "<synthetic>", 0, 0, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),
        # vrai modèle tiers non modélisé (le « : » fait échouer HF sans réseau)
        InferenceEvent("openrouter", "z-ai/glm-4.5-air:free", 100, 200, 0, 0,
                       "2026-06-27T10:05:00.000Z", "p", "s", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    data = store.uncovered_by_model()
    assert len(data) == 1  # le <synthetic> est exclu
    assert data[0]["model"] == "z-ai/glm-4.5-air:free"
    assert data[0]["tokens"] == 200  # tokens générés (sortie)


def test_coverage_excludes_synthetic(tmp_path):
    """Les placeholders <synthetic> (0 token) ne comptent ni dans le total ni dans
    les non couverts : le compte reste cohérent avec la liste des modèles concernés."""
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),
        InferenceEvent("openrouter", "z-ai/glm-4.5-air:free", 100, 200, 0, 0,
                       "2026-06-27T10:05:00.000Z", "p", "s", "u2"),
        InferenceEvent("anthropic", "<synthetic>", 0, 0, 0, 0,
                       "2026-06-27T10:10:00.000Z", "p", "s", "u3"),
    ]
    store.ingest(events, _engine(), Config())
    cov = store.coverage()
    assert cov["total"] == 2       # <synthetic> exclu
    assert cov["measured"] == 1    # opus mesuré
    assert cov["uncovered"] == 1   # glm non couvert ; <synthetic> non compté


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


def test_client_persisted_and_in_report(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    events = [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "projA", "sess-A", "u1",
                       client="claude-code"),
    ]
    store.ingest(events, _engine(), Config())
    assert store.rows_for_report()[0]["client"] == "claude-code"


def test_client_backfilled_on_reingest(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    # 1re ingestion sans client (event historique)
    e = InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "projA", "sess-A", "u1")
    store.ingest([e], _engine(), Config())
    assert store.rows_for_report()[0]["client"] == ""
    # ré-ingestion du même event avec client → backfill
    import dataclasses
    store.ingest([dataclasses.replace(e, client="claude-code")], _engine(), Config())
    assert store.rows_for_report()[0]["client"] == "claude-code"


def test_impact_columns_persisted(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    store.ingest(_events(), _engine(), Config())
    row = store.rows_for_report(None)[0]
    assert row["gwp_min"] > 0 and row["gwp_max"] >= row["gwp_min"]
    assert row["wcf_max"] > 0


def test_recompute_errors_resolves_after_params_added(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    # « x:y » : le « : » fait échouer HF sans réseau → event en erreur
    events = [
        InferenceEvent("ollama", "x:y", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),
        InferenceEvent("anthropic", "<synthetic>", 0, 0, 0, 0,
                       "2026-06-27T10:01:00.000Z", "p", "s", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    assert store.coverage()["uncovered"] == 1  # <synthetic> non compté
    cfg = Config(electricity_mix_zone="FRA",
                 model_params={"ollama/x:y": {
                     "active": 7.0, "total": 7.0, "arch": "dense",
                     "source": "resolve", "hf_repo": "Org/Repo"}})
    delta = store.recompute_errors(_engine(), cfg)
    assert delta["before"] == 1 and delta["after"] == 0   # x:y résolu, <synthetic> jamais compté
    assert delta.get("recomputed") == 1  # 1 event recalculé (x:y)
    covered = [r for r in store.rows_for_report() if r["model"] == "x:y"]
    assert covered and covered[0]["gwp_min"] > 0


def test_mark_model_events_error_targets_only_that_model(tmp_path):
    """Teste que mark_model_events_error n'affecte QUE les events de la paire
    (provider, model), même si d'autres modèles partagent session_id ou msg_id."""
    store = SQLiteStore(str(tmp_path / "c.db"))
    cfg = Config(electricity_mix_zone="FRA", model_params={
        "ollama/A": {"active": 7.0, "total": 7.0, "arch": "dense", "source": "user"},
        "ollama/B": {"active": 7.0, "total": 7.0, "arch": "dense", "source": "user"}})
    # A a deux events ; B partage une session ET un msg_id avec A, mais pas la PAIRE.
    events = [
        InferenceEvent("ollama", "A", 100, 200, 0, 0, "2026-06-27T10:00:00Z", "p", "s1", "mA1"),
        InferenceEvent("ollama", "A", 100, 200, 0, 0, "2026-06-27T10:01:00Z", "p", "s2", "mA2"),
        InferenceEvent("ollama", "B", 100, 200, 0, 0, "2026-06-27T10:02:00Z", "p", "s1", "mA2"),
    ]
    store.ingest(events, _engine(), cfg)
    assert store.coverage()["uncovered"] == 0          # les 3 couverts
    store.mark_model_events_error("ollama", "A", "model-params-reset")
    # seuls les 2 events de A repassent en erreur ; B (s1, mA2) reste couvert
    assert store.coverage()["uncovered"] == 2
    assert {r["model"] for r in store.rows_for_report()} == {"B"}


def test_estimated_param_models_lists_models_with_estimation_warnings(tmp_path):
    """M2c : les modèles dont les params sont estimés (taille de fichiers)
    ressortent pour être signalés dans le rapport."""
    import json as _json
    from agent_carbon.store.db import SQLiteStore
    store = SQLiteStore(str(tmp_path / "t.db"))
    store.conn.execute(
        "INSERT INTO events VALUES ('s1','m1','ollama','est-model',1,2,0,0,"
        "'2026-07-02T00:00:00+00:00','p',0,'')")
    store.conn.execute(
        "INSERT INTO impacts VALUES ('s1','m1','est-model','WOR','v',"
        "1,2,1,2,1,2,1,2,1,2,'{}',?,NULL)",
        (_json.dumps(["params-from-cli-used_storage", "params-bytes-per-param:0.5"]),))
    store.conn.execute(
        "INSERT INTO events VALUES ('s1','m2','openai','gpt-4o-mini',1,2,0,0,"
        "'2026-07-02T00:00:00+00:00','p',0,'')")
    store.conn.execute(
        "INSERT INTO impacts VALUES ('s1','m2','gpt-4o-mini','WOR','v',"
        "1,2,1,2,1,2,1,2,1,2,'{}','[]',NULL)")
    store.conn.commit()
    assert store.estimated_param_models() == ["est-model"]


def test_ingest_normalizes_timestamp_to_utc_canonical(tmp_path):
    """N2 : un timestamp « Z » est stocké en ISO UTC canonique (+00:00)."""
    from agent_carbon.store.db import SQLiteStore, _canonical_ts
    assert _canonical_ts("2026-07-02T10:00:00Z") == "2026-07-02T10:00:00+00:00"
    assert _canonical_ts("2026-07-02T12:00:00+02:00") == "2026-07-02T10:00:00+00:00"
    assert _canonical_ts("pas-une-date") == "pas-une-date"  # laissé tel quel


def test_open_migrates_legacy_z_timestamps(tmp_path):
    """N2 : à l'ouverture, les vieux timestamps « …Z » sont convertis en +00:00."""
    import sqlite3
    from agent_carbon.store.db import SQLiteStore
    db = str(tmp_path / "t.db")
    s = SQLiteStore(db)
    s.conn.execute(
        "INSERT INTO events VALUES ('s1','m1','p','mod',1,2,0,0,"
        "'2026-07-02T10:00:00Z','proj',0,'')")
    s.conn.execute(
        "INSERT INTO sessions VALUES ('s1','proj','2026-07-02T10:00:00Z','2026-07-02T11:00:00Z')")
    s.conn.commit()
    s.conn.close()
    s2 = SQLiteStore(db)  # la migration tourne à l'ouverture
    ts = s2.conn.execute("SELECT timestamp FROM events").fetchone()[0]
    assert ts == "2026-07-02T10:00:00+00:00"
    row = s2.conn.execute("SELECT started_at, ended_at FROM sessions").fetchone()
    assert row[0].endswith("+00:00") and row[1].endswith("+00:00")
