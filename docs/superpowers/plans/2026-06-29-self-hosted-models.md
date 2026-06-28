# Évaluation des modèles auto-hébergés — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estimer l'impact des modèles auto-hébergés (inconnus d'EcoLogits) via une chaîne registre → cache → Hugging Face → file d'attente, avec config persistée (mix, PUE/WUE) et saisie interactive différée.

**Architecture:** On garde la délégation à EcoLogits. Tier 1 reste `llm_impacts()`. En échec « model-not-registered », un `ModelParamsResolver` fournit `(active, total)` (cache config ou Hugging Face), et le moteur appelle directement la fonction bas-niveau `compute_llm_impacts()` avec ces params + le mix + un PUE/WUE en plage. Les modèles non résolus sont mis en file (`pending_models`) et renseignés via une commande interactive hors batch.

**Tech Stack:** Python ≥ 3.10, EcoLogits `0.11.0` (épinglé), `huggingface_hub` (nouveau, import paresseux), `json` + `os` (stdlib) pour la config persistée, `sqlite3` (existant), `pytest`.

## Global Constraints

- **Python ≥ 3.10, < 4** (exigé par EcoLogits).
- **Aucun modèle d'impact réécrit** : tout calcul passe par EcoLogits (`llm_impacts` ou `compute_llm_impacts`).
- **Offline-first** : le réseau n'est sollicité qu'au tier Hugging Face, uniquement pour un modèle jamais vu ; résultat caché ensuite. Toute erreur réseau/import → `None`, jamais d'exception remontée au batch.
- **Jamais de question interactive hors TTY** (hook statusline, batch d'ingestion).
- **Confidentialité** : on ne stocke que `{provider, model, tokens, ts, project, ids}` + métadonnées publiques de modèle. Jamais de contenu.
- **Persistance config** : `~/.agent-carbon/config.json` (JSON stdlib, pas de dépendance d'écriture).
- **Plages par défaut** : `datacenter_pue = RangeValue(min=1.1, max=1.5)`, `datacenter_wue = 0.0`, `electricity_mix_zone = None` (sentinelle « non renseigné »).
- **Réponses et messages utilisateur en français.**
- **TDD** : test qui échoue d'abord, puis implémentation minimale. **Commits fréquents**, format sémantique (`feat:`, `test:`, `chore:`…).

---

## Structure des fichiers

| Fichier                                        | Responsabilité                                                                                                                          |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_carbon/config.py` _(modifié)_           | Dataclass `Config` + `load()` / `save()` JSON ; nouveaux champs `datacenter_pue`, `datacenter_wue`, `model_params` ; défaut zone `None` |
| `agent_carbon/config_detect.py` _(créé)_       | Détection locale → pays → ISO-3 ; mapping alpha-2→alpha-3 ; repli liste                                                                 |
| `agent_carbon/impact/params.py` _(créé)_       | `ParamsResult`, `ModelParamsResolver` (tiers registre → cache → Hugging Face)                                                           |
| `agent_carbon/impact/engine.py` _(modifié)_    | Branchement fallback : `model-not-registered` → resolver → `compute_llm_impacts()` ; sinon signale « non résolu »                       |
| `agent_carbon/store/db.py` _(modifié)_         | Table `pending_models` ; `add_pending()`, `list_pending()`, `clear_pending()`                                                           |
| `agent_carbon/__main__.py` _(modifié)_         | Charge `Config.load()` ; sous-commande `models` ; détection mix au 1er `report` interactif                                              |
| `pyproject.toml` _(modifié)_                   | Ajoute la dépendance `huggingface_hub`                                                                                                  |
| `skills/agent-carbon-config/SKILL.md` _(créé)_ | Skill de réglage mix + PUE/WUE                                                                                                          |
| `CHANGELOG.md` _(modifié)_                     | Entrée de version                                                                                                                       |

---

### Task 1 : Config persistée (load/save JSON + nouveaux champs)

**Files:**

- Modify: `agent_carbon/config.py`
- Test: `tests/test_config_persist.py`

**Interfaces:**

- Consumes: `ecologits.utils.range_value.RangeValue`
- Produces:
  - `Config` dataclass avec champs : `electricity_mix_zone: str | None = None`, `throughput_tok_s: float = 50.0`, `model_aliases: dict[str, str]`, `datacenter_pue: RangeValue = RangeValue(min=1.1, max=1.5)`, `datacenter_wue: float = 0.0`, `model_params: dict[str, dict] = {}`, `local_wh_per_token: float | None = None`
  - `Config.load(path: str) -> Config` (fichier absent → défauts)
  - `Config.save(self, path: str) -> None`
  - constante `DEFAULT_CONFIG_PATH = os.path.expanduser("~/.agent-carbon/config.json")`

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_config_persist.py
import os
from ecologits.utils.range_value import RangeValue
from agent_carbon.config import Config


def test_defaults():
    c = Config()
    assert c.electricity_mix_zone is None
    assert c.datacenter_pue == RangeValue(min=1.1, max=1.5)
    assert c.datacenter_wue == 0.0
    assert c.model_params == {}
    assert c.throughput_tok_s == 50.0


def test_load_missing_file_returns_defaults(tmp_path):
    c = Config.load(str(tmp_path / "absent.json"))
    assert c.electricity_mix_zone is None
    assert c.model_params == {}


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    c = Config(
        electricity_mix_zone="FRA",
        datacenter_pue=RangeValue(min=1.2, max=1.2),
        datacenter_wue=0.3,
        model_params={"ollama/qwen2.5:7b": {"active": 7e9, "total": 7e9,
                                            "arch": "dense", "source": "user"}},
    )
    c.save(path)
    loaded = Config.load(path)
    assert loaded.electricity_mix_zone == "FRA"
    assert loaded.datacenter_pue == RangeValue(min=1.2, max=1.2)
    assert loaded.datacenter_wue == 0.3
    assert loaded.model_params["ollama/qwen2.5:7b"]["total"] == 7e9
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_config_persist.py -v`
Expected: FAIL (`electricity_mix_zone` vaut `"USA"`, pas de `datacenter_pue`, pas de `load`/`save`)

- [ ] **Step 3 : Réécrire `agent_carbon/config.py`**

```python
import json
import os
from dataclasses import asdict, dataclass, field

from ecologits.utils.range_value import RangeValue

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.agent-carbon/config.json")


@dataclass
class Config:
    """Constantes maison persistées dans ~/.agent-carbon/config.json."""

    electricity_mix_zone: str | None = None          # None = non renseigné
    throughput_tok_s: float = 50.0
    model_aliases: dict[str, str] = field(default_factory=dict)
    datacenter_pue: RangeValue = field(
        default_factory=lambda: RangeValue(min=1.1, max=1.5))
    datacenter_wue: float = 0.0
    model_params: dict[str, dict] = field(default_factory=dict)
    local_wh_per_token: float | None = None

    @classmethod
    def load(cls, path: str = DEFAULT_CONFIG_PATH) -> "Config":
        if not os.path.exists(path):
            return cls()
        with open(path) as fd:
            data = json.load(fd)
        pue = data.get("datacenter_pue")
        if isinstance(pue, dict):
            data["datacenter_pue"] = RangeValue(min=pue["min"], max=pue["max"])
        return cls(**data)

    def save(self, path: str = DEFAULT_CONFIG_PATH) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        data = asdict(self)
        data["datacenter_pue"] = {"min": self.datacenter_pue.min,
                                  "max": self.datacenter_pue.max}
        with open(path, "w") as fd:
            json.dump(data, fd, indent=2, ensure_ascii=False)
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/test_config_persist.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5 : Vérifier qu'on n'a rien cassé**

Run: `.venv/bin/pytest tests/test_models_config.py -v`
Expected: `test_config_defaults` échoue (il attend `electricity_mix_zone == "USA"`). Mettre à jour cette assertion vers `is None` puis relancer → PASS.

- [ ] **Step 6 : Commit**

```bash
git add agent_carbon/config.py tests/test_config_persist.py tests/test_models_config.py
git commit -m "feat: config persistée JSON (mix None, PUE/WUE en plage, cache model_params)"
```

---

### Task 2 : Détection du mix électrique (locale → ISO-3)

**Files:**

- Create: `agent_carbon/config_detect.py`
- Test: `tests/test_config_detect.py`

**Interfaces:**

- Produces:
  - `ALPHA2_TO_ALPHA3: dict[str, str]` (au moins FR→FRA, DE→DEU, US→USA, GB→GBR, BE→BEL, CH→CHE, ES→ESP, IT→ITA, CA→CAN, NL→NLD, SE→SWE, NO→NOR)
  - `detect_zone(locale_str: str | None) -> str | None` : extrait le code pays d'une locale (`"fr_FR.UTF-8"` → `"FRA"`), `None` si indétectable
  - `system_locale() -> str | None` : lit `LC_ALL`/`LC_CTYPE`/`LANG` de l'environnement

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_config_detect.py
from agent_carbon.config_detect import detect_zone, ALPHA2_TO_ALPHA3


def test_detect_zone_from_locale():
    assert detect_zone("fr_FR.UTF-8") == "FRA"
    assert detect_zone("en_US.UTF-8") == "USA"
    assert detect_zone("de_DE") == "DEU"


def test_detect_zone_unknown_country_returns_none():
    assert detect_zone("xx_ZZ.UTF-8") is None


def test_detect_zone_no_country_returns_none():
    assert detect_zone("C") is None
    assert detect_zone(None) is None


def test_mapping_covers_common_countries():
    for a3 in ("FRA", "DEU", "USA", "SWE", "NOR"):
        assert a3 in ALPHA2_TO_ALPHA3.values()
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_config_detect.py -v`
Expected: FAIL (`No module named 'agent_carbon.config_detect'`)

- [ ] **Step 3 : Créer `agent_carbon/config_detect.py`**

```python
import os
import re

# Mapping alpha-2 → alpha-3 (ISO 3166-1) pour les zones EcoLogits courantes.
ALPHA2_TO_ALPHA3 = {
    "FR": "FRA", "DE": "DEU", "US": "USA", "GB": "GBR", "BE": "BEL",
    "CH": "CHE", "ES": "ESP", "IT": "ITA", "CA": "CAN", "NL": "NLD",
    "SE": "SWE", "NO": "NOR", "PL": "POL", "CN": "CHN", "JP": "JPN",
}

_LOCALE_COUNTRY = re.compile(r"^[a-z]{2}[_-]([A-Z]{2})")


def system_locale() -> str | None:
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def detect_zone(locale_str: str | None) -> str | None:
    if not locale_str:
        return None
    m = _LOCALE_COUNTRY.match(locale_str)
    if not m:
        return None
    return ALPHA2_TO_ALPHA3.get(m.group(1))
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/test_config_detect.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5 : Commit**

```bash
git add agent_carbon/config_detect.py tests/test_config_detect.py
git commit -m "feat: détection zone mix depuis la locale système (alpha-2 → ISO-3)"
```

---

### Task 3 : `ModelParamsResolver` — tiers registre + cache

**Files:**

- Create: `agent_carbon/impact/params.py`
- Test: `tests/test_params_resolver.py`

**Interfaces:**

- Consumes: `Config.model_params` (Task 1) ; `ecologits.model_repository.models`, `ParametersMoE`
- Produces:
  - `@dataclass ParamsResult { active: float, total: float, arch: str, source: str, warnings: list[str] }`
  - `ModelParamsResolver(config)` avec `resolve(provider: str, model: str) -> ParamsResult | None`
  - méthode interne `_from_registry(provider, model) -> ParamsResult | None`
  - méthode interne `_from_cache(provider, model) -> ParamsResult | None` (clé `f"{provider}/{model}"`)
  - méthode `_from_huggingface` ajoutée en Task 4 (laisser un stub qui renvoie `None` ici)

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_params_resolver.py
from agent_carbon.config import Config
from agent_carbon.impact.params import ModelParamsResolver, ParamsResult


def test_registry_tier_resolves_known_model():
    r = ModelParamsResolver(Config())
    # gpt-4o-mini est dans le registre EcoLogits 0.11.0
    res = r.resolve("openai", "gpt-4o-mini")
    assert isinstance(res, ParamsResult)
    assert res.source == "registry"
    assert res.total > 0


def test_cache_tier_resolves_declared_model():
    cfg = Config(model_params={
        "ollama/qwen2.5:7b": {"active": 7e9, "total": 7e9,
                              "arch": "dense", "source": "user"}})
    r = ModelParamsResolver(cfg)
    res = r.resolve("ollama", "qwen2.5:7b")
    assert res.source == "user"
    assert res.total == 7e9
    assert res.active == 7e9


def test_unknown_model_returns_none():
    r = ModelParamsResolver(Config())
    assert r.resolve("ollama", "modele-inexistant-xyz") is None
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_params_resolver.py -v`
Expected: FAIL (`No module named 'agent_carbon.impact.params'`)

- [ ] **Step 3 : Créer `agent_carbon/impact/params.py`**

```python
from dataclasses import dataclass, field

from ecologits.model_repository import ParametersMoE, models


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
                return ParamsResult(active=float(p), total=float(p),
                                    arch="dense", source="registry")
        return None

    def _from_cache(self, provider: str, model: str) -> ParamsResult | None:
        entry = self.config.model_params.get(f"{provider}/{model}")
        if entry is None:
            return None
        return ParamsResult(
            active=float(entry["active"]), total=float(entry["total"]),
            arch=entry.get("arch", "dense"), source=entry.get("source", "user"))

    def _from_huggingface(self, provider: str, model: str) -> ParamsResult | None:
        return None  # implémenté en Task 4
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/test_params_resolver.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5 : Commit**

```bash
git add agent_carbon/impact/params.py tests/test_params_resolver.py
git commit -m "feat: ModelParamsResolver (tiers registre + cache config)"
```

---

### Task 4 : Tier Hugging Face (import paresseux, offline-safe, caché)

**Files:**

- Modify: `agent_carbon/impact/params.py`
- Modify: `pyproject.toml` (ajout dépendance)
- Test: `tests/test_params_huggingface.py`

**Interfaces:**

- Consumes: `huggingface_hub.model_info` (import paresseux dans la méthode)
- Produces: `ModelParamsResolver._from_huggingface(provider, model) -> ParamsResult | None` ; écrit le résultat dans `self.config.model_params` (cache)

- [ ] **Step 1 : Écrire les tests qui échouent (HF mocké, jamais de réseau réel)**

```python
# tests/test_params_huggingface.py
import sys
import types
import pytest
from agent_carbon.config import Config
from agent_carbon.impact.params import ModelParamsResolver


def _fake_hf(total, monkeypatch):
    """Injecte un faux module huggingface_hub avec model_info()."""
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def test_huggingface_dense_sets_active_equals_total(monkeypatch):
    _fake_hf(7_000_000_000, monkeypatch)
    cfg = Config()
    r = ModelParamsResolver(cfg)
    res = r.resolve("ollama", "Qwen/Qwen2.5-7B")
    assert res.source == "huggingface"
    assert res.active == res.total == 7_000_000_000
    # mis en cache
    assert "ollama/Qwen/Qwen2.5-7B" in cfg.model_params


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
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_params_huggingface.py -v`
Expected: FAIL (`_from_huggingface` renvoie toujours `None`, `source` jamais `"huggingface"`)

- [ ] **Step 3 : Implémenter `_from_huggingface` (remplace le stub)**

```python
    def _from_huggingface(self, provider: str, model: str) -> ParamsResult | None:
        try:
            import huggingface_hub
        except ImportError:
            return None
        if huggingface_hub is None:
            return None
        try:
            info = huggingface_hub.model_info(model, timeout=10)
            total = float(info.safetensors.total)
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
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/test_params_huggingface.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5 : Ajouter la dépendance**

Dans `pyproject.toml`, sous `dependencies`, ajouter la ligne après ecologits :

```toml
dependencies = [
  "ecologits @ git+https://github.com/mlco2/ecologits.git@0.11.0",
  "huggingface_hub>=0.20",
]
```

Puis installer : `.venv/bin/pip install -e .`

- [ ] **Step 6 : Commit**

```bash
git add agent_carbon/impact/params.py tests/test_params_huggingface.py pyproject.toml
git commit -m "feat: tier Hugging Face (params via safetensors, offline-safe, caché)"
```

---

### Task 5 : Branchement du moteur (fallback compute_llm_impacts)

**Files:**

- Modify: `agent_carbon/impact/engine.py`
- Test: `tests/test_engine_selfhosted.py`

**Interfaces:**

- Consumes: `ModelParamsResolver` (Task 3-4) ; `Config.datacenter_pue`, `Config.datacenter_wue` ; `ecologits.impacts.llm.compute_llm_impacts` ; `ecologits.electricity_mix_repository.electricity_mixes` ; `ecologits.tracers.utils.ImpactsOutput`
- Produces: `EcoLogitsEngine` gagne `self.params_resolver` ; `ImpactRecord` inchangé ; en non-résolu, `ImpactRecord.error = "model-params-unresolved"`

**Note d'implémentation :** EcoLogits ne _lève pas_ `ModelNotRegisteredError` — `llm_impacts()` renvoie `ImpactsOutput(errors=[...])` dont le `.code` vaut `"model-not-registered"`. C'est ce code qu'on intercepte (le bloc `if out.errors:` existant en `engine.py:58`).

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_engine_selfhosted.py
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
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_engine_selfhosted.py -v`
Expected: FAIL (le fallback n'existe pas ; `error` vaut `"model-not-registered"`, pas `"model-params-unresolved"`)

- [ ] **Step 3 : Modifier `agent_carbon/impact/engine.py`**

Ajouter les imports en tête :

```python
from ecologits.electricity_mix_repository import electricity_mixes
from ecologits.impacts.llm import compute_llm_impacts
from ecologits.tracers.utils import ImpactsOutput
from agent_carbon.impact.params import ModelParamsResolver
```

Dans `__init__`, instancier le resolver de params :

```python
    def __init__(self, resolver: ModelResolver):
        self.resolver = resolver
        self.params_resolver = None  # initialisé paresseusement avec la config
        self.methodology_version = f"engine={ENGINE_VERSION};ecologits={ecologits.__version__}"
```

Remplacer le bloc `if out.errors:` (lignes 58-64) par un branchement vers le fallback :

```python
        if out.errors:
            if out.errors[0].code == "model-not-registered":
                return self._compute_selfhosted(event, name, aliased, config)
            return ImpactRecord(
                model_resolved=name, zone=config.electricity_mix_zone,
                methodology_version=self.methodology_version,
                totals={}, usage={}, embodied={},
                warnings=[], error=out.errors[0].code,
            )
```

Ajouter la méthode `_compute_selfhosted` (le mix `None` retombe sur `"WOR"` côté EcoLogits via la zone) :

```python
    def _compute_selfhosted(self, event, name, aliased, config) -> ImpactRecord:
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
        totals = {c: _minmax(getattr(out, c)) for c in CRITERIA}
        usage = {c: _minmax(getattr(out.usage, c))
                 for c in CRITERIA if getattr(out.usage, c, None) is not None}
        embodied = {c: _minmax(getattr(out.embodied, c))
                    for c in _EMBODIED_CRITERIA
                    if getattr(out.embodied, c, None) is not None}
        warnings = list(params.warnings)
        if aliased:
            warnings.append(f"alias:{event.model}->{name}")
        return ImpactRecord(
            model_resolved=name, zone=zone,
            methodology_version=self.methodology_version,
            totals=totals, usage=usage, embodied=embodied,
            warnings=warnings, error=None,
        )
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/test_engine_selfhosted.py tests/test_engine.py -v`
Expected: PASS (nouveaux + anciens tests engine)

- [ ] **Step 5 : Commit**

```bash
git add agent_carbon/impact/engine.py tests/test_engine_selfhosted.py
git commit -m "feat: moteur — fallback auto-hébergé via compute_llm_impacts (params resolver + mix + PUE)"
```

---

### Task 6 : File d'attente `pending_models` en DB

**Files:**

- Modify: `agent_carbon/store/db.py`
- Test: `tests/test_pending_models.py`

**Interfaces:**

- Consumes: connexion sqlite existante (`SQLiteStore`)
- Produces:
  - table `pending_models(provider TEXT, model TEXT, first_seen TEXT, occurrences INTEGER, PRIMARY KEY(provider, model))`
  - `SQLiteStore.add_pending(provider: str, model: str, ts: str) -> None` (upsert : incrémente `occurrences`)
  - `SQLiteStore.list_pending() -> list[dict]` (clés : `provider, model, first_seen, occurrences`)
  - `SQLiteStore.clear_pending(provider: str, model: str) -> None`
  - appel à `add_pending` depuis `ingest()` quand `rec.error == "model-params-unresolved"`

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_pending_models.py
from agent_carbon.store.db import SQLiteStore


def test_add_and_list_pending(tmp_path):
    s = SQLiteStore(str(tmp_path / "c.db"))
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T10:00:00Z")
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T11:00:00Z")
    rows = s.list_pending()
    assert len(rows) == 1
    assert rows[0]["provider"] == "ollama"
    assert rows[0]["occurrences"] == 2
    assert rows[0]["first_seen"] == "2026-06-29T10:00:00Z"


def test_clear_pending(tmp_path):
    s = SQLiteStore(str(tmp_path / "c.db"))
    s.add_pending("ollama", "m", "2026-06-29T10:00:00Z")
    s.clear_pending("ollama", "m")
    assert s.list_pending() == []
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_pending_models.py -v`
Expected: FAIL (`add_pending` n'existe pas)

- [ ] **Step 3 : Modifier `agent_carbon/store/db.py`**

Ajouter à `_SCHEMA` (après la table `sessions`) :

```sql
CREATE TABLE IF NOT EXISTS pending_models (
  provider TEXT, model TEXT, first_seen TEXT, occurrences INTEGER DEFAULT 0,
  PRIMARY KEY (provider, model)
);
```

Ajouter les méthodes dans `SQLiteStore` :

```python
    def add_pending(self, provider: str, model: str, ts: str) -> None:
        self.conn.execute(
            "INSERT INTO pending_models (provider, model, first_seen, occurrences) "
            "VALUES (?,?,?,1) "
            "ON CONFLICT(provider, model) DO UPDATE SET occurrences = occurrences + 1",
            (provider, model, ts),
        )
        self.conn.commit()

    def list_pending(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT provider, model, first_seen, occurrences "
            "FROM pending_models ORDER BY occurrences DESC").fetchall()]

    def clear_pending(self, provider: str, model: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_models WHERE provider=? AND model=?",
            (provider, model))
        self.conn.commit()
```

Dans `ingest()`, après `self._store_impact(e, rec)`, capter le résultat pour repérer les non-résolus. Remplacer la ligne `self._store_impact(e, engine.compute(e, config))` par :

```python
            rec = engine.compute(e, config)
            self._store_impact(e, rec)
            if rec.error == "model-params-unresolved":
                self.add_pending(e.provider, e.model, e.timestamp)
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/test_pending_models.py tests/test_store.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add agent_carbon/store/db.py tests/test_pending_models.py
git commit -m "feat: file d'attente pending_models (modèles non résolus, hors batch)"
```

---

### Task 7 : CLI — config chargée + sous-commande `models` + détection mix

**Files:**

- Modify: `agent_carbon/__main__.py`
- Test: `tests/test_cli_models.py`

**Interfaces:**

- Consumes: `Config.load`/`save` (Task 1), `detect_zone`/`system_locale` (Task 2), `SQLiteStore.list_pending`/`clear_pending` (Task 6)
- Produces:
  - `Config()` → remplacé par `Config.load()` partout dans `main()`
  - nouvelle sous-commande `agent-carbon models` : liste les modèles en attente (non-TTY → liste seule ; TTY → demande params, écrit le cache, purge)
  - helper `_maybe_detect_mix(config: Config) -> None` : si `zone is None` et TTY → propose la détection et persiste

- [ ] **Step 1 : Écrire le test qui échoue (sous-commande `models`, mode non interactif)**

```python
# tests/test_cli_models.py
import io
from contextlib import redirect_stdout
from agent_carbon.store.db import SQLiteStore
from agent_carbon import __main__ as cli


def test_models_command_lists_pending(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    s = SQLiteStore(db)
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T10:00:00Z")
    # stdin non-TTY → pas de question, simple listing
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["models", "--db", db])
    out = buf.getvalue()
    assert rc == 0
    assert "qwen2.5:7b" in out
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_cli_models.py -v`
Expected: FAIL (`invalid choice: 'models'`)

- [ ] **Step 3 : Modifier `agent_carbon/__main__.py`**

Imports en tête :

```python
from agent_carbon.config import Config, DEFAULT_CONFIG_PATH
from agent_carbon.config_detect import detect_zone, system_locale
```

Remplacer `config = Config()` (ligne 72) par `config = Config.load()`.

Déclarer la sous-commande après `p_st` :

```python
    p_mod = sub.add_parser("models", help="lister/renseigner les modèles auto-hébergés non résolus")
    p_mod.add_argument("--db", default=_DEFAULT_DB)
```

Ajouter le helper de détection mix et le handler `models` :

```python
def _maybe_detect_mix(config: Config) -> None:
    if config.electricity_mix_zone is not None or not sys.stdin.isatty():
        return
    guess = detect_zone(system_locale())
    prompt = f"Zone du mix électrique [{guess or 'ex. FRA'}] : "
    answer = input(prompt).strip().upper() or (guess or "")
    if answer:
        config.electricity_mix_zone = answer
        config.save()
        print(f"Zone enregistrée : {answer}")


def _cmd_models(args) -> int:
    store = _store(args.db)
    pending = store.list_pending()
    if not pending:
        print("Aucun modèle auto-hébergé en attente.")
        return 0
    for row in pending:
        print(f"· {row['provider']}/{row['model']} "
              f"({row['occurrences']} occurrences)")
    if not sys.stdin.isatty():
        return 0
    config = Config.load()
    for row in pending:
        ans = input(f"Params totaux pour {row['model']} "
                    "(ex. 7e9, vide = ignorer) : ").strip()
        if not ans:
            continue
        total = float(ans)
        config.model_params[f"{row['provider']}/{row['model']}"] = {
            "active": total, "total": total, "arch": "dense", "source": "user"}
        store.clear_pending(row["provider"], row["model"])
    config.save()
    print("Paramètres enregistrés. Relancez `agent-carbon ingest`.")
    return 0
```

Brancher le handler dans `main()` (avant `return 1`) :

```python
    if args.cmd == "models":
        return _cmd_models(args)
```

Et appeler la détection mix au début du handler `report` (juste après `store = _store(args.db)`) :

```python
        _maybe_detect_mix(config)
```

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `.venv/bin/pytest tests/test_cli_models.py -v`
Expected: PASS

- [ ] **Step 5 : Vérifier la non-régression CLI**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS (toute la suite)

- [ ] **Step 6 : Commit**

```bash
git add agent_carbon/__main__.py tests/test_cli_models.py
git commit -m "feat: CLI — config persistée chargée, sous-commande models, détection mix au report"
```

---

### Task 8 : Skill `agent-carbon-config` + CHANGELOG

**Files:**

- Create: `skills/agent-carbon-config/SKILL.md`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Consumes: la CLI (`agent-carbon report`, `agent-carbon models`) et `~/.agent-carbon/config.json`

- [ ] **Step 1 : Créer `skills/agent-carbon-config/SKILL.md`**

```markdown
---
name: agent-carbon-config
description: Régler la configuration d'agent-carbon — zone du mix électrique, PUE et WUE de l'hébergement auto-hébergé. À utiliser quand l'utilisateur veut changer sa localisation/mix ou les hypothèses d'infrastructure.
---

# agent-carbon-config

Réglages persistés dans `~/.agent-carbon/config.json`.

## Champs

- `electricity_mix_zone` : code ISO-3 (ex. `FRA`, `DEU`, `USA`). `null` = détecté au prochain `report` interactif.
- `datacenter_pue` : plage `{min, max}` (défaut `1.1`–`1.5`). Plus bas = poste local ; plus haut = datacenter on-prem.
- `datacenter_wue` : litres d'eau par kWh (défaut `0`, local sans refroidissement eau).

## Procédure

1. Lire le fichier `~/.agent-carbon/config.json` (créer avec les défauts s'il est absent).
2. Demander à l'utilisateur la/les valeur(s) à changer.
3. Pour le mix, si l'utilisateur ne connaît pas son code, proposer une détection : `agent-carbon report` (interactif) déclenche la détection locale → ISO-3.
4. Écrire le JSON mis à jour (préserver les autres champs, notamment `model_params`).
5. Confirmer les valeurs enregistrées.

Ne jamais toucher `model_params` (cache des modèles auto-hébergés, géré par `agent-carbon models`).
```

- [ ] **Step 2 : Ajouter l'entrée CHANGELOG**

Sous la section non publiée de `CHANGELOG.md`, ajouter :

```markdown
### Ajouté

- Évaluation des modèles **auto-hébergés** : chaîne registre EcoLogits → cache → Hugging Face → file d'attente.
- Config **persistée** (`~/.agent-carbon/config.json`) : zone du mix (détectée à la 1re utilisation), PUE/WUE en plage.
- Sous-commande `agent-carbon models` pour renseigner les modèles non résolus.
- Skill `agent-carbon-config` pour régler mix et PUE/WUE.
```

- [ ] **Step 3 : Commit**

```bash
git add skills/agent-carbon-config/SKILL.md CHANGELOG.md
git commit -m "docs: skill agent-carbon-config + entrée CHANGELOG (modèles auto-hébergés)"
```

---

## Self-Review (effectuée)

**Couverture du spec :**

- Config persistée + champs → Task 1 ✓ · Détection mix → Task 2 + Task 7 ✓ · `ModelParamsResolver` tiers 1-2 → Task 3 ✓ · Tier HF → Task 4 ✓ · Moteur fallback + plage PUE → Task 5 ✓ · `pending_models` → Task 6 ✓ · Commande interactive + question différée → Task 7 ✓ · Skill `agent-carbon-config` → Task 8 ✓ · Tests de chaque tier → Tasks 1-7 ✓.

**Placeholders :** aucun — chaque step porte le code/commande réels.

**Cohérence des types :** `ParamsResult(active, total, arch, source, warnings)` identique entre Tasks 3, 4, 5 · `Config` (champs + `load`/`save`) cohérent Tasks 1/5/7 · code d'erreur `"model-params-unresolved"` identique Tasks 5/6 · clé de cache `f"{provider}/{model}"` identique Tasks 3/4/7.
