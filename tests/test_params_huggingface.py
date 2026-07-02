import sys
import types
import pytest
from agent_carbon.config import Config
from agent_carbon.impact.params import ModelParamsResolver, fetch_hf_params


def test_huggingface_failure_not_retried_same_run(monkeypatch):
    """M1a : un échec HF n'est pas retenté dans le même run (cache négatif mémoire)."""
    import agent_carbon.impact.params as params_mod
    call_count = [0]
    mod = types.ModuleType("huggingface_hub")
    def boom(repo_id, **kw):
        call_count[0] += 1
        raise OSError("offline")
    mod.model_info = boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    # Neutraliser les méthodes 2 et 3 (CLI hf, index.json) : on ne compte que la cascade.
    monkeypatch.setattr(params_mod, "_fetch_hf_cli_info", lambda repo: None)
    monkeypatch.setattr(params_mod, "_fetch_safetensors_index_bytes", lambda repo: None)
    r = ModelParamsResolver(Config())
    assert r.resolve("ollama", "org/inconnu") is None
    assert r.resolve("ollama", "org/inconnu") is None
    assert call_count[0] == 1  # 2e resolve court-circuité par le cache négatif


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


def _hf_counting(monkeypatch):
    """Faux huggingface_hub qui compte les appels et échoue toujours."""
    import agent_carbon.impact.params as params_mod
    call_count = [0]
    mod = types.ModuleType("huggingface_hub")
    def boom(repo_id, **kw):
        call_count[0] += 1
        raise OSError("offline")
    mod.model_info = boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    monkeypatch.setattr(params_mod, "_fetch_hf_cli_info", lambda repo: None)
    monkeypatch.setattr(params_mod, "_fetch_safetensors_index_bytes", lambda repo: None)
    return call_count


def test_negative_cache_fresh_entry_skips_hf(monkeypatch):
    """M1b : une entrée négative récente (config) court-circuite la cascade."""
    from datetime import datetime, timezone
    call_count = _hf_counting(monkeypatch)
    cfg = Config(hf_unresolved={
        "ollama/org/x": datetime.now(timezone.utc).isoformat()})
    r = ModelParamsResolver(cfg)
    assert r.resolve("ollama", "org/x") is None
    assert call_count[0] == 0  # jamais tenté


def test_negative_cache_stale_entry_retries_hf(monkeypatch):
    """M1b : une entrée négative plus vieille que le TTL est retentée."""
    from datetime import datetime, timedelta, timezone
    call_count = _hf_counting(monkeypatch)
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    cfg = Config(hf_unresolved={"ollama/org/x": stale})
    r = ModelParamsResolver(cfg)
    assert r.resolve("ollama", "org/x") is None
    assert call_count[0] == 1  # retenté, et l'horodatage est rafraîchi
    assert cfg.hf_unresolved["ollama/org/x"] != stale


def test_negative_cache_cleared_on_success(monkeypatch):
    """M1b : une résolution réussie retire l'entrée négative."""
    _fake_hf(7_000_000_000, monkeypatch)
    cfg = Config(hf_unresolved={"ollama/Qwen/Qwen2.5-7B": "2020-01-01T00:00:00+00:00"})
    r = ModelParamsResolver(cfg)
    res = r.resolve("ollama", "Qwen/Qwen2.5-7B")
    assert res is not None
    assert "ollama/Qwen/Qwen2.5-7B" not in cfg.hf_unresolved
