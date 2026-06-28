from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine, ImpactRecord, CRITERIA
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent


def _event(model, out=1000):
    return InferenceEvent("anthropic", model, 100, out, 0, 0,
                          "2026-06-27T10:00:00Z", "projA", "s1", "m1")


def test_compute_returns_five_positive_ranges():
    eng = EcoLogitsEngine(ModelResolver({}))
    rec = eng.compute(_event("claude-opus-4-8"), Config())
    assert rec.error is None
    for c in CRITERIA:
        lo, hi = rec.totals[c]
        assert hi >= lo > 0
    assert rec.zone is None
    assert "ecologits=" in rec.methodology_version


def test_unknown_model_yields_error_not_crash():
    eng = EcoLogitsEngine(ModelResolver({}))
    rec = eng.compute(_event("claude-does-not-exist"), Config())
    assert rec.error is not None
    assert rec.totals == {}


def test_alias_is_recorded_in_warnings():
    eng = EcoLogitsEngine(ModelResolver({"claude-x": "claude-opus-4-8"}))
    rec = eng.compute(_event("claude-x"), Config())
    assert rec.error is None
    assert any(w.startswith("alias:") for w in rec.warnings)
