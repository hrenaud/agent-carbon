import io
import json
import sys
import types
from contextlib import redirect_stdout
from agent_carbon import __main__ as cli
from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent
from agent_carbon.store.db import SQLiteStore


def _engine():
    return EcoLogitsEngine(ModelResolver({}))


def _fake_hf(total, monkeypatch):
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def _patch_config(monkeypatch, path):
    original_load = Config.load.__func__
    original_save = Config.save
    def load(cls, p=None):
        return original_load(cls, p or path)
    def save(self, p=None):
        return original_save(self, p or path)
    monkeypatch.setattr(Config, "load", classmethod(load))
    monkeypatch.setattr(Config, "save", save)


def _ingest_error_event(db):
    s = SQLiteStore(db)
    s.ingest([InferenceEvent("ollama", "x:y", 100, 200, 0, 0,
              "2026-06-27T10:00:00.000Z", "p", "s", "u1")],
             _engine(), Config(electricity_mix_zone="FRA"))
    return s


def test_resolve_list_json(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    _patch_config(monkeypatch, str(tmp_path / "config.json"))
    _ingest_error_event(db)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["resolve", "--db", db, "--list", "--json"])
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data[0]["model"] == "x:y"
    assert data[0]["tokens"] == 200


def test_resolve_set_recompute_covers_model(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    Config(electricity_mix_zone="FRA").save(config_path)
    _patch_config(monkeypatch, config_path)
    _ingest_error_event(db)                      # HF réel : x:y invalide → erreur
    assert SQLiteStore(db).coverage()["uncovered"] == 1
    _fake_hf(7_000_000_000, monkeypatch)         # mock pour le --set
    with redirect_stdout(io.StringIO()):
        rc = cli.main(["resolve", "--db", db, "--set", "ollama/x:y=Org/Repo"])
    assert rc == 0
    assert SQLiteStore(db).coverage()["uncovered"] == 0
    reloaded = Config.load(config_path)
    assert reloaded.model_params["ollama/x:y"]["source"] == "resolve"
    assert reloaded.model_params["ollama/x:y"]["hf_repo"] == "Org/Repo"


def test_resolve_forget_reverts(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    Config(electricity_mix_zone="FRA").save(config_path)
    _patch_config(monkeypatch, config_path)
    _ingest_error_event(db)
    _fake_hf(7_000_000_000, monkeypatch)
    with redirect_stdout(io.StringIO()):
        cli.main(["resolve", "--db", db, "--set", "ollama/x:y=Org/Repo"])
    assert SQLiteStore(db).coverage()["uncovered"] == 0
    # HF indisponible → le recompute du forget ne peut pas re-résoudre x:y
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with redirect_stdout(io.StringIO()):
        rc = cli.main(["resolve", "--db", db, "--forget", "ollama/x:y"])
    assert rc == 0
    assert SQLiteStore(db).coverage()["uncovered"] == 1
    assert "ollama/x:y" not in Config.load(config_path).model_params


def test_resolve_forget_only_affects_target_model(tmp_path, monkeypatch):
    """Teste que --forget n'affecte que le modèle oublié, même quand deux
    modèles coexistent et partagent des (session_id, msg_id) de manière croisée."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    Config(electricity_mix_zone="FRA").save(config_path)
    _patch_config(monkeypatch, config_path)

    # Ingère deux modèles non couverts
    store = SQLiteStore(db)
    store.ingest([
        InferenceEvent("ollama", "ModelA", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s1", "mA1"),
        InferenceEvent("ollama", "ModelA", 100, 200, 0, 0,
                       "2026-06-27T10:01:00.000Z", "p", "s2", "mA2"),
        InferenceEvent("ollama", "ModelB", 100, 200, 0, 0,
                       "2026-06-27T10:02:00.000Z", "p", "s1", "mA2"),
    ], _engine(), Config(electricity_mix_zone="FRA"))
    assert store.coverage()["uncovered"] == 3  # tous en erreur

    # Mock HF pour le --set
    _fake_hf(7_000_000_000, monkeypatch)

    # Set params pour A et B → tous couverts
    with redirect_stdout(io.StringIO()):
        cli.main(["resolve", "--db", db, "--set", "ollama/ModelA=Org/RepoA"])
    with redirect_stdout(io.StringIO()):
        cli.main(["resolve", "--db", db, "--set", "ollama/ModelB=Org/RepoB"])
    assert SQLiteStore(db).coverage()["uncovered"] == 0

    # Forget ModelA, mais HF est now unavailable pour recompute
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with redirect_stdout(io.StringIO()):
        cli.main(["resolve", "--db", db, "--forget", "ollama/ModelA"])

    # Vérification : ModelA uncovered, ModelB covered
    store = SQLiteStore(db)
    uncovered_models = {r["model"] for r in store.uncovered_by_model()}
    assert uncovered_models == {"ModelA"}, f"Expected only ModelA uncovered, got {uncovered_models}"
