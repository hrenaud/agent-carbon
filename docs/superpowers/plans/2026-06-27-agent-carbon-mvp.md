# agent-carbon MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un compteur d'impact environnemental vendor-neutral et multi-critères qui parse les transcripts Claude Code (JSONL), calcule l'impact via EcoLogits en offline, stocke dans une DB SQLite, et restitue un rapport CLI + une statusline.

**Architecture:** Pipeline `JSONL → ClaudeCodeCollector → InferenceEvent[] → EcoLogitsEngine (offline) → SQLiteStore → rapport CLI / statusline`. Le cœur est vendor-neutral ; le spécifique outil (Claude Code) et cible (statusline) vit dans des adaptateurs derrière des interfaces. On ne réécrit aucun modèle d'impact : EcoLogits le fournit.

**Tech Stack:** Python ≥ 3.10, stdlib en priorité (`json`, `sqlite3`, `argparse`, `dataclasses`, `glob`), EcoLogits épinglé sur le tag git `mlco2/ecologits@0.11.0`, pytest pour les tests.

## Global Constraints

- **Runtime** : Python ≥ 3.10 (`requires-python = ">=3.10,<4"`, exigé par EcoLogits 0.11.0).
- **Dépendance d'impact** : EcoLogits via `git+https://github.com/mlco2/ecologits.git@0.11.0` — pas la version PyPI 0.8.2 (qui n'a ni l'eau ni les modèles récents). Aucun autre moteur d'impact n'est écrit.
- **Offline strict** : aucun appel réseau dans le pipeline (ni SDK, ni API REST `api.ecologits.ai`, ni clé). EcoLogits est appelé en local via `llm_impacts(...)`.
- **5 critères** : `energy` (kWh), `gwp` (kgCO₂eq), `adpe` (kgSbeq), `pe` (MJ), `wcf` (L) — chacun en fourchette `RangeValue(min, max)`.
- **Impact piloté par les tokens de sortie uniquement** : `llm_impacts` ne consomme que `output_token_count`. input/cache sont collectés et stockés (complétude/audit) mais n'entrent pas dans le calcul.
- **Confidentialité** : on ne stocke que `{model, tokens, timestamp, project, ids}` — jamais de contenu de prompt/réponse.
- **Zone élec par défaut** : `USA` (configurable). `request_latency` estimée `= output_tokens / 50` (débit tok/s configurable), plancher 0.5 s.
- **Réponses & docs en français. TDD. `trash` au lieu de `rm`. Simplicité d'abord (stdlib avant dépendance).**

---

## File Structure

```
pyproject.toml                        # métadonnées, dep EcoLogits pin, script console
README.md                             # présentation + sources d'inspiration (Task 10)
docs/ARCHITECTURE.md                  # doc technique du fonctionnement (Task 10)
agent_carbon/
  __init__.py                         # __version__, ENGINE_VERSION
  config.py                           # Config (zone, débit, alias)
  models.py                           # InferenceEvent
  collectors/
    __init__.py
    base.py                           # Collector (ABC)
    claude_code.py                    # ClaudeCodeCollector (parse JSONL)
    stubs.py                          # CodexCollector, LocalInferenceCollector (NotImplementedError)
  impact/
    __init__.py
    resolver.py                       # ModelResolver (table d'alias)
    engine.py                         # EcoLogitsEngine, ImpactRecord
  store/
    __init__.py
    db.py                             # SQLiteStore (events / impacts / sessions, ingestion idempotente)
  report/
    __init__.py
    cli.py                            # rendu du rapport (par modèle / projet / total)
  statusline/
    __init__.py
    line.py                           # ligne compacte
  __main__.py                         # CLI argparse: ingest / report / statusline
tests/
  fixtures/sample.jsonl               # transcript JSONL réduit (structure réelle)
  test_ecologits_offline.py
  test_models_config.py
  test_claude_code_collector.py
  test_resolver.py
  test_engine.py
  test_store.py
  test_report.py
  test_statusline.py
  test_cli_end_to_end.py
```

---

## Task 1: Scaffolding + verrou du moteur EcoLogits offline

**Files:**

- Create: `pyproject.toml`
- Create: `agent_carbon/__init__.py`
- Test: `tests/test_ecologits_offline.py`

**Interfaces:**

- Consumes: rien.
- Produces: package `agent_carbon` installable ; `agent_carbon.__version__` (str), `agent_carbon.ENGINE_VERSION` (int) ; environnement Python ≥ 3.10 avec EcoLogits 0.11.0 importable.

- [ ] **Step 1: Écrire `pyproject.toml`**

```toml
[project]
name = "agent-carbon"
version = "0.1.0"
description = "Compteur d'impact environnemental multi-critères pour outils d'IA agentique (vendor-neutral, via EcoLogits)"
requires-python = ">=3.10,<4"
dependencies = [
  "ecologits @ git+https://github.com/mlco2/ecologits.git@0.11.0",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
agent-carbon = "agent_carbon.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["agent_carbon*"]
```

- [ ] **Step 2: Écrire `agent_carbon/__init__.py`**

```python
"""agent-carbon — compteur d'impact multi-critères pour l'IA agentique."""

__version__ = "0.1.0"
ENGINE_VERSION = 1
```

