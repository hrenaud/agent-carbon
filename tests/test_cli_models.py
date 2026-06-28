import io
from contextlib import redirect_stdout
from agent_carbon.store.db import SQLiteStore
from agent_carbon import __main__ as cli
from agent_carbon.config import Config


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

    # Simulate TTY and input "7e9"
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "7e9")

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

    # First input "abc" (bad), second "7e9" (good)
    inputs = iter(["abc", "7e9"])
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
