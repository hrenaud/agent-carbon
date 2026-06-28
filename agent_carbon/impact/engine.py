import logging
from dataclasses import dataclass

import ecologits
from ecologits.tracers.utils import llm_impacts

from agent_carbon import ENGINE_VERSION
from agent_carbon.config import Config
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent

# EcoLogits émet un `logger.warning_once` par modèle inconnu / architecture non
# divulguée. En traitement de masse (ingestion), ça inonde la sortie et fait
# craindre un plantage. On muselle ce logger : l'information n'est pas perdue,
# elle reste capturée par record dans `ImpactRecord.warnings` / `.error`.
logging.getLogger("ecologits").setLevel(logging.ERROR)

CRITERIA = ("energy", "gwp", "adpe", "pe", "wcf")
_EMBODIED_CRITERIA = ("gwp", "adpe", "pe")


def _minmax(criterion) -> tuple[float, float]:
    v = criterion.value
    if hasattr(v, "min"):
        return float(v.min), float(v.max)
    return float(v), float(v)


@dataclass
class ImpactRecord:
    model_resolved: str
    zone: str
    methodology_version: str
    totals: dict[str, tuple[float, float]]
    usage: dict[str, tuple[float, float]]
    embodied: dict[str, tuple[float, float]]
    warnings: list[str]
    error: str | None


class EcoLogitsEngine:
    """Calcul d'impact offline via EcoLogits (output tokens uniquement)."""

    def __init__(self, resolver: ModelResolver):
        self.resolver = resolver
        self.methodology_version = f"engine={ENGINE_VERSION};ecologits={ecologits.__version__}"

    def compute(self, event: InferenceEvent, config: Config) -> ImpactRecord:
        name, aliased = self.resolver.resolve(event.model)
        latency = max(event.output_tokens / config.throughput_tok_s, 0.5)
        out = llm_impacts(
            provider=event.provider,
            model_name=name,
            output_token_count=event.output_tokens,
            request_latency=latency,
            electricity_mix_zone=config.electricity_mix_zone,
        )
        if out.errors:
            return ImpactRecord(
                model_resolved=name, zone=config.electricity_mix_zone,
                methodology_version=self.methodology_version,
                totals={}, usage={}, embodied={},
                warnings=[], error=out.errors[0].code,
            )
        totals = {c: _minmax(getattr(out, c)) for c in CRITERIA}
        usage = {
            c: _minmax(getattr(out.usage, c))
            for c in CRITERIA if getattr(out.usage, c, None) is not None
        }
        embodied = {
            c: _minmax(getattr(out.embodied, c))
            for c in _EMBODIED_CRITERIA if getattr(out.embodied, c, None) is not None
        }
        warnings = [w.code for w in (out.warnings or [])]
        if aliased:
            warnings.append(f"alias:{event.model}->{name}")
        return ImpactRecord(
            model_resolved=name, zone=config.electricity_mix_zone,
            methodology_version=self.methodology_version,
            totals=totals, usage=usage, embodied=embodied,
            warnings=warnings, error=None,
        )

    def compute_live(self, *args, **kwargs) -> ImpactRecord:
        """Placeholder — mode live (instrumentation SDK temps réel), hors MVP."""
        raise NotImplementedError("mode live pas encore implémenté")