- [ ] **Step 3: Créer le venv (Python ≥ 3.10) et installer**

Run :

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Expected: installation réussie, y compris `ecologits` depuis le tag git (peut prendre 1–2 min).

- [ ] **Step 4: Écrire le test de non-régression du spike fondateur**

`tests/test_ecologits_offline.py` :

```python
from ecologits.tracers.utils import llm_impacts

CRITERIA = ("energy", "gwp", "adpe", "pe", "wcf")


def _minmax(criterion):
    v = criterion.value
    return (float(v.min), float(v.max)) if hasattr(v, "min") else (float(v), float(v))


def test_offline_call_returns_five_criteria_for_current_claude_model():
    out = llm_impacts(
        provider="anthropic",
        model_name="claude-opus-4-8",
        output_token_count=1000,
        request_latency=20.0,
        electricity_mix_zone="USA",
    )
    assert out.errors is None
    for name in CRITERIA:
        lo, hi = _minmax(getattr(out, name))
        assert hi >= lo > 0, f"{name} doit être une fourchette positive"
```

- [ ] **Step 5: Lancer le test**

Run: `pytest tests/test_ecologits_offline.py -v`
Expected: PASS (verrouille le fait que le pin EcoLogits fournit bien les 5 critères offline).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml agent_carbon/__init__.py tests/test_ecologits_offline.py
git commit -m "feat: scaffolding + test de non-régression EcoLogits offline (5 critères)"
```

---

## Task 2: `InferenceEvent` et `Config`

**Files:**

- Create: `agent_carbon/models.py`
- Create: `agent_carbon/config.py`
- Test: `tests/test_models_config.py`

**Interfaces:**

- Consumes: rien.
- Produces:
  - `InferenceEvent` (dataclass frozen) avec champs `provider:str, model:str, input_tokens:int, output_tokens:int, cache_creation_tokens:int, cache_read_tokens:int, timestamp:str, project:str, session_id:str, msg_id:str`.
  - `Config` (dataclass) : `electricity_mix_zone:str="USA"`, `throughput_tok_s:float=50.0`, `model_aliases:dict[str,str]={}`, `local_wh_per_token:float|None=None` (placeholder).

- [ ] **Step 1: Écrire le test**

`tests/test_models_config.py` :

```python
from agent_carbon.models import InferenceEvent
from agent_carbon.config import Config


def test_inference_event_holds_normalized_fields():
    e = InferenceEvent(
        provider="anthropic", model="claude-opus-4-8",
        input_tokens=8427, output_tokens=287,
        cache_creation_tokens=7052, cache_read_tokens=8020,
        timestamp="2026-06-27T10:08:45.619Z", project="agent-carbon",
        session_id="sess-1", msg_id="uuid-1",
    )
    assert e.output_tokens == 287
    assert e.session_id == "sess-1"


