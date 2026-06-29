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
        """Tier 3 : récupère le nb de params depuis le Hub (metadata safetensors),
        puis met le résultat en cache. Import paresseux et offline-safe : lib absente,
        réseau, 404… → None (jamais d'exception, pour ne pas casser l'ingestion batch)."""
        try:
            import huggingface_hub
        except ImportError:
            return None
        if huggingface_hub is None:
            return None
        try:
            # timeout court (10s) : un Hub lent ne doit pas ralentir un batch ;
            # en cas d'échec on retombe proprement sur le tier 4 (file d'attente).
            info = huggingface_hub.model_info(model, timeout=10)
            # Garde explicite : safetensors peut être None si le repo n'a pas de fichiers .safetensors
            if info.safetensors is None:
                return None
            # safetensors.total est un compte BRUT de paramètres ; EcoLogits
            # (compute_llm_impacts) attend le nombre EN MILLIARDS, comme le
            # registre (ex. 7 pour un modèle 7B). On convertit donc /1e9.
            total = float(info.safetensors.total) / 1e9
        except Exception:
            # 404, offline, repo privé, pas de safetensors… → on échoue proprement
            return None
        if total <= 0:
            return None
        res = ParamsResult(active=total, total=total, arch="dense",
                           source="huggingface", warnings=["moe-assumed-dense"])
        self.config.model_params[f"{provider}/{model}"] = {
            "active": res.active, "total": res.total,
            "arch": res.arch, "source": res.source}
        return res
