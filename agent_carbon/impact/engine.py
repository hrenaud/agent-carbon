import logging
from dataclasses import dataclass

import ecologits
from ecologits.electricity_mix_repository import electricity_mixes
from ecologits.impacts.llm import compute_llm_impacts
from ecologits.tracers.utils import llm_impacts, ImpactsOutput

from agent_carbon import ENGINE_VERSION
from agent_carbon.config import Config
from agent_carbon.impact.params import ModelParamsResolver
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


def _extract_impacts(out: ImpactsOutput) -> tuple[dict, dict, dict]:
    """Extrait les impacts totaux, usage et embodied d'un ImpactsOutput.

    Retourne (totals, usage, embodied) où chaque dict mappe critère → (min, max).
    """
    totals = {c: _minmax(getattr(out, c)) for c in CRITERIA}
    usage = {
        c: _minmax(getattr(out.usage, c))
        for c in CRITERIA if getattr(out.usage, c, None) is not None
    }
    embodied = {
        c: _minmax(getattr(out.embodied, c))
        for c in _EMBODIED_CRITERIA if getattr(out.embodied, c, None) is not None
    }
    return totals, usage, embodied


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
        self.params_resolver = None  # initialisé paresseusement avec la config
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
            if out.errors[0].code == "model-not-registered":
                return self._compute_selfhosted(event, name, aliased, config)
            return ImpactRecord(
                model_resolved=name, zone=config.electricity_mix_zone,
                methodology_version=self.methodology_version,
                totals={}, usage={}, embodied={},
                warnings=[], error=out.errors[0].code,
            )
        totals, usage, embodied = _extract_impacts(out)
        warnings = [w.code for w in (out.warnings or [])]
        if aliased:
            warnings.append(f"alias:{event.model}->{name}")
        return ImpactRecord(
            model_resolved=name, zone=config.electricity_mix_zone,
            methodology_version=self.methodology_version,
            totals=totals, usage=usage, embodied=embodied,
            warnings=warnings, error=None,
        )

    def _compute_selfhosted(self, event: InferenceEvent, name: str, aliased: bool,
                             config: Config) -> ImpactRecord:
        """Fallback pour modèles auto-hébergés : résout params et appelle compute_llm_impacts directement."""
        if self.params_resolver is None:
            self.params_resolver = ModelParamsResolver(config)
        params = self.params_resolver.resolve(event.provider, name)
        zone = config.electricity_mix_zone or "WOR"
        if params is None:
            return ImpactRecord(
                model_resolved=name, zone=zone,
                methodology_version=self.methodology_version,
                totals={}, usage={}, embodied={},
                warnings=[], error="model-params-unresolved",
            )
        mix = electricity_mixes.find_electricity_mix(zone=zone)
        latency = max(event.output_tokens / config.throughput_tok_s, 0.5)
        impacts = compute_llm_impacts(
            model_active_parameter_count=params.active,
            model_total_parameter_count=params.total,
            output_token_count=event.output_tokens,
            request_latency=latency,
            if_electricity_mix_adpe=mix.adpe, if_electricity_mix_pe=mix.pe,
            if_electricity_mix_gwp=mix.gwp, if_electricity_mix_wue=mix.wue,
            datacenter_pue=config.datacenter_pue,
            datacenter_wue=config.datacenter_wue,
        )
        out = ImpactsOutput.model_validate(impacts.model_dump())
        totals, usage, embodied = _extract_impacts(out)
        warnings = list(params.warnings)
        if aliased:
            warnings.append(f"alias:{event.model}->{name}")
        return ImpactRecord(
            model_resolved=name, zone=zone,
            methodology_version=self.methodology_version,
            totals=totals, usage=usage, embodied=embodied,
            warnings=warnings, error=None,
        )

    def compute_live(self, *args, **kwargs) -> ImpactRecord:
        """Placeholder — mode live (instrumentation SDK temps réel), hors MVP."""
        raise NotImplementedError("mode live pas encore implémenté")