def test_config_defaults():
    c = Config()
    assert c.electricity_mix_zone == "USA"
    assert c.throughput_tok_s == 50.0
    assert c.model_aliases == {}
    assert c.local_wh_per_token is None
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_models_config.py -v`
Expected: FAIL (`ModuleNotFoundError: agent_carbon.models`).

- [ ] **Step 3: Écrire `agent_carbon/models.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceEvent:
    """Un message d'inférence normalisé, neutre vis-à-vis de l'outil source."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    timestamp: str          # ISO 8601 UTC
    project: str
    session_id: str
    msg_id: str             # unique par message → clé d'idempotence
```

- [ ] **Step 4: Écrire `agent_carbon/config.py`**

```python
from dataclasses import dataclass, field


@dataclass
class Config:
    """Constantes maison — source de vérité unique."""

    electricity_mix_zone: str = "USA"          # zone ISO pour EcoLogits
    throughput_tok_s: float = 50.0             # débit pour estimer request_latency
    model_aliases: dict[str, str] = field(default_factory=dict)
    local_wh_per_token: float | None = None    # placeholder inférence locale (hors MVP)
```

- [ ] **Step 5: Lancer le test (passe)**

Run: `pytest tests/test_models_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_carbon/models.py agent_carbon/config.py tests/test_models_config.py
git commit -m "feat: modèle InferenceEvent et Config"
```

---

## Task 3: `Collector` (ABC) + `ClaudeCodeCollector` + stubs

**Files:**

- Create: `agent_carbon/collectors/__init__.py`
- Create: `agent_carbon/collectors/base.py`
- Create: `agent_carbon/collectors/claude_code.py`
- Create: `agent_carbon/collectors/stubs.py`
- Create: `tests/fixtures/sample.jsonl`
- Test: `tests/test_claude_code_collector.py`

**Interfaces:**

- Consumes: `InferenceEvent` (Task 2).
- Produces:
  - `Collector` (ABC) avec `provider:str` et méthode abstraite `collect() -> Iterator[InferenceEvent]`.
  - `ClaudeCodeCollector(root: str)` ; `root` = répertoire des JSONL (`~/.claude/projects`). `collect()` parcourt `**/*.jsonl`, ne retient que `type=="assistant"` avec `message.usage`, dérive `project` du champ `cwd` (basename, défaut `"unknown"`), `msg_id` = `uuid` de la ligne.
  - `CodexCollector`, `LocalInferenceCollector` : stubs dont `collect()` lève `NotImplementedError`.

- [ ] **Step 1: Créer la fixture `tests/fixtures/sample.jsonl`**

(Structure réelle réduite : une ligne user — ignorée, deux lignes assistant — comptées, dont une autre session.)

```json
{"type":"user","message":{"role":"user","content":"hi"},"sessionId":"sess-A","uuid":"u0","cwd":"/Users/me/DEV/projA","timestamp":"2026-06-27T10:00:00.000Z"}
{"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":8427,"output_tokens":287,"cache_creation_input_tokens":7052,"cache_read_input_tokens":8020}},"sessionId":"sess-A","uuid":"u1","cwd":"/Users/me/DEV/projA","timestamp":"2026-06-27T10:08:45.619Z"}
{"type":"assistant","message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":1200,"output_tokens":540,"cache_creation_input_tokens":0,"cache_read_input_tokens":300}},"sessionId":"sess-B","uuid":"u2","cwd":"/Users/me/DEV/projB","timestamp":"2026-06-27T11:00:00.000Z"}
```

- [ ] **Step 2: Écrire le test**

`tests/test_claude_code_collector.py` :

```python
from pathlib import Path
from agent_carbon.collectors.claude_code import ClaudeCodeCollector
from agent_carbon.collectors.stubs import CodexCollector
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_only_assistant_messages_with_usage():
    events = list(ClaudeCodeCollector(str(FIXTURES)).collect())
    assert len(events) == 2  # la ligne user est ignorée


def test_event_fields_mapped_from_real_structure():
    events = {e.msg_id: e for e in ClaudeCodeCollector(str(FIXTURES)).collect()}
    e = events["u1"]
    assert e.provider == "anthropic"
    assert e.model == "claude-opus-4-8"
    assert e.output_tokens == 287
    assert e.cache_read_tokens == 8020
    assert e.cache_creation_tokens == 7052
    assert e.project == "projA"          # basename de cwd
    assert e.session_id == "sess-A"


def test_stub_collector_raises():
    with pytest.raises(NotImplementedError):
        list(CodexCollector().collect())
```

- [ ] **Step 3: Lancer le test (échoue)**

Run: `pytest tests/test_claude_code_collector.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Écrire `agent_carbon/collectors/base.py`**

```python
from abc import ABC, abstractmethod
from collections.abc import Iterator

from agent_carbon.models import InferenceEvent


class Collector(ABC):
    """Transforme une source spécifique à un outil en InferenceEvent normalisés."""

    provider: str = ""

    @abstractmethod
    def collect(self) -> Iterator[InferenceEvent]:
        ...
```

- [ ] **Step 5: Écrire `agent_carbon/collectors/claude_code.py`**

```python
import glob
import json
import os
from collections.abc import Iterator

from agent_carbon.collectors.base import Collector
from agent_carbon.models import InferenceEvent


def _project_from_cwd(cwd: str) -> str:
    return os.path.basename(cwd.rstrip("/")) or "unknown"


class ClaudeCodeCollector(Collector):
    provider = "anthropic"

    def __init__(self, root: str):
        self.root = os.path.expanduser(root)

    def collect(self) -> Iterator[InferenceEvent]:
        pattern = os.path.join(self.root, "**", "*.jsonl")
        for path in glob.glob(pattern, recursive=True):
            yield from self._parse_file(path)

    def _parse_file(self, path: str) -> Iterator[InferenceEvent]:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage")
                if not usage:
                    continue
                yield InferenceEvent(
                    provider=self.provider,
                    model=msg.get("model", ""),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    timestamp=obj.get("timestamp", ""),
                    project=_project_from_cwd(obj.get("cwd", "")),
                    session_id=obj.get("sessionId", ""),
                    msg_id=obj.get("uuid", ""),
                )
```

- [ ] **Step 6: Écrire `agent_carbon/collectors/stubs.py`**

```python
from collections.abc import Iterator

from agent_carbon.collectors.base import Collector
from agent_carbon.models import InferenceEvent


class CodexCollector(Collector):
    """Placeholder — à implémenter quand on ajoutera Codex."""

    provider = "openai"

    def collect(self) -> Iterator[InferenceEvent]:
        raise NotImplementedError("CodexCollector pas encore implémenté")


class LocalInferenceCollector(Collector):
    """Placeholder — inférence locale (Apple Silicon), hors MVP."""

    provider = "local"

    def collect(self) -> Iterator[InferenceEvent]:
        raise NotImplementedError("LocalInferenceCollector pas encore implémenté")
```

- [ ] **Step 7: Créer `agent_carbon/collectors/__init__.py` (vide)**

```python

```

- [ ] **Step 8: Lancer le test (passe)**

Run: `pytest tests/test_claude_code_collector.py -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Commit**

```bash
git add agent_carbon/collectors tests/test_claude_code_collector.py tests/fixtures/sample.jsonl
git commit -m "feat: Collector ABC, ClaudeCodeCollector (parse JSONL réel) + stubs"
```

---

## Task 4: `ModelResolver` (table d'alias)

**Files:**

- Create: `agent_carbon/impact/__init__.py`
- Create: `agent_carbon/impact/resolver.py`
- Test: `tests/test_resolver.py`

**Interfaces:**

- Consumes: rien.
- Produces: `ModelResolver(aliases: dict[str, str])` ; `resolve(model: str) -> tuple[str, bool]` renvoie `(nom_à_utiliser, alias_appliqué)`. Si `model` est dans la table → `(alias, True)`, sinon `(model, False)`. La détection « modèle inconnu d'EcoLogits » est gérée en aval par l'engine (via `errors`).

- [ ] **Step 1: Écrire le test**

`tests/test_resolver.py` :

```python
from agent_carbon.impact.resolver import ModelResolver


def test_passthrough_when_no_alias():
    r = ModelResolver({})
    assert r.resolve("claude-opus-4-8") == ("claude-opus-4-8", False)


def test_applies_alias():
    r = ModelResolver({"claude-future-9": "claude-opus-4-8"})
    assert r.resolve("claude-future-9") == ("claude-opus-4-8", True)
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_resolver.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Écrire `agent_carbon/impact/resolver.py`**

```python
class ModelResolver:
    """Filet de sécurité : mappe un modèle non encore enregistré upstream
    vers un modèle connu d'EcoLogits, via une table d'alias explicite.
    Table vide au départ (le registre 0.11.0 couvre déjà les modèles actuels)."""

    def __init__(self, aliases: dict[str, str]):
        self.aliases = aliases

    def resolve(self, model: str) -> tuple[str, bool]:
        if model in self.aliases:
            return self.aliases[model], True
        return model, False
```

- [ ] **Step 4: Créer `agent_carbon/impact/__init__.py` (vide)**

```python

```

- [ ] **Step 5: Lancer le test (passe)**

Run: `pytest tests/test_resolver.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_carbon/impact/__init__.py agent_carbon/impact/resolver.py tests/test_resolver.py
git commit -m "feat: ModelResolver (table d'alias, filet de sécurité)"
```

---

## Task 5: `EcoLogitsEngine` + `ImpactRecord`

**Files:**

- Create: `agent_carbon/impact/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**

- Consumes: `InferenceEvent` (Task 2), `Config` (Task 2), `ModelResolver` (Task 4), `agent_carbon.ENGINE_VERSION`, `ecologits`.
- Produces:
  - `ImpactRecord` (dataclass) : `model_resolved:str`, `zone:str`, `methodology_version:str`, `totals:dict[str,tuple[float,float]]`, `usage:dict[str,tuple[float,float]]`, `embodied:dict[str,tuple[float,float]]`, `warnings:list[str]`, `error:str|None`.
  - `CRITERIA = ("energy", "gwp", "adpe", "pe", "wcf")`.
  - `EcoLogitsEngine(resolver: ModelResolver)` ; `compute(event: InferenceEvent, config: Config) -> ImpactRecord`. Latence = `max(output_tokens / throughput_tok_s, 0.5)`. Si EcoLogits renvoie des `errors` (modèle inconnu) → `ImpactRecord` avec `error` rempli et dicts vides.
  - `compute_live(...)` : stub `NotImplementedError` (couture pour le mode live, hors MVP).

- [ ] **Step 1: Écrire le test**

`tests/test_engine.py` :

```python
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
    assert rec.zone == "USA"
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
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Écrire `agent_carbon/impact/engine.py`**

```python
from dataclasses import dataclass

import ecologits
from ecologits.tracers.utils import llm_impacts

from agent_carbon import ENGINE_VERSION
from agent_carbon.config import Config
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent

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
```

- [ ] **Step 4: Lancer le test (passe)**

Run: `pytest tests/test_engine.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/impact/engine.py tests/test_engine.py
git commit -m "feat: EcoLogitsEngine offline + ImpactRecord (5 critères, alias, gestion erreurs)"
```

---

## Task 6: `SQLiteStore` (schéma + ingestion idempotente + sessions)

**Files:**

- Create: `agent_carbon/store/__init__.py`
- Create: `agent_carbon/store/db.py`
- Test: `tests/test_store.py`

**Interfaces:**

- Consumes: `InferenceEvent` (Task 2), `EcoLogitsEngine`/`ImpactRecord` (Task 5), `Config` (Task 2).
- Produces:
  - `SQLiteStore(path: str)` — crée les tables `events`, `impacts`, `sessions` si absentes.
  - `ingest(events: Iterable[InferenceEvent], engine: EcoLogitsEngine, config: Config) -> int` — insère les events non vus (PK `(session_id, msg_id)`), calcule et stocke l'impact, met à jour la durée de session ; renvoie le nombre de **nouveaux** events ingérés. Idempotent.
  - `import_legacy(carbon_db_path: str)` — stub `NotImplementedError` (backfill placeholder).
  - Helpers de lecture pour le reporting : `rows_for_report(since: str | None) -> list[dict]` (jointure events+impacts), `session_count()`, `total_duration_seconds()`.

- [ ] **Step 1: Écrire le test**

`tests/test_store.py` :

```python
from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent
from agent_carbon.store.db import SQLiteStore


def _events():
    return [
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 287, 0, 0,
                       "2026-06-27T10:00:00.000Z", "projA", "sess-A", "u1"),
        InferenceEvent("anthropic", "claude-opus-4-8", 100, 200, 0, 0,
                       "2026-06-27T10:10:00.000Z", "projA", "sess-A", "u2"),
    ]


def _engine():
    return EcoLogitsEngine(ModelResolver({}))


def test_ingest_is_idempotent(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    n1 = store.ingest(_events(), _engine(), Config())
    n2 = store.ingest(_events(), _engine(), Config())  # rejoue
    assert n1 == 2
    assert n2 == 0  # aucun nouveau
    assert len(store.rows_for_report(None)) == 2


def test_session_duration_computed(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    store.ingest(_events(), _engine(), Config())
    assert store.session_count() == 1
    assert store.total_duration_seconds() == 600.0  # 10 min entre u1 et u2


def test_impact_columns_persisted(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    store.ingest(_events(), _engine(), Config())
    row = store.rows_for_report(None)[0]
    assert row["gwp_min"] > 0 and row["gwp_max"] >= row["gwp_min"]
    assert row["wcf_max"] > 0
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Écrire `agent_carbon/store/db.py`**

```python
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from agent_carbon.config import Config
from agent_carbon.impact.engine import CRITERIA, EcoLogitsEngine
from agent_carbon.models import InferenceEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  session_id TEXT, msg_id TEXT, provider TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  cache_creation_tokens INTEGER, cache_read_tokens INTEGER,
  timestamp TEXT, project TEXT,
  PRIMARY KEY (session_id, msg_id)
);
CREATE TABLE IF NOT EXISTS impacts (
  session_id TEXT, msg_id TEXT, model_resolved TEXT, zone TEXT,
  methodology_version TEXT,
  energy_min REAL, energy_max REAL, gwp_min REAL, gwp_max REAL,
  adpe_min REAL, adpe_max REAL, pe_min REAL, pe_max REAL,
  wcf_min REAL, wcf_max REAL,
  breakdown_json TEXT, warnings TEXT, error TEXT,
  PRIMARY KEY (session_id, msg_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, project TEXT, started_at TEXT, ended_at TEXT
);
"""


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class SQLiteStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def import_legacy(self, carbon_db_path: str):
        raise NotImplementedError("backfill carbon.db pas encore implémenté")

    def ingest(self, events: Iterable[InferenceEvent],
               engine: EcoLogitsEngine, config: Config) -> int:
        new_count = 0
        for e in events:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                (e.session_id, e.msg_id, e.provider, e.model,
                 e.input_tokens, e.output_tokens,
                 e.cache_creation_tokens, e.cache_read_tokens,
                 e.timestamp, e.project),
            )
            if cur.rowcount == 0:
                continue  # déjà ingéré → idempotent
            new_count += 1
            self._store_impact(e, engine.compute(e, config))
            self._touch_session(e)
        self.conn.commit()
        return new_count

    def _store_impact(self, e: InferenceEvent, rec) -> None:
        def mm(crit):
            return rec.totals.get(crit, (None, None))
        self.conn.execute(
            "INSERT OR REPLACE INTO impacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.session_id, e.msg_id, rec.model_resolved, rec.zone,
             rec.methodology_version,
             *mm("energy"), *mm("gwp"), *mm("adpe"), *mm("pe"), *mm("wcf"),
             json.dumps({"usage": rec.usage, "embodied": rec.embodied}),
             json.dumps(rec.warnings), rec.error),
        )

    def _touch_session(self, e: InferenceEvent) -> None:
        row = self.conn.execute(
            "SELECT started_at, ended_at FROM sessions WHERE session_id=?",
            (e.session_id,),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (e.session_id, e.project, e.timestamp, e.timestamp),
            )
            return
        started = min(row["started_at"], e.timestamp)
        ended = max(row["ended_at"], e.timestamp)
        self.conn.execute(
            "UPDATE sessions SET started_at=?, ended_at=? WHERE session_id=?",
            (started, ended, e.session_id),
        )

    def rows_for_report(self, since: str | None) -> list[dict]:
        sql = (
            "SELECT e.model, e.project, e.timestamp, "
            "i.energy_min, i.energy_max, i.gwp_min, i.gwp_max, "
            "i.adpe_min, i.adpe_max, i.pe_min, i.pe_max, i.wcf_min, i.wcf_max "
            "FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NULL"
        )
        params: tuple = ()
        if since:
            sql += " AND e.timestamp >= ?"
            params = (since,)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def session_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def total_duration_seconds(self) -> float:
        total = 0.0
        for r in self.conn.execute("SELECT started_at, ended_at FROM sessions"):
            a, b = _parse_ts(r["started_at"]), _parse_ts(r["ended_at"])
            if a and b:
                total += (b - a).total_seconds()
        return total
