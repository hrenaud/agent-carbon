from dataclasses import dataclass, field

from ecologits.model_repository import ParametersMoE, models
from ecologits.utils.range_value import RangeValue


@dataclass
class ParamsResult:
    active: float
    total: float
    arch: str            # "dense" | "moe"
    source: str          # "registry" | "user" | "huggingface"
    warnings: list[str] = field(default_factory=list)


def fetch_hf_params(repo: str) -> ParamsResult | None:
    """repo HF → paramètres (safetensors.total ÷ 1e9, dense). Offline-safe :
    lib absente, réseau, 404, identifiant invalide → None (jamais d'exception)."""
    try:
        import huggingface_hub
    except ImportError:
        return None
    if huggingface_hub is None:
        return None
    try:
        info = huggingface_hub.model_info(repo, timeout=10)
        if info.safetensors is None:
            return None
        # EcoLogits attend les params en milliards ; safetensors.total est un
        # compte brut → ÷ 1e9.
        total = float(info.safetensors.total) / 1e9
    except Exception:
        return None
    if total <= 0:
        return None
    return ParamsResult(active=total, total=total, arch="dense",
                        source="huggingface", warnings=["moe-assumed-dense"])


def fetch_moe_params_from_hf(repo: str, active: float) -> ParamsResult | None:
    """Même chose que fetch_hf_params mais pour un MoE : le total vient de HF,
    l'actif est fourni par l'utilisateur. Si HF échoue, retourne None."""
    try:
        import importlib
        huggingface_hub = importlib.import_module("huggingface_hub")
    except (ImportError, ValueError):
        return None
    try:
        info = huggingface_hub.model_info(repo, timeout=10)
        if info.safetensors is None:
            return None
        total = float(info.safetensors.total) / 1e9
    except Exception:
        return None
    if total <= 0:
        return None
    return ParamsResult(active=active, total=total, arch="moe", source="huggingface")


class ModelParamsResolver:
    """Résout (params actifs, totaux) pour un modèle, en cascade :
    registre EcoLogits → cache config → Hugging Face → None."""

    def __init__(self, config):
        self.config = config

    def resolve(self, provider: str, model: str) -> ParamsResult | None:
        return (
            self._from_registry(provider, model)
            or self._from_cache(provider, model)
            or self._from_huggingface(provider, model)
        )

    def _from_registry(self, provider: str, model: str) -> ParamsResult | None:
        for prov in (provider, "huggingface_hub"):
            m = models.find_model(provider=prov, model_name=model)
            if m is not None:
                p = m.architecture.parameters
                if isinstance(p, ParametersMoE):
                    return ParamsResult(active=float(p.active), total=float(p.total),
                                        arch="moe", source="registry")
                # Gérer RangeValue (min/max) en prenant la moyenne.
                # EcoLogits expose parfois une plage de paramètres quand l'architecture
                # n'est pas précisément spécifiée. On prend la valeur centrale comme
                # estimation typique ; l'incertitude dominante vient du PUE et du mix,
                # pas de la fourchette des paramètres.
                if isinstance(p, RangeValue):
                    val = (p.min + p.max) / 2.0
                else:
                    val = float(p)
                return ParamsResult(active=val, total=val,
                                    arch="dense", source="registry")
        return None

    def _from_cache(self, provider: str, model: str) -> ParamsResult | None:
        """Tier 2 : params déclarés par l'utilisateur ou résolus précédemment via HF,
        mémorisés dans la config (clé « provider/model »)."""
        entry = self.config.model_params.get(f"{provider}/{model}")
        if entry is None:
            return None
        return ParamsResult(
            active=float(entry["active"]), total=float(entry["total"]),
            arch=entry.get("arch", "dense"), source=entry.get("source", "user"))

    def _from_huggingface(self, provider: str, model: str) -> ParamsResult | None:
        """Tier 3 : params depuis le Hub via fetch_hf_params, puis mise en cache.
        arch toujours « dense » ici (fetch_hf_params suppose dense) ; l'affinage
        MoE est différé (cf. « Suite 2 » de docs/TODO-self-hosted-models.md)."""
        res = fetch_hf_params(model)
        if res is None:
            return None
        self.config.model_params[f"{provider}/{model}"] = {
            "active": res.active, "total": res.total,
            "arch": res.arch, "source": res.source}
        return res
