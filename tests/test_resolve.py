import sys
import types
from agent_carbon.config import Config
from agent_carbon.resolve.cli import parse_mapping, set_mappings, forget


def _fake_hf(total, monkeypatch):
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def test_parse_mapping_splits_on_first_equals():
    assert parse_mapping("anthropic/z-ai/glm:free=zai-org/GLM-4.5-Air") == (
        "anthropic/z-ai/glm:free", "zai-org/GLM-4.5-Air")


def test_set_mappings_writes_params_with_provenance(monkeypatch):
    _fake_hf(110_000_000_000, monkeypatch)
    cfg = Config()
    results = set_mappings(cfg, ["anthropic/glm:free=zai-org/GLM-4.5-Air"])
    assert results[0]["ok"] is True
    entry = cfg.model_params["anthropic/glm:free"]
    assert entry["total"] == 110.0
    assert entry["source"] == "resolve"
    assert entry["hf_repo"] == "zai-org/GLM-4.5-Air"


def test_set_mappings_reports_hf_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)  # HF indisponible
    cfg = Config()
    results = set_mappings(cfg, ["anthropic/foo=bar/baz"])
    assert results[0]["ok"] is False
    assert "anthropic/foo" not in cfg.model_params


def test_set_mappings_reports_bad_format():
    cfg = Config()
    results = set_mappings(cfg, ["pas-de-egal"])
    assert results[0]["ok"] is False
    assert results[0]["error"] == "format"


def test_forget_removes_entry():
    cfg = Config(model_params={"anthropic/glm:free": {"active": 110.0}})
    results = forget(cfg, ["anthropic/glm:free", "absent/xx"])
    assert results[0]["removed"] is True
    assert results[1]["removed"] is False
    assert "anthropic/glm:free" not in cfg.model_params