```

- [ ] **Step 4: Créer `agent_carbon/store/__init__.py` (vide)**

```python

```

- [ ] **Step 5: Lancer le test (passe)**

Run: `pytest tests/test_store.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add agent_carbon/store tests/test_store.py
git commit -m "feat: SQLiteStore (events/impacts/sessions, ingestion idempotente, durée)"
```

---

## Task 7: Rapport CLI (agrégation par modèle / projet / total)

**Files:**

- Create: `agent_carbon/report/__init__.py`
- Create: `agent_carbon/report/cli.py`
- Test: `tests/test_report.py`

**Interfaces:**

- Consumes: `SQLiteStore.rows_for_report` (Task 6), `CRITERIA` (Task 5).
- Produces: `render_report(rows: list[dict], group_by: str) -> str` où `group_by ∈ {"model", "project", "total"}`. Agrège en sommant `*_min` et `*_max` par groupe. Renvoie un tableau texte avec une colonne fourchette `min – max` par critère et une ligne `TOTAL`. Rappelle la zone/incertitude en pied.

- [ ] **Step 1: Écrire le test**

`tests/test_report.py` :

```python
from agent_carbon.report.cli import render_report


ROWS = [
    {"model": "claude-opus-4-8", "project": "projA",
     "gwp_min": 1.0, "gwp_max": 2.0, "energy_min": 0.1, "energy_max": 0.2,
     "adpe_min": 1e-9, "adpe_max": 2e-9, "pe_min": 0.3, "pe_max": 0.6,
     "wcf_min": 0.01, "wcf_max": 0.02},
    {"model": "claude-sonnet-4-6", "project": "projA",
     "gwp_min": 0.5, "gwp_max": 1.0, "energy_min": 0.05, "energy_max": 0.1,
     "adpe_min": 1e-9, "adpe_max": 1e-9, "pe_min": 0.1, "pe_max": 0.2,
     "wcf_min": 0.005, "wcf_max": 0.01},
]


