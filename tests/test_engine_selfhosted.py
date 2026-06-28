from ecologits.utils.range_value import RangeValue
from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent


def _event(provider, model):
    return InferenceEvent(
        provider=provider, model=model, input_tokens=100, output_tokens=200,
        cache_creation_tokens=0, cache_read_tokens=0,
        timestamp="2026-06-29T10:00:00Z", project="p",
        session_id="s", msg_id="m")


def test_selfhosted_cached_model_is_computed():
    cfg = Config(
        electricity_mix_zone="FRA",
        model_params={"ollama/qwen2.5:7b": {
            "active": 7e9, "total": 7e9, "arch": "dense", "source": "user"}})
    eng = EcoLogitsEngine(ModelResolver({}))
    rec = eng.compute(_event("ollama", "qwen2.5:7b"), cfg)
    assert rec.error is None
    assert rec.totals["gwp"][0] > 0
    assert rec.zone == "FRA"


def test_pue_range_propagates_to_minmax():
    cfg = Config(
        electricity_mix_zone="FRA",
        datacenter_pue=RangeValue(min=1.0, max=2.0),
        model_params={"ollama/m": {"active": 7e9, "total": 7e9,
                                   "arch": "dense", "source": "user"}})
    eng = EcoLogitsEngine(ModelResolver({}))
    rec = eng.compute(_event("ollama", "m"), cfg)
    gmin, gmax = rec.totals["gwp"]
    assert gmax > gmin  # la plage PUE produit une fourchette


def test_unresolved_model_reports_error():
    cfg = Config(electricity_mix_zone="FRA")
    eng = EcoLogitsEngine(ModelResolver({}))
    rec = eng.compute(_event("ollama", "modele-totalement-inconnu-xyz"), cfg)
    assert rec.error == "model-params-unresolved"
