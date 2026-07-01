import json
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


def _fetch_safetensors_index_bytes(repo: str) -> int | None:
    """Récupère la taille totale des fichiers safetensors d'un repo HF via le
    model.safetensors.index.json. Retourne None en cas d'échec."""
    try:
        import urllib.request
        index_url = f"https://huggingface.co/{repo}/resolve/main/model.safetensors.index.json"
        req = urllib.request.Request(index_url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        index_data = json.loads(resp.read())
        
        # Extraire les noms de fichiers uniques du weight_map
        weight_map = index_data.get("weight_map", {})
        files = sorted(set(weight_map.values()))
        
        # Calculer la taille totale via HEAD requests
        base_url = f"https://huggingface.co/{repo}/resolve/main/"
        total_bytes = 0
        for f in files:
            try:
                file_url = base_url + f
                req = urllib.request.Request(file_url, method="HEAD")
                resp = urllib.request.urlopen(req, timeout=10)
                size = int(resp.headers.get("Content-Length", 0))
                total_bytes += size
            except Exception:
                continue
        
        return total_bytes if total_bytes > 0 else None
    except Exception:
        return None


def _bytes_to_params_estimated(total_bytes: int) -> float:
    """Estime le nombre de paramètres depuis la taille totale des fichiers.
    Hypothèse : 4-bit quantized = 0.5 byte/paramètre (valeur par défaut).
    Retourne les params en milliards."""
    # 4-bit = 0.5 byte par paramètre
    return (total_bytes / 0.5) / 1e9


def _fetch_hf_cli_info(repo: str) -> dict | None:
    """Récupère les infos d'un repo HF via le CLI `hf models info`.
    Retourne le dict d'info ou None en cas d'échec.
    
    Cherche le binaire dans : PATH, ou venv actif (./venv/bin/hf)."""
    try:
        import subprocess
        import shutil
        import os
        import sys
        
        hf_path = None
        
        # 1. Chercher dans le PATH
        hf_path = shutil.which("hf")
        
        # 2. Chercher dans le venv actif (sys.executable → ./venv/bin/hf)
        if hf_path is None and sys.executable:
            # sys.executable = ".../.venv/bin/pythonX.Y" → "./venv/bin/hf"
            candidate = os.path.join(
                os.path.dirname(os.path.dirname(sys.executable)),
                "bin", "hf"
            )
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                hf_path = candidate
        
        # 3. Fallback : répertoires courants connus
        if hf_path is None:
            for base in [os.getcwd(), os.path.expanduser("~/.agent-carbon/src")]:
                candidate = os.path.join(base, ".venv", "bin", "hf")
                if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                    hf_path = candidate
                    break
        
        if hf_path is None:
            return None
            
        result = subprocess.run(
            [hf_path, "models", "info", repo],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        pass
    return None


def fetch_hf_params(repo: str) -> ParamsResult | None:
    """repo HF → paramètres (safetensors.total ÷ 1e9, dense). Offline-safe :
    lib absente, réseau, 404, identifiant invalide → None (jamais d'exception).
    
    Gère les cas où le metadata HF ne popule pas safetensors mais où les fichiers
    existent (ex: modèles GGUF avec index safetensors, ou modèles récents)."""
    try:
        import huggingface_hub
    except ImportError:
        return None
    if huggingface_hub is None:
        return None
    
    # Méthode 1 : metadata HF standard (safetensors.total)
    try:
        info = huggingface_hub.model_info(repo, timeout=10)
        if info.safetensors is not None:
            total = float(info.safetensors.total) / 1e9
            if total > 0:
                return ParamsResult(active=total, total=total, arch="dense",
                                    source="huggingface", warnings=["moe-assumed-dense"])
    except Exception:
        pass
    
    # Méthode 2 : CLI `hf models info` (used_storage → params estimés 4bit)
    cli_info = _fetch_hf_cli_info(repo)
    if cli_info is not None:
        used_storage = cli_info.get("used_storage", 0)
        if used_storage and used_storage > 0:
            total = _bytes_to_params_estimated(used_storage)
            if total > 0:
                return ParamsResult(active=total, total=total, arch="dense",
                                    source="huggingface", 
                                    warnings=["moe-assumed-dense", "params-from-cli-used_storage"])
    
    # Méthode 3 : fichiers safetensors via index.json (fallback final)
    total_bytes = _fetch_safetensors_index_bytes(repo)
    if total_bytes is not None and total_bytes > 0:
        total = _bytes_to_params_estimated(total_bytes)
        if total > 0:
            return ParamsResult(active=total, total=total, arch="dense",
                                source="huggingface", 
                                warnings=["moe-assumed-dense", "params-estimated-4bit"])
    
    return None


def fetch_moe_params_from_hf(repo: str, active: float) -> ParamsResult | None:
    """Même chose que fetch_hf_params mais pour un MoE : le total vient de HF,
    l'actif est fourni par l'utilisateur. Si HF échoue, retourne None.
    
    Gère les cas où le metadata HF ne popule pas safetensors mais où les fichiers
    existent (ex: modèles GGUF avec index safetensors, ou modèles récents)."""
    try:
        import importlib
        huggingface_hub = importlib.import_module("huggingface_hub")
    except (ImportError, ValueError):
        return None
    
    # Méthode 1 : metadata HF standard (safetensors.total)
    try:
        info = huggingface_hub.model_info(repo, timeout=10)
        if info.safetensors is not None:
            total = float(info.safetensors.total) / 1e9
            if total > 0:
                return ParamsResult(active=active, total=total, arch="moe", source="huggingface")
    except Exception:
        pass
    
    # Méthode 2 : CLI `hf models info` (used_storage → params estimés 4bit)
    cli_info = _fetch_hf_cli_info(repo)
    if cli_info is not None:
        used_storage = cli_info.get("used_storage", 0)
        if used_storage and used_storage > 0:
            total = _bytes_to_params_estimated(used_storage)
            if total > 0:
                return ParamsResult(active=active, total=total, arch="moe", source="huggingface",
                                    warnings=["params-from-cli-used_storage"])
    
    # Méthode 3 : fichiers safetensors via index.json (fallback final)
    total_bytes = _fetch_safetensors_index_bytes(repo)
    if total_bytes is not None and total_bytes > 0:
        total = _bytes_to_params_estimated(total_bytes)
        if total > 0:
            return ParamsResult(active=active, total=total, arch="moe", source="huggingface",
                                warnings=["params-estimated-4bit"])
    
    return None


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