def test_group_by_model_lists_each_model():
    out = render_report(ROWS, group_by="model")
    assert "claude-opus-4-8" in out
    assert "claude-sonnet-4-6" in out


def test_total_row_sums_ranges():
    out = render_report(ROWS, group_by="total")
    # somme GWP : min 1.5, max 3.0
    assert "1.5" in out and "3" in out


def test_group_by_project_aggregates():
    out = render_report(ROWS, group_by="project")
    assert "projA" in out
    # un seul groupe projet
    assert out.count("projA") == 1
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_report.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Écrire `agent_carbon/report/cli.py`**

```python
from agent_carbon.impact.engine import CRITERIA

_LABELS = {
    "energy": "Énergie(kWh)", "gwp": "GWP(kgCO2e)", "adpe": "ADPe(kgSb)",
    "pe": "PE(MJ)", "wcf": "Eau(L)",
}


def _key(row: dict, group_by: str) -> str:
    if group_by == "total":
        return "TOTAL"
    return row.get(group_by, "?")


def _fmt(lo: float, hi: float) -> str:
    return f"{lo:.3g}–{hi:.3g}"


def render_report(rows: list[dict], group_by: str) -> str:
    groups: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        g = groups.setdefault(_key(row, group_by), {c: [0.0, 0.0] for c in CRITERIA})
        for c in CRITERIA:
            g[c][0] += row[f"{c}_min"]
            g[c][1] += row[f"{c}_max"]

    header = ["groupe"] + [_LABELS[c] for c in CRITERIA]
    lines = [" | ".join(header), "-" * (len(" | ".join(header)))]
    totals = {c: [0.0, 0.0] for c in CRITERIA}
    for name, vals in groups.items():
        cells = [name]
        for c in CRITERIA:
            cells.append(_fmt(vals[c][0], vals[c][1]))
            totals[c][0] += vals[c][0]
            totals[c][1] += vals[c][1]
        lines.append(" | ".join(cells))
    if group_by != "total":
        lines.append("-" * (len(" | ".join(header))))
        lines.append(" | ".join(["TOTAL"] + [_fmt(totals[c][0], totals[c][1]) for c in CRITERIA]))
    lines.append("")
    lines.append("Fourchettes min–max (incertitude irréductible : région datacenter inconnue). "
                 "Zone élec configurable (défaut USA). Impact basé sur les tokens de sortie.")
    return "\n".join(lines)
```

