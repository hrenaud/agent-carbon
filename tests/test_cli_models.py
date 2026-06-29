import io
import sys
import types
from contextlib import redirect_stdout
from agent_carbon.store.db import SQLiteStore
from agent_carbon import __main__ as cli
from agent_carbon.config import Config


def _patch_config(monkeypatch, path):
    """Patch Config.load/save pour utiliser un fichier de config temporaire."""
    original_load = Config.load.__func__
    original_save = Config.save
    def load(cls, p=None):
        return original_load(cls, p or path)
    def save(self, p=None):
        return original_save(self, p or path)
    monkeypatch.setattr(Config, "load", classmethod(load))
    monkeypatch.setattr(Config, "save", save)


def _fake_hf(total, monkeypatch):
    """Mock huggingface_hub qui retourne un safetensors.total."""
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def test_models_command_lists_pending(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    s = SQLiteStore(db)
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T10:00:00Z")
    # stdin non-TTY → pas de question, simple listing
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])
    out = buf.getvalue()
    assert rc == 0
    assert "qwen2.5:7b" in out


def test_models_preserves_config_fields(tmp_path, monkeypatch):
    """Fix C: Ensure _cmd_models preserves electricity_mix_zone and other fields."""
    config_path = str(tmp_path / "config.json")
    db = str(tmp_path / "c.db")

    # Write initial config with electricity_mix_zone and model_params
    cfg = Config(electricity_mix_zone="FRA", model_params={"x/y": {"active": 1e9}})
    cfg.save(config_path)

    # Patch Config.load and Config.save to use our temp config path when called without args
    original_load = Config.load.__func__
    original_save = Config.save
    def patched_load(cls, path=None):
        if path is None:
            path = config_path
        return original_load(cls, path)
    def patched_save(self, path=None):
        if path is None:
            path = config_path
        return original_save(self, path)
    monkeypatch.setattr(Config, "load", classmethod(patched_load))
    monkeypatch.setattr(Config, "save", patched_save)

    # Add a pending model
    s = SQLiteStore(db)
    s.add_pending("ollama", "test:7b", "2026-06-29T10:00:00Z")

    # Simulate TTY: first input = type (empty → dense), second = total (7e9)
    inputs = iter(["", "7e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    assert rc == 0

    # Reload config directly without patches
    reloaded = Config.load(config_path)
    assert reloaded.electricity_mix_zone == "FRA", "electricity_mix_zone was lost"
    assert "x/y" in reloaded.model_params, "original model_params was lost"
    assert "ollama/test:7b" in reloaded.model_params, "new model not added"
    assert reloaded.model_params["ollama/test:7b"]["active"] == 7e9
    assert reloaded.model_params["ollama/test:7b"]["arch"] == "dense"


def test_models_bad_input_recovers(tmp_path, monkeypatch):
    """Fix D: Bad input should not crash, continue to next model."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")

    # Initial config
    cfg = Config()
    cfg.save(config_path)

    # Patch Config.load and Config.save to use our temp config path when called without args
    original_load = Config.load.__func__
    original_save = Config.save
    def patched_load(cls, path=None):
        if path is None:
            path = config_path
        return original_load(cls, path)
    def patched_save(self, path=None):
        if path is None:
            path = config_path
        return original_save(self, path)
    monkeypatch.setattr(Config, "load", classmethod(patched_load))
    monkeypatch.setattr(Config, "save", patched_save)

    # Two pending models
    s = SQLiteStore(db)
    s.add_pending("ollama", "model1", "2026-06-29T10:00:00Z")
    s.add_pending("ollama", "model2", "2026-06-29T10:00:01Z")

    # model1: type="dense", total="abc" (bad), model2: type="dense", total="7e9" (good)
    inputs = iter(["dense", "abc", "dense", "7e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    out = buf.getvalue()
    assert rc == 0, f"Command should return 0, got {rc}"
    assert "Format invalide, ignoré." in out, "Should print French error message"

    # Verify second model was saved despite first bad input
    reloaded = Config.load(config_path)
    assert "ollama/model2" in reloaded.model_params, "Second model should be saved"
    assert reloaded.model_params["ollama/model2"]["active"] == 7e9
    assert reloaded.model_params["ollama/model2"]["arch"] == "dense"


# ── Tests Suite 2 : MoE ────────────────────────────────────────────────


def test_models_dense_by_default(tmp_path, monkeypatch):
    """Teste que saisir "" (vide) → modèle dense (total=active)."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    cfg = Config()
    cfg.save(config_path)

    _patch_config(monkeypatch, config_path)

    s = SQLiteStore(db)
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T10:00:00Z")

    # type="" (dense), total="7e9"
    inputs = iter(["", "7e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    assert rc == 0
    reloaded = Config.load(config_path)
    entry = reloaded.model_params["ollama/qwen2.5:7b"]
    assert entry["arch"] == "dense"
    assert entry["active"] == 7e9
    assert entry["total"] == 7e9
    assert entry["source"] == "user"


def test_models_moe_with_cache(tmp_path, monkeypatch):
    """Teste MoE : le total vient du cache (sans HF)."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")

    # Cache contient le modèle avec params (arch=moE, total=35e9)
    cache_params = {
        "ollama/qwen3:35b-a3b": {"active": 3.5e9, "total": 35e9, "arch": "moe", "source": "user"}
    }
    cfg = Config(model_params=cache_params)
    cfg.save(config_path)

    _patch_config(monkeypatch, config_path)

    s = SQLiteStore(db)
    s.add_pending("ollama", "qwen3:35b-a3b", "2026-06-29T10:00:00Z")

    # type="moe", active="3.5e9" (notation scientifique)
    inputs = iter(["moe", "3.5e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    assert rc == 0
    reloaded = Config.load(config_path)
    entry = reloaded.model_params["ollama/qwen3:35b-a3b"]
    assert entry["arch"] == "moe"
    assert entry["active"] == 3.5e9
    # Le total vient du cache (35e9), pas de HF
    assert entry["total"] == 35e9
    assert entry["source"] == "user"


def test_models_moe_with_hf(tmp_path, monkeypatch):
    """Teste MoE : le total vient de HF (pas en cache), actif saisi."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    cfg = Config()
    cfg.save(config_path)
    _patch_config(monkeypatch, config_path)
    _fake_hf(35_000_000_000, monkeypatch)  # HF retourne total=35e9

    s = SQLiteStore(db)
    s.add_pending("ollama", "qwen3:35b-a3b", "2026-06-29T10:00:00Z")

    # type="moe", active="3.5e9" (notation scientifique)
    inputs = iter(["moe", "3.5e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    assert rc == 0
    reloaded = Config.load(config_path)
    entry = reloaded.model_params["ollama/qwen3:35b-a3b"]
    assert entry["arch"] == "moe"
    # active en unité brute (saisi par l'utilisateur)
    assert entry["active"] == 3.5e9
    # total = 35e9 / 1e9 = 35.0 (ParamsResult est en milliards, conversion HF)
    assert entry["total"] == 35.0
    assert entry["source"] == "user"
    assert "hf_repo" in entry


def test_models_moe_no_cache_no_hf(tmp_path, monkeypatch):
    """Teste MoE : ni cache ni HF → fallback (active=total)."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    cfg = Config()
    cfg.save(config_path)
    _patch_config(monkeypatch, config_path)
    # HF non disponible (module inexistant)
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)

    s = SQLiteStore(db)
    s.add_pending("ollama", "unknown:moe-model", "2026-06-29T10:00:00Z")

    # type="moe", active="3.5e9" (notation scientifique)
    inputs = iter(["moe", "3.5e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    assert rc == 0
    reloaded = Config.load(config_path)
    entry = reloaded.model_params["ollama/unknown:moe-model"]
    assert entry["arch"] == "moe"
    assert entry["active"] == 3.5e9
    # Fallback : total = active (car ni cache ni HF ne trouvables)
    assert entry["total"] == 3.5e9
    assert entry["source"] == "user"


def test_models_moe_uppercase(tmp_path, monkeypatch):
    """Teste que 'MoE' (majuscules) est reconnu comme MoE."""
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    cfg = Config()
    cfg.save(config_path)
    _patch_config(monkeypatch, config_path)

    s = SQLiteStore(db)
    s.add_pending("ollama", "test:moe", "2026-06-29T10:00:00Z")

    inputs = iter(["MoE", "3.5e9"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])

    assert rc == 0
    reloaded = Config.load(config_path)
    entry = reloaded.model_params["ollama/test:moe"]
    assert entry["arch"] == "moe"
    assert entry["active"] == 3.5e9
