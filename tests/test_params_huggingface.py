import sys
import types
import pytest
from agent_carbon.config import Config
from agent_carbon.impact.params import ModelParamsResolver, fetch_hf_params


def _fake_hf(total, monkeypatch):
    """Injecte un faux module huggingface_hub avec model_info()."""
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def test_huggingface_dense_sets_active_equals_total(monkeypatch):
    # safetensors.total est un compte BRUT (7 milliards) ; EcoLogits attend
    # le nb de params EN MILLIARDS → ParamsResult doit valoir 7.0, pas 7e9.
    _fake_hf(7_000_000_000, monkeypatch)
    cfg = Config()
    r = ModelParamsResolver(cfg)
    res = r.resolve("ollama", "Qwen/Qwen2.5-7B")
    assert res.source == "huggingface"
    assert res.active == res.total == 7.0
    # mis en cache, en milliards
    assert cfg.model_params["ollama/Qwen/Qwen2.5-7B"]["total"] == 7.0


def test_huggingface_network_error_returns_none(monkeypatch):
    mod = types.ModuleType("huggingface_hub")
    def boom(repo_id, **kw):
        raise OSError("offline")
    mod.model_info = boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    r = ModelParamsResolver(Config())
    assert r.resolve("ollama", "whatever") is None


def test_huggingface_missing_lib_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    r = ModelParamsResolver(Config())
    assert r.resolve("ollama", "whatever") is None


def test_huggingface_cache_hit_avoids_second_call(monkeypatch):
    """Vérifie que après un premier resolve (cache + HF),
    un second resolve pour la même clé retourne le résultat en cache
    sans relancer l'appel HF."""
    call_count = [0]

    def model_info_callable(repo_id, **kw):
        call_count[0] += 1
        if call_count[0] > 1:
            raise AssertionError("model_info should not be called twice for cached entry")
        return types.SimpleNamespace(safetensors=types.SimpleNamespace(total=7_000_000_000))

    mod = types.ModuleType("huggingface_hub")
    mod.model_info = model_info_callable
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)

    cfg = Config()
    r = ModelParamsResolver(cfg)

    # Premier resolve: appelle HF, met en cache
    res1 = r.resolve("ollama", "Qwen/Qwen2.5-7B")
    assert res1 is not None
    assert res1.source == "huggingface"
    assert res1.total == 7.0  # 7e9 brut → 7 milliards
    assert call_count[0] == 1

    # Deuxième resolve: doit lire le cache, pas rappeler model_info
    res2 = r.resolve("ollama", "Qwen/Qwen2.5-7B")
    assert res2 is not None
    assert res2.source == "huggingface"  # Source depuis le cache (écrit par HF)
    assert res2.total == 7.0
    assert call_count[0] == 1  # Pas d'appel supplémentaire


def test_huggingface_total_zero_returns_none(monkeypatch):
    """Vérifie que si safetensors.total == 0, resolve retourne None
    et rien n'est mis en cache."""
    _fake_hf(0, monkeypatch)
    cfg = Config()
    r = ModelParamsResolver(cfg)
    res = r.resolve("ollama", "EmptyModel")
    assert res is None
    assert "ollama/EmptyModel" not in cfg.model_params


def test_fetch_hf_params_returns_billions(monkeypatch):
    _fake_hf(7_000_000_000, monkeypatch)
    res = fetch_hf_params("Org/Repo")
    assert res is not None
    assert res.active == res.total == 7.0
    assert res.arch == "dense"
    assert res.source == "huggingface"


def test_fetch_hf_params_missing_lib_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    assert fetch_hf_params("Org/Repo") is None


def test_fetch_hf_params_no_safetensors_returns_none(monkeypatch):
    import types as _t
    mod = _t.ModuleType("huggingface_hub")
    mod.model_info = lambda repo_id, **kw: _t.SimpleNamespace(safetensors=None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    assert fetch_hf_params("Org/Repo") is None