- [ ] **Step 4: Créer `agent_carbon/report/__init__.py` (vide)**

```python

```

- [ ] **Step 5: Lancer le test (passe)**

Run: `pytest tests/test_report.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add agent_carbon/report tests/test_report.py
git commit -m "feat: rapport CLI multi-critères avec fourchettes (par modèle/projet/total)"
```

---

## Task 8: Statusline

**Files:**

- Create: `agent_carbon/statusline/__init__.py`
- Create: `agent_carbon/statusline/line.py`
- Test: `tests/test_statusline.py`

**Interfaces:**

- Consumes: `SQLiteStore.rows_for_report` (Task 6).
- Produces: `render_statusline(rows: list[dict]) -> str` — ligne compacte sommant l'énergie et le GWP sur tous les rows, format `⚡ <e_min>–<e_max> kWh · 🌍 <gwp_min>–<gwp_max> kgCO2e`. Chaîne vide si aucun row.

- [ ] **Step 1: Écrire le test**

`tests/test_statusline.py` :

```python
from agent_carbon.statusline.line import render_statusline


def test_compact_line_sums_energy_and_gwp():
    rows = [
        {"energy_min": 0.1, "energy_max": 0.2, "gwp_min": 1.0, "gwp_max": 2.0},
        {"energy_min": 0.05, "energy_max": 0.1, "gwp_min": 0.5, "gwp_max": 1.0},
    ]
    line = render_statusline(rows)
    assert "kWh" in line and "kgCO2e" in line
    assert "0.15" in line  # énergie min sommée


def test_empty_when_no_rows():
    assert render_statusline([]) == ""
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_statusline.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Écrire `agent_carbon/statusline/line.py`**

```python
def render_statusline(rows: list[dict]) -> str:
    if not rows:
        return ""
    e_min = sum(r["energy_min"] for r in rows)
    e_max = sum(r["energy_max"] for r in rows)
    g_min = sum(r["gwp_min"] for r in rows)
    g_max = sum(r["gwp_max"] for r in rows)
    return f"⚡ {e_min:.3g}–{e_max:.3g} kWh · 🌍 {g_min:.3g}–{g_max:.3g} kgCO2e"
```

- [ ] **Step 4: Créer `agent_carbon/statusline/__init__.py` (vide)**

```python

```

- [ ] **Step 5: Lancer le test (passe)**

Run: `pytest tests/test_statusline.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_carbon/statusline tests/test_statusline.py
git commit -m "feat: statusline compacte (énergie + GWP) lisant la DB"
```

---

## Task 9: CLI `agent-carbon` (ingest / report / statusline) + test end-to-end

**Files:**

- Create: `agent_carbon/__main__.py`
- Test: `tests/test_cli_end_to_end.py`

**Interfaces:**

- Consumes: tout ce qui précède.
- Produces: `main(argv: list[str] | None = None) -> int`. Sous-commandes :
  - `ingest --source <dir> --db <path>` → parse + calcule + stocke, affiche `N events ingérés`.
  - `report --db <path> [--by model|project|total] [--since ISO]` → imprime `render_report`.
  - `statusline --db <path>` → imprime `render_statusline`.
    Emplacements par défaut : `--source ~/.claude/projects`, `--db ~/.agent-carbon/carbon.db`.

- [ ] **Step 1: Écrire le test end-to-end**

`tests/test_cli_end_to_end.py` :

```python
from pathlib import Path
from agent_carbon.__main__ import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_then_report(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    rc = main(["ingest", "--source", str(FIXTURES), "--db", db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 events" in out

    rc = main(["report", "--db", db, "--by", "model"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "claude-opus-4-8" in out
    assert "GWP" in out


def test_ingest_is_idempotent_via_cli(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    capsys.readouterr()
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    assert "0 events" in capsys.readouterr().out


def test_statusline_runs(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    capsys.readouterr()
    rc = main(["statusline", "--db", db])
    assert rc == 0
    assert "kWh" in capsys.readouterr().out
```

- [ ] **Step 2: Lancer le test (échoue)**

Run: `pytest tests/test_cli_end_to_end.py -v`
Expected: FAIL (`ModuleNotFoundError` / pas de `main`).

- [ ] **Step 3: Écrire `agent_carbon/__main__.py`**

```python
import argparse
import os

from agent_carbon.collectors.claude_code import ClaudeCodeCollector
from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.report.cli import render_report
from agent_carbon.statusline.line import render_statusline
from agent_carbon.store.db import SQLiteStore

_DEFAULT_SOURCE = os.path.expanduser("~/.claude/projects")
_DEFAULT_DB = os.path.expanduser("~/.agent-carbon/carbon.db")


def _store(db_path: str) -> SQLiteStore:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    return SQLiteStore(db_path)


def _engine(config: Config) -> EcoLogitsEngine:
    return EcoLogitsEngine(ModelResolver(config.model_aliases))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-carbon")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="parser les transcripts et calculer l'impact")
    p_ing.add_argument("--source", default=_DEFAULT_SOURCE)
    p_ing.add_argument("--db", default=_DEFAULT_DB)

    p_rep = sub.add_parser("report", help="afficher le rapport multi-critères")
    p_rep.add_argument("--db", default=_DEFAULT_DB)
    p_rep.add_argument("--by", choices=["model", "project", "total"], default="model")
    p_rep.add_argument("--since", default=None)

    p_st = sub.add_parser("statusline", help="ligne compacte pour la statusline")
    p_st.add_argument("--db", default=_DEFAULT_DB)

    args = parser.parse_args(argv)
    config = Config()

    if args.cmd == "ingest":
        store = _store(args.db)
        events = ClaudeCodeCollector(args.source).collect()
        n = store.ingest(events, _engine(config), config)
        print(f"{n} events ingérés")
        return 0

    if args.cmd == "report":
        store = _store(args.db)
        print(render_report(store.rows_for_report(args.since), group_by=args.by))
        return 0

    if args.cmd == "statusline":
        store = _store(args.db)
        print(render_statusline(store.rows_for_report(None)))
        return 0

    return 1
```

- [ ] **Step 4: Lancer le test (passe)**

Run: `pytest tests/test_cli_end_to_end.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lancer toute la suite**

Run: `pytest -v`
Expected: tous les tests PASS.

- [ ] **Step 6: Vérification réelle sur tes propres données**

Run:

```bash
agent-carbon ingest --db /tmp/ac-real.db
agent-carbon report --db /tmp/ac-real.db --by model
```

Expected: nombre d'events > 0, tableau multi-critères avec fourchettes sur tes vraies sessions.

- [ ] **Step 7: Commit**

```bash
git add agent_carbon/__main__.py tests/test_cli_end_to_end.py
git commit -m "feat: CLI agent-carbon (ingest/report/statusline) + test end-to-end"
```

---

## Task 10: Documentation (README + doc technique)

**Files:**

- Create: `README.md`
- Create: `docs/ARCHITECTURE.md`

**Interfaces:**

- Consumes: l'ensemble du projet livré.
- Produces: documentation de présentation et technique. Pas de test automatisé ; vérification = relecture.

- [ ] **Step 1: Écrire `README.md`**

Contenu (sections) :

```markdown
# agent-carbon

Compteur d'impact environnemental **multi-critères** et **vendor-neutral** pour les
outils d'IA agentique. Il parse les transcripts (Claude Code en MVP), délègue le
calcul d'impact à **EcoLogits**, et restitue un rapport CLI + une statusline.

## Pourquoi

Issu de l'audit de `claude-carbon` (mono-critère CO₂, facteurs dérivés du prix). Ici :
multi-critères (énergie, GWP, eau, ADPe, PE), fourchettes min–max assumées (l'incertitude
sur la région datacenter est irréductible), et **aucun modèle d'impact réécrit** — on
s'appuie sur EcoLogits.

## Installation

- Python ≥ 3.10
- `pip install -e .` (installe EcoLogits depuis le tag `mlco2/ecologits@0.11.0`)

## Usage

- `agent-carbon ingest` — parse `~/.claude/projects` et remplit la DB
- `agent-carbon report --by model|project|total [--since ISO]`
- `agent-carbon statusline` — ligne compacte

## Sources d'inspiration

- **claude-carbon** — audit d'origine et UX de reporting.
- **EcoLogits** (`mlco2/ecologits`) — moteur d'impact multi-critères/multi-phases.
- **CodeCarbon** — offline tracker + zone élec par code pays (`country_iso_code`).
- **thirsty-llm** — offline-first, fourchettes, logging minimal (on rejette son modèle
  prix-proxy, justement remplacé par EcoLogits).

## Limites assumées

Impact piloté par les tokens de sortie ; région datacenter d'Anthropic inconnue (d'où les
fourchettes) ; inférence locale et énergie du poste de travail hors MVP.
```

- [ ] **Step 2: Écrire `docs/ARCHITECTURE.md`**

Contenu (sections) :

```markdown
# Architecture technique

## Pipeline

JSONL Claude Code → ClaudeCodeCollector → InferenceEvent[] → EcoLogitsEngine (offline)
→ SQLiteStore → rapport CLI / statusline.

## Collecte

`ClaudeCodeCollector` lit `~/.claude/projects/**/*.jsonl`, retient les messages
`type=="assistant"` avec `message.usage`, et normalise en `InferenceEvent`
(`model`, tokens in/out/cache, `timestamp`, `project` dérivé de `cwd`, `session_id`,
`msg_id`=`uuid`). Confidentialité : aucun contenu de prompt/réponse.

## Impact (EcoLogits offline)

`EcoLogitsEngine` appelle `ecologits.tracers.utils.llm_impacts(provider, model_name,
output_token_count, request_latency, electricity_mix_zone)` — sans réseau. Sortie : 5
critères (energy, gwp, adpe, pe, wcf), phases usage/embodied, fourchettes RangeValue.
`request_latency` estimée (`output_tokens / débit`, défaut 50 tok/s). Seuls les **tokens
de sortie** entrent dans le calcul. `ModelResolver` mappe au besoin un modèle non encore
enregistré upstream vers un modèle connu (table d'alias).

## Stockage

SQLite, trois tables : `events` (brut normalisé, PK `(session_id, msg_id)` → idempotence),
`impacts` (5 critères min/max + `methodology_version` + zone + breakdown JSON + warnings),
`sessions` (durée = ended_at − started_at). Séparation events/impacts → recalcul possible
sans re-parser.

## Restitution

`report` agrège par modèle/projet/total avec fourchettes ; `statusline` donne une ligne
compacte. Tous deux lisent la DB (jamais les JSONL).

## Incertitude & méthodologie

Tout est affiché en fourchette min–max. `methodology_version` (engine + version EcoLogits)
est stockée par record → comparaisons et recalculs fiables. Cf. plan de maintenance pour
le suivi de version EcoLogits.

## Hors MVP (coutures posées)

CodexCollector/LocalInferenceCollector (stubs), `import_legacy` (backfill carbon.db),
mode live (`compute_live`), énergie du poste de travail, eau via release PyPI, export
fichier.
```

- [ ] **Step 3: Relire les deux documents**

Vérifier : cohérence avec le code livré (noms de commandes, chemins, 5 critères), pas de placeholder, français correct.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: README (présentation + sources d'inspiration) et doc technique"
```

---

## Notes de fin

- **Ordre des tâches** : 1 → 10 séquentiel (chaque tâche consomme les précédentes).
- **Hors périmètre** (placeholders déjà posés, ne pas implémenter) : inférence locale, énergie du poste, backfill `carbon.db`, mode live, export fichier, GitHub Action de suivi de version (cf. section Maintenance du spec).
- **Après le MVP** : brancher la statusline dans `~/.claude/settings.json` (`statusLine` → `agent-carbon statusline --db ...`), et planifier l'`ingest` (hook ou cron) pour garder la DB à jour avant purge des JSONL.
