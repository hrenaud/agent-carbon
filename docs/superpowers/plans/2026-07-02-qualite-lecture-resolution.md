# Qualité lecture des données & résolution des modèles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger les défauts M1–M3, N1–N4 et mineurs de la spec `docs/SPEC-qualite-lecture-resolution.md` (cache négatif HF, hypothèse 4-bit, warnings, collisions d'ids, timestamps, plafonds réseau).

**Architecture:** Aucun nouveau module. Les correctifs vivent dans les fichiers existants : `agent_carbon/impact/params.py` (cascade HF), `agent_carbon/store/db.py` (ingest/requêtes), `agent_carbon/collectors/crush.py` (ids), `agent_carbon/config.py` (cache négatif persisté), `agent_carbon/__main__.py` et `agent_carbon/resolve/cli.py` (CLI). La cascade reste **offline-safe** (jamais d'exception) et la provenance reste tracée via `warnings`.

**Tech Stack:** Python ≥ 3.10, stdlib + `ecologits` (épinglé git 0.11.0) + `huggingface_hub`, pytest, SQLite.

## Global Constraints

- Tests : `.venv/bin/python -m pytest` (lancer depuis la racine du repo). TDD strict : test rouge avant implémentation.
- **Params EcoLogits en milliards partout** (`ParamsResult.active/total`, `config.model_params`) ; `safetensors.total` HF = compte brut → `÷ 1e9`.
- La cascade `impact/params.py` ne doit **jamais lever d'exception** (offline-safe) : tout échec → `None`.
- Ne jamais utiliser `rm` ; utiliser `trash` si suppression.
- Commits sémantiques en français : `fix: …`, `feat: …`, `docs: …`, `perf: …`.
- Commentaires de code en français (comme l'existant).
- Ne pas casser l'idempotence de `SQLiteStore.ingest` (PK `(session_id, msg_id)` + `INSERT OR IGNORE`).
- `RangeValue` vient de `ecologits.utils.range_value` (pydantic, champs `min`/`max`) ; le registre EcoLogits l'utilise déjà pour des comptes de paramètres, donc `compute_llm_impacts` l'accepte en entrée.

---

### Task 1: M1a — cache négatif HF en mémoire (par run)

**Files:**

- Modify: `agent_carbon/impact/params.py` (classe `ModelParamsResolver`, lignes ~169-225)
- Test: `tests/test_params_huggingface.py`

**Interfaces:**

- Consumes: `ModelParamsResolver.resolve(provider, model)` et `_from_huggingface` existants.
- Produces: `ModelParamsResolver._hf_failed: set[str]` (clés `provider/model` échouées dans ce run). Task 2 le complète avec la persistance.

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_params_huggingface.py` :

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py::test_huggingface_failure_not_retried_same_run -v`
Expected: FAIL — `assert call_count[0] == 1` échoue avec `2 == 1`.

- [ ] **Step 3: Write minimal implementation**

Dans `agent_carbon/impact/params.py`, classe `ModelParamsResolver` :

```python
    def __init__(self, config):
        self.config = config
        # M1a : clés « provider/model » dont la résolution HF a échoué dans ce
        # run — évite de relancer la cascade réseau à chaque event du même modèle.
        self._hf_failed: set[str] = set()
```

Et dans `_from_huggingface` :

```python
    def _from_huggingface(self, provider: str, model: str) -> ParamsResult | None:
        """Tier 3 : params depuis le Hub via fetch_hf_params, puis mise en cache.
        arch toujours « dense » ici (fetch_hf_params suppose dense) ; l'affinage
        MoE passe par `resolve --set "P/M=repo:<actifs>"` (cf. resolve/cli.py)."""
        key = f"{provider}/{model}"
        if key in self._hf_failed:
            return None
        res = fetch_hf_params(model)
        if res is None:
            self._hf_failed.add(key)
            return None
        self.config.model_params[key] = {
            "active": res.active, "total": res.total,
            "arch": res.arch, "source": res.source}
        return res
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py tests/test_params_resolver.py -v`
Expected: PASS (tous, y compris le nouveau).

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/impact/params.py tests/test_params_huggingface.py
git commit -m "perf: cache négatif HF en mémoire par run (M1a)"
```

---

### Task 2: M1b — cache négatif persisté avec TTL

**Files:**

- Modify: `agent_carbon/config.py` (dataclass `Config`)
- Modify: `agent_carbon/impact/params.py` (`ModelParamsResolver`)
- Modify: `agent_carbon/__main__.py` (branches `ingest` ligne ~245 et `statusline` ligne ~280)
- Test: `tests/test_config_persist.py`, `tests/test_params_huggingface.py`

**Interfaces:**

- Consumes: `Config.load()/save()`, `ModelParamsResolver._hf_failed` (Task 1).
- Produces: `Config.hf_unresolved: dict[str, str]` (clé `provider/model` → ISO UTC du dernier échec) ; constante `HF_NEGATIVE_TTL_DAYS = 7` dans `params.py`. Task 9 (`--retry-hf`) purge ce dict.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_config_persist.py` :

```python
def test_config_roundtrips_hf_unresolved(tmp_path):
    """M1b : le cache négatif HF est persisté dans config.json."""
    from agent_carbon.config import Config
    p = str(tmp_path / "config.json")
    cfg = Config(hf_unresolved={"ollama/org/x": "2026-07-02T00:00:00+00:00"})
    cfg.save(p)
    assert Config.load(p).hf_unresolved == {"ollama/org/x": "2026-07-02T00:00:00+00:00"}
```

Ajouter à `tests/test_params_huggingface.py` :

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config_persist.py::test_config_roundtrips_hf_unresolved tests/test_params_huggingface.py -v -k "negative_cache or roundtrips_hf"`
Expected: FAIL — `TypeError: Config.__init__() got an unexpected keyword argument 'hf_unresolved'`.

- [ ] **Step 3: Write minimal implementation**

`agent_carbon/config.py`, ajouter le champ dans la dataclass (après `model_params`) :

```python
    model_params: dict[str, dict] = field(default_factory=dict)
    # M1b : cache négatif HF persisté — clé « provider/model » → ISO UTC du
    # dernier échec de résolution. Purgé par succès, TTL côté résolveur.
    hf_unresolved: dict[str, str] = field(default_factory=dict)
    local_wh_per_token: float | None = None
```

`agent_carbon/impact/params.py`, en tête (avec les imports) :

```python
from datetime import datetime, timedelta, timezone

# TTL du cache négatif persisté : au-delà, on retente la résolution HF
# (le modèle a pu être publié/renommé entre-temps).
HF_NEGATIVE_TTL_DAYS = 7
```

Dans `ModelParamsResolver` :

```python
    def _negative_fresh(self, key: str) -> bool:
        """Vrai si un échec HF récent (< TTL) est mémorisé en config pour key."""
        ts = self.config.hf_unresolved.get(key)
        if ts is None:
            return False
        try:
            failed_at = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return False
        if failed_at.tzinfo is None:
            failed_at = failed_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - failed_at < timedelta(days=HF_NEGATIVE_TTL_DAYS)

    def _from_huggingface(self, provider: str, model: str) -> ParamsResult | None:
        """Tier 3 : params depuis le Hub via fetch_hf_params, puis mise en cache.
        arch toujours « dense » ici (fetch_hf_params suppose dense) ; l'affinage
        MoE passe par `resolve --set "P/M=repo:<actifs>"` (cf. resolve/cli.py)."""
        key = f"{provider}/{model}"
        if key in self._hf_failed or self._negative_fresh(key):
            return None
        res = fetch_hf_params(model)
        if res is None:
            self._hf_failed.add(key)
            self.config.hf_unresolved[key] = datetime.now(timezone.utc).isoformat()
            return None
        self.config.hf_unresolved.pop(key, None)
        self.config.model_params[key] = {
            "active": res.active, "total": res.total,
            "arch": res.arch, "source": res.source}
        return res
```

`agent_carbon/__main__.py` : la config mutée pendant l'ingest (cache positif **et** négatif) doit être sauvée — aujourd'hui elle ne l'est jamais depuis `ingest`/`statusline`. Ajouter un helper au niveau module :

```python
def _config_snapshot(config: Config) -> str:
    """Empreinte des champs mutés par la résolution (pour ne sauver que si changé)."""
    return json.dumps(
        {"model_params": config.model_params, "hf_unresolved": config.hf_unresolved},
        sort_keys=True, default=str)
```

Dans la branche `ingest` (autour de la ligne 255) :

```python
        before = _config_snapshot(config)
        n = store.ingest(events, _engine(config), config)
        if _config_snapshot(config) != before:
            config.save()  # persiste caches positif/négatif résolus pendant l'ingest
        print(_ingest_summary(n, store.coverage(), store))
        return 0
```

Dans la branche `statusline` (autour de la ligne 288) :

```python
        if transcript and os.path.exists(transcript):
            before = _config_snapshot(config)
            store.ingest(ClaudeCodeCollector(transcript).collect(), _engine(config), config)
            if _config_snapshot(config) != before:
                config.save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config_persist.py tests/test_params_huggingface.py tests/test_cli_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite (la sérialisation config est transverse)**

Run: `.venv/bin/python -m pytest -q`
Expected: 163 + 4 nouveaux = tous PASS. Si un test existant construit `Config(**data)` avec des clés strictes, la tolérance `known keys` de `Config.load` couvre déjà les vieux config.json (champ absent → default_factory).

- [ ] **Step 6: Commit**

```bash
git add agent_carbon/config.py agent_carbon/impact/params.py agent_carbon/__main__.py tests/test_config_persist.py tests/test_params_huggingface.py
git commit -m "perf: cache négatif HF persisté avec TTL 7 jours (M1b)"
```

---

### Task 3: M3 — warning `moe-assumed-dense` conditionnel

**Files:**

- Modify: `agent_carbon/impact/params.py` (`fetch_hf_params`, ligne ~147-155)
- Test: `tests/test_params_huggingface.py`

**Interfaces:**

- Consumes: `fetch_hf_params(repo)` (Task 1/2 ne changent pas sa signature).
- Produces: helper `_looks_moe(repo: str) -> bool` (réutilisé nulle part ailleurs pour l'instant) ; le warning `moe-assumed-dense` n'apparaît plus que si le nom suggère un MoE.

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_params_huggingface.py` :

```python
def test_dense_repo_has_no_moe_warning(monkeypatch):
    """M3 : un repo au nom dense ne reçoit pas le warning moe-assumed-dense."""
    _fake_hf(7_000_000_000, monkeypatch)
    res = fetch_hf_params("Qwen/Qwen2.5-7B")
    assert "moe-assumed-dense" not in res.warnings


def test_moe_named_repo_keeps_moe_warning(monkeypatch):
    """M3 : un nom type « …-A3B » (MoE) garde le warning."""
    _fake_hf(35_000_000_000, monkeypatch)
    res = fetch_hf_params("Qwen/Qwen3.6-35B-A3B-Instruct")
    assert "moe-assumed-dense" in res.warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py -v -k "moe_warning or moe_named"`
Expected: `test_dense_repo_has_no_moe_warning` FAIL (le warning est toujours présent) ; l'autre PASS.

- [ ] **Step 3: Write minimal implementation**

Dans `agent_carbon/impact/params.py`, en tête ajouter `import re`, puis au niveau module :

```python
# Noms de modèles MoE : motif « a<N>b » isolé (ex. -A3B, …120b-a12b).
_MOE_NAME_RE = re.compile(r"(?:^|[^a-z0-9])a\d+b(?:[^a-z0-9]|$)", re.IGNORECASE)


def _looks_moe(repo: str) -> bool:
    """Vrai si le nom du repo suggère une architecture MoE (motif « aNb »)."""
    return bool(_MOE_NAME_RE.search(repo))
```

Et dans `fetch_hf_params` :

```python
def fetch_hf_params(repo: str) -> ParamsResult | None:
    """repo HF → paramètres (total ÷ 1e9, supposé dense). Offline-safe : None si
    la résolution échoue (cf. _fetch_hf_total_params)."""
    resolved = _fetch_hf_total_params(repo)
    if resolved is None:
        return None
    total, warnings = resolved
    if _looks_moe(repo):
        # Nom type MoE traité en dense : l'énergie serait surestimée (calculée
        # sur le total au lieu des params actifs) — signalé en provenance.
        warnings = ["moe-assumed-dense", *warnings]
    return ParamsResult(active=total, total=total, arch="dense",
                        source="huggingface", warnings=warnings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py tests/test_resolve.py tests/test_resolve_cli.py -v`
Expected: PASS. Si un test existant assertait `moe-assumed-dense` sur un nom dense, adapter ce test (le nouveau comportement est le bon).

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/impact/params.py tests/test_params_huggingface.py
git commit -m "fix: warning moe-assumed-dense seulement si le nom suggère un MoE (M3)"
```

---

### Task 4: M2a — détection du dtype (octets/param) depuis le nom du repo

**Files:**

- Modify: `agent_carbon/impact/params.py` (`_bytes_to_params_estimated`, `_fetch_hf_total_params`)
- Test: `tests/test_params_huggingface.py`

**Interfaces:**

- Consumes: méthodes 2 (`used_storage`) et 3 (`index.json`) existantes.
- Produces: `_detect_bytes_per_param(repo: str) -> float | None` (0.5 / 1.0 / 2.0 / 4.0 / None) ; `_bytes_to_params_estimated(total_bytes: int, bytes_per_param: float) -> float` (signature **modifiée** : le 2ᵉ argument devient obligatoire) ; warnings de provenance `params-bytes-per-param:<bpp>`. Task 5 gère le cas `None` (fourchette).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_params_huggingface.py` :

```python
import pytest
from agent_carbon.impact.params import _detect_bytes_per_param


@pytest.mark.parametrize("repo,expected", [
    ("mlx-community/Qwen3.6-35B-A3B-4bit", 0.5),
    ("org/model-q4_K_M-GGUF", 0.5),
    ("org/model-MXFP4", 0.5),
    ("org/model-int8", 1.0),
    ("org/model-fp8", 1.0),
    ("org/model-fp16", 2.0),
    ("org/model-bf16", 2.0),
    ("org/model-fp32", 4.0),
    ("Qwen/Qwen2.5-7B", None),          # rien dans le nom → inconnu
])
def test_detect_bytes_per_param(repo, expected):
    """M2a : le dtype est déduit du nom du repo (octets par paramètre)."""
    assert _detect_bytes_per_param(repo) == expected


def test_used_storage_uses_detected_dtype(monkeypatch):
    """M2a : méthode 2 (used_storage) — un repo fp16 divise par 2 octets/param,
    pas par 0.5 (l'ancien comportement surestimait 4×)."""
    import agent_carbon.impact.params as params_mod
    mod = types.ModuleType("huggingface_hub")
    mod.model_info = lambda repo_id, **kw: types.SimpleNamespace(safetensors=None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    monkeypatch.setattr(params_mod, "_fetch_hf_cli_info",
                        lambda repo: {"used_storage": 14_000_000_000})  # 14 Go
    monkeypatch.setattr(params_mod, "_fetch_safetensors_index_bytes", lambda repo: None)
    res = fetch_hf_params("org/model-fp16")
    assert res is not None
    assert res.total == pytest.approx(7.0)  # 14e9 octets / 2 o/param / 1e9 = 7 Md
    assert "params-bytes-per-param:2.0" in res.warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py -v -k "dtype or bytes_per_param"`
Expected: FAIL — `ImportError: cannot import name '_detect_bytes_per_param'`.

- [ ] **Step 3: Write minimal implementation**

Dans `agent_carbon/impact/params.py` :

```python
# Détection du dtype depuis le nom du repo → octets par paramètre.
# Ordre : du plus spécifique au plus général ; premier motif gagnant.
_BYTES_PER_PARAM_PATTERNS: tuple[tuple[re.Pattern, float], ...] = (
    (re.compile(r"4[-_]?bit|q4|int4|awq|gptq|mxfp4|nf4", re.IGNORECASE), 0.5),
    (re.compile(r"8[-_]?bit|q8|int8|fp8", re.IGNORECASE), 1.0),
    (re.compile(r"fp16|bf16|f16|half", re.IGNORECASE), 2.0),
    (re.compile(r"fp32|f32", re.IGNORECASE), 4.0),
)


def _detect_bytes_per_param(repo: str) -> float | None:
    """Octets/param déduits du nom du repo (`-4bit` → 0.5, `-fp16` → 2.0…).
    None si le nom ne dit rien (dtype inconnu → fourchette, cf. Task M2b)."""
    for pattern, bpp in _BYTES_PER_PARAM_PATTERNS:
        if pattern.search(repo):
            return bpp
    return None


def _bytes_to_params_estimated(total_bytes: int, bytes_per_param: float) -> float:
    """Estime le nombre de paramètres (en milliards) depuis la taille totale
    des fichiers et le dtype détecté."""
    return (total_bytes / bytes_per_param) / 1e9
```

Dans `_fetch_hf_total_params`, remplacer les méthodes 2 et 3 :

```python
    bpp = _detect_bytes_per_param(repo)

    # Méthode 2 : CLI `hf models info` (used_storage → params estimés via dtype)
    cli_info = _fetch_hf_cli_info(repo)
    if cli_info is not None:
        used_storage = cli_info.get("used_storage", 0)
        if used_storage and used_storage > 0 and bpp is not None:
            total = _bytes_to_params_estimated(used_storage, bpp)
            if total > 0:
                return total, ["params-from-cli-used_storage",
                               f"params-bytes-per-param:{bpp}"]

    # Méthode 3 : fichiers safetensors via index.json (fallback final)
    total_bytes = _fetch_safetensors_index_bytes(repo)
    if total_bytes is not None and total_bytes > 0 and bpp is not None:
        total = _bytes_to_params_estimated(total_bytes, bpp)
        if total > 0:
            return total, ["params-estimated-from-files",
                           f"params-bytes-per-param:{bpp}"]

    return None
```

> Note : le cas `bpp is None` renvoie temporairement None (dtype inconnu → pas
> d'estimation) ; la Task 5 le remplace par une fourchette. L'ancien warning
> `params-estimated-4bit` disparaît — si un test existant l'asserte, le mettre
> à jour vers `params-bytes-per-param:0.5`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py tests/test_resolve.py tests/test_resolve_cli.py tests/test_cli_models.py -v`
Expected: PASS (adapter les assertions sur `params-estimated-4bit` le cas échéant).

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/impact/params.py tests/test_params_huggingface.py
git commit -m "fix: octets/param déduits du dtype au lieu du 4-bit universel (M2a)"
```

---

### Task 5: M2b — fourchette de params quand le dtype est inconnu

**Files:**

- Modify: `agent_carbon/impact/params.py` (`ParamsResult`, `_fetch_hf_total_params`, `ModelParamsResolver._from_cache`/`_from_huggingface`)
- Modify: `agent_carbon/resolve/cli.py` (`set_mappings`, `_print_set`)
- Modify: `agent_carbon/__main__.py` (`_cmd_models`, lecture du cache ligne ~112)
- Test: `tests/test_params_huggingface.py`, `tests/test_engine_selfhosted.py`

**Interfaces:**

- Consumes: `_detect_bytes_per_param` (Task 4), `RangeValue` (pydantic EcoLogits, champs `min`/`max`).
- Produces: `ParamsResult.active/total: float | RangeValue` ; helpers module `_param_to_json(v) -> float | dict` et `_param_from_json(v) -> float | RangeValue` ; helper `fmt_params_md(v) -> str` dans `resolve/cli.py`. `compute_llm_impacts` accepte `RangeValue` (déjà le cas pour les modèles du registre à plage, ex. devstral).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_params_huggingface.py` :

```python
def test_unknown_dtype_yields_param_range(monkeypatch):
    """M2b : dtype indétectable → fourchette 0.5–2 octets/param, pas une valeur unique."""
    from ecologits.utils.range_value import RangeValue
    import agent_carbon.impact.params as params_mod
    mod = types.ModuleType("huggingface_hub")
    mod.model_info = lambda repo_id, **kw: types.SimpleNamespace(safetensors=None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    monkeypatch.setattr(params_mod, "_fetch_hf_cli_info",
                        lambda repo: {"used_storage": 14_000_000_000})
    monkeypatch.setattr(params_mod, "_fetch_safetensors_index_bytes", lambda repo: None)
    res = fetch_hf_params("org/model-sans-dtype")
    assert res is not None
    assert isinstance(res.total, RangeValue)
    assert res.total.min == pytest.approx(7.0)    # 14e9 / 2.0 / 1e9
    assert res.total.max == pytest.approx(28.0)   # 14e9 / 0.5 / 1e9
    assert "params-range-unknown-dtype" in res.warnings


def test_param_range_roundtrips_through_cache(monkeypatch):
    """M2b : la fourchette survit à l'aller-retour cache config (JSON)."""
    from ecologits.utils.range_value import RangeValue
    import agent_carbon.impact.params as params_mod
    mod = types.ModuleType("huggingface_hub")
    mod.model_info = lambda repo_id, **kw: types.SimpleNamespace(safetensors=None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    monkeypatch.setattr(params_mod, "_fetch_hf_cli_info",
                        lambda repo: {"used_storage": 14_000_000_000})
    monkeypatch.setattr(params_mod, "_fetch_safetensors_index_bytes", lambda repo: None)
    cfg = Config()
    r = ModelParamsResolver(cfg)
    r.resolve("ollama", "org/model-sans-dtype")           # remplit le cache
    # Le cache config doit rester du JSON pur (dict min/max, pas d'objet pydantic)
    entry = cfg.model_params["ollama/org/model-sans-dtype"]
    assert entry["total"] == {"min": pytest.approx(7.0), "max": pytest.approx(28.0)}
    res2 = ModelParamsResolver(cfg).resolve("ollama", "org/model-sans-dtype")
    assert isinstance(res2.total, RangeValue)
    assert res2.total.max == pytest.approx(28.0)
```

Ajouter à `tests/test_engine_selfhosted.py` :

```python
def test_selfhosted_range_params_produce_wider_bounds():
    """M2b : des params en fourchette traversent compute_llm_impacts (min < max)."""
    from ecologits.utils.range_value import RangeValue
    from agent_carbon.config import Config
    from agent_carbon.impact.engine import EcoLogitsEngine
    from agent_carbon.impact.resolver import ModelResolver
    from agent_carbon.models import InferenceEvent
    cfg = Config(
        electricity_mix_zone="WOR",
        model_params={"ollama/range-model": {
            "active": {"min": 7.0, "max": 28.0},
            "total": {"min": 7.0, "max": 28.0},
            "arch": "dense", "source": "huggingface"}})
    engine = EcoLogitsEngine(ModelResolver({}))
    e = InferenceEvent(provider="ollama", model="range-model",
                       input_tokens=10, output_tokens=100,
                       cache_creation_tokens=0, cache_read_tokens=0,
                       timestamp="2026-07-02T00:00:00+00:00", project="p",
                       session_id="s", msg_id="m", active_seconds=1.0)
    rec = engine.compute(e, cfg)
    assert rec.error is None
    gwp_min, gwp_max = rec.totals["gwp"]
    assert 0 < gwp_min < gwp_max  # la fourchette de params élargit les bornes
```

(Adapter la construction d'`InferenceEvent` aux champs exacts de `agent_carbon/models.py` si l'ordre diffère — reprendre le style des tests existants du fichier.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py tests/test_engine_selfhosted.py -v -k "range"`
Expected: FAIL — `res.total` est None (dtype inconnu → None depuis Task 4) et le cache dict fait planter `float(entry["active"])`.

- [ ] **Step 3: Write minimal implementation**

`agent_carbon/impact/params.py` — dataclass et helpers :

```python
@dataclass
class ParamsResult:
    active: float | RangeValue
    total: float | RangeValue
    arch: str            # "dense" | "moe"
    source: str          # "registry" | "user" | "huggingface"
    warnings: list[str] = field(default_factory=list)


def _param_to_json(v: float | RangeValue) -> float | dict:
    """Sérialise un compte de params pour le cache config (JSON pur)."""
    if isinstance(v, RangeValue):
        return {"min": float(v.min), "max": float(v.max)}
    return float(v)


def _param_from_json(v) -> float | RangeValue:
    """Désérialise un compte de params du cache config."""
    if isinstance(v, dict):
        return RangeValue(min=v["min"], max=v["max"])
    return float(v)
```

Dans `_fetch_hf_total_params`, gérer `bpp is None` (fourchette 0.5–2 octets/param) :

```python
    def _estimated(total_bytes: int) -> tuple[float | RangeValue, list[str]]:
        """Params estimés depuis des octets : valeur si dtype connu, fourchette sinon."""
        if bpp is not None:
            return (_bytes_to_params_estimated(total_bytes, bpp),
                    [f"params-bytes-per-param:{bpp}"])
        return (RangeValue(min=_bytes_to_params_estimated(total_bytes, 2.0),
                           max=_bytes_to_params_estimated(total_bytes, 0.5)),
                ["params-range-unknown-dtype"])

    # Méthode 2 : CLI `hf models info` (used_storage → params estimés)
    cli_info = _fetch_hf_cli_info(repo)
    if cli_info is not None:
        used_storage = cli_info.get("used_storage", 0)
        if used_storage and used_storage > 0:
            total, extra = _estimated(used_storage)
            return total, ["params-from-cli-used_storage", *extra]

    # Méthode 3 : fichiers safetensors via index.json (fallback final)
    total_bytes = _fetch_safetensors_index_bytes(repo)
    if total_bytes is not None and total_bytes > 0:
        total, extra = _estimated(total_bytes)
        return total, ["params-estimated-from-files", *extra]

    return None
```

(La signature de `_fetch_hf_total_params` devient `-> tuple[float | RangeValue, list[str]] | None` ; mettre à jour la docstring. Les « `if total > 0` » de la Task 4 disparaissent pour les fourchettes — garder le garde pour la valeur simple : `if isinstance(total, RangeValue) or total > 0:`.)

`ModelParamsResolver` — cache read/write via les helpers :

```python
    def _from_cache(self, provider: str, model: str) -> ParamsResult | None:
        """Tier 2 : params déclarés par l'utilisateur ou résolus précédemment via HF,
        mémorisés dans la config (clé « provider/model »)."""
        entry = self.config.model_params.get(f"{provider}/{model}")
        if entry is None:
            return None
        return ParamsResult(
            active=_param_from_json(entry["active"]),
            total=_param_from_json(entry["total"]),
            arch=entry.get("arch", "dense"), source=entry.get("source", "user"))
```

Et dans `_from_huggingface` (écriture) :

```python
        self.config.model_params[key] = {
            "active": _param_to_json(res.active), "total": _param_to_json(res.total),
            "arch": res.arch, "source": res.source}
```

`agent_carbon/resolve/cli.py` — affichage et validation MoE :

```python
from ecologits.utils.range_value import RangeValue


def fmt_params_md(v) -> str:
    """Formatte un compte de params (Md) — valeur ou fourchette."""
    if isinstance(v, RangeValue):
        return f"{v.min:.1f}–{v.max:.1f}"
    return f"{v:.1f}"
```

Dans `set_mappings`, la validation `active > params.total` devient (le total peut être une fourchette) :

```python
            total_max = params.total.max if isinstance(params.total, RangeValue) else params.total
            if active <= 0 or active > total_max:
```

Et le stockage passe par les helpers :

```python
        from agent_carbon.impact.params import _param_to_json
        config.model_params[key] = {
            "active": _param_to_json(entry_active), "total": _param_to_json(params.total),
            "arch": arch, "source": "resolve", "hf_repo": repo}
        results.append({"key": key, "repo": repo, "ok": True,
                        "params": fmt_params_md(params.total),
                        "active": fmt_params_md(entry_active), "arch": arch})
```

Dans `_print_set`, les valeurs sont déjà formatées (chaînes) :

```python
        if r["ok"]:
            if r.get("arch") == "moe":
                detail = f"MoE {r['active']} actifs / {r['params']} Md"
            else:
                detail = f"{r['params']} Md"
```

`agent_carbon/__main__.py` — `_cmd_models` lit le cache avec le helper (ligne ~112) :

```python
            from agent_carbon.impact.params import _param_from_json
            if cache_entry is not None:
                cached = _param_from_json(cache_entry.get("total", active))
                cache_total = cached.max if hasattr(cached, "max") else float(cached)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: tous PASS. Points de friction attendus : tests de `resolve_cli` qui assertaient `r["params"]` numérique (devenu chaîne formatée) → adapter ces assertions.

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/impact/params.py agent_carbon/resolve/cli.py agent_carbon/__main__.py tests/test_params_huggingface.py tests/test_engine_selfhosted.py tests/test_resolve_cli.py
git commit -m "feat: fourchette de params quand le dtype est inconnu (M2b)"
```

---

### Task 6: M2c — remonter l'estimation dans le rapport

**Files:**

- Modify: `agent_carbon/store/db.py` (nouvelle méthode)
- Modify: `agent_carbon/report/cli.py` (nouvelle fonction de rendu)
- Modify: `agent_carbon/__main__.py` (branche `report`, après `render_tokens_by_model`)
- Test: `tests/test_report.py`, `tests/test_store.py`

**Interfaces:**

- Consumes: colonne `impacts.warnings` (JSON list, déjà peuplée) ; warnings des Tasks 4-5 (`params-bytes-per-param:*`, `params-range-unknown-dtype`, `params-from-cli-used_storage`).
- Produces: `SQLiteStore.estimated_param_models(since: str | None = None) -> list[str]` ; `render_estimated_note(models: list[str]) -> str` (chaîne vide si rien).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_store.py` (reprendre le style des tests existants du fichier pour créer store/event) :

```python
def test_estimated_param_models_lists_models_with_estimation_warnings(tmp_path):
    """M2c : les modèles dont les params sont estimés (taille de fichiers)
    ressortent pour être signalés dans le rapport."""
    import json as _json
    from agent_carbon.store.db import SQLiteStore
    store = SQLiteStore(str(tmp_path / "t.db"))
    store.conn.execute(
        "INSERT INTO events VALUES ('s1','m1','ollama','est-model',1,2,0,0,"
        "'2026-07-02T00:00:00+00:00','p',0,'')")
    store.conn.execute(
        "INSERT INTO impacts VALUES ('s1','m1','est-model','WOR','v',"
        "1,2,1,2,1,2,1,2,1,2,'{}',?,NULL)",
        (_json.dumps(["params-from-cli-used_storage", "params-bytes-per-param:0.5"]),))
    store.conn.execute(
        "INSERT INTO events VALUES ('s1','m2','openai','gpt-4o-mini',1,2,0,0,"
        "'2026-07-02T00:00:00+00:00','p',0,'')")
    store.conn.execute(
        "INSERT INTO impacts VALUES ('s1','m2','gpt-4o-mini','WOR','v',"
        "1,2,1,2,1,2,1,2,1,2,'{}','[]',NULL)")
    store.conn.commit()
    assert store.estimated_param_models() == ["est-model"]
```

Ajouter à `tests/test_report.py` :

```python
def test_render_estimated_note():
    """M2c : note d'avertissement listant les modèles à params estimés."""
    from agent_carbon.report.cli import render_estimated_note
    assert render_estimated_note([]) == ""
    note = render_estimated_note(["est-model", "autre"])
    assert "est-model" in note and "autre" in note
    assert "estim" in note.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store.py::test_estimated_param_models_lists_models_with_estimation_warnings tests/test_report.py::test_render_estimated_note -v`
Expected: FAIL — `AttributeError` / `ImportError`.

- [ ] **Step 3: Write minimal implementation**

`agent_carbon/store/db.py` (après `uncovered_by_model`) :

```python
    def estimated_param_models(self, since: str | None = None) -> list[str]:
        """Modèles mesurés dont les params viennent d'une estimation par taille
        de fichiers (dtype supposé ou fourchette) — signalés dans le rapport."""
        sql = (
            "SELECT DISTINCT e.model FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NULL AND ("
            "i.warnings LIKE '%params-bytes-per-param%' "
            "OR i.warnings LIKE '%params-range-unknown-dtype%' "
            "OR i.warnings LIKE '%params-from-cli-used_storage%')"
        )
        params: list = []
        if since:
            sql += " AND e.timestamp >= ?"
            params.append(since)
        sql += " ORDER BY e.model"
        return [r["model"] for r in self.conn.execute(sql, tuple(params))]
```

`agent_carbon/report/cli.py` (fin de fichier, style des autres `render_*`) :

```python
def render_estimated_note(models: list[str]) -> str:
    """Note d'avertissement : params estimés depuis la taille des fichiers
    (dtype supposé, précision limitée). Chaîne vide si aucun modèle concerné."""
    if not models:
        return ""
    return ("⚠️  Params estimés depuis la taille des fichiers (précision limitée) : "
            + ", ".join(models))
```

`agent_carbon/__main__.py`, branche `report`, après le bloc `tokens` :

```python
        estimated = render_estimated_note(store.estimated_param_models(args.since))
        if estimated:
            out += "\n\n" + estimated
```

(ajouter `render_estimated_note` à l'import `from agent_carbon.report.cli import (...)`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_report.py tests/test_cli_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/store/db.py agent_carbon/report/cli.py agent_carbon/__main__.py tests/test_store.py tests/test_report.py
git commit -m "feat: le rapport signale les modèles à params estimés (M2c)"
```

---

### Task 7: N1 — ids synthétiques pour les events Crush sans identifiants

**Files:**

- Modify: `agent_carbon/collectors/crush.py`
- Test: `tests/test_crush_collector.py`

**Interfaces:**

- Consumes: `CrushCollector._parse_export` / `_backfill_rows` existants.
- Produces: `_synthetic_id(prefix: str, *parts) -> str` (sha1 tronqué 16 hex, déterministe) ; plus aucun `InferenceEvent` Crush avec `msg_id == ""`. Nettoyage : la branche morte `info.get("ID")` (absente du format d'export, cf. fixture `tests/fixtures/crush-export.json`) disparaît.

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_crush_collector.py` (reprendre les helpers du fichier pour écrire un export temporaire) :

```python
def test_messages_without_ids_get_distinct_deterministic_ids(tmp_path):
    """N1 : deux messages assistant sans id ne se téléscopent pas (PK DB) et
    l'id synthétique est déterministe d'un run à l'autre."""
    import json
    from agent_carbon.collectors.crush import CrushCollector
    export = {
        "info": {"id": "sess-1"},
        "directory": "/Users/me/DEV/projA",
        "messages": [
            {"data": {"role": "assistant",
                      "model": {"providerID": "ollama", "modelID": "m"},
                      "tokens": {"input": 10, "output": 5},
                      "time": {"created": 1719741600000}}},
            {"data": {"role": "assistant",
                      "model": {"providerID": "ollama", "modelID": "m"},
                      "tokens": {"input": 20, "output": 7},
                      "time": {"created": 1719741660000}}},
        ],
    }
    p = tmp_path / "export.json"
    p.write_text(json.dumps(export))
    events1 = list(CrushCollector(root=str(p)).collect())
    events2 = list(CrushCollector(root=str(p)).collect())
    assert len(events1) == 2
    assert events1[0].msg_id and events1[1].msg_id          # jamais vide
    assert events1[0].msg_id != events1[1].msg_id           # distincts
    assert events1[0].msg_id == events2[0].msg_id           # déterministe
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_crush_collector.py::test_messages_without_ids_get_distinct_deterministic_ids -v`
Expected: FAIL — `assert events1[0].msg_id` (vide).

- [ ] **Step 3: Write minimal implementation**

Dans `agent_carbon/collectors/crush.py`, en tête ajouter `import hashlib`, puis au niveau module :

```python
def _synthetic_id(prefix: str, *parts) -> str:
    """Id déterministe pour un event sans identifiant : évite que tous les
    events ("","") s'écrasent sur la même PK en DB (perte silencieuse)."""
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"
```

Dans `_parse_export`, remplacer les blocs Session / Msg ID :

```python
            # Session (la branche `info.get("ID")` était morte : le format
            # d'export ne la contient pas — cf. tests/fixtures/crush-export.json)
            session_id = info.get("session_id") or obj.get("info", {}).get("id", "")
            if not session_id:
                session_id = _synthetic_id("crush-sess", path)

            ...

            # Msg ID — synthétique si absent (déterministe : mêmes champs → même id)
            msg_id = info.get("id") or _synthetic_id(
                "crush", session_id, ts_ms, model, input_tokens, output_tokens)
```

(`path` est le paramètre de `_parse_export` ; déplacer le calcul de `session_id` avant celui de `msg_id` si besoin.)

Dans `_backfill_rows`, même filet pour `msg_id` :

```python
            # Msg ID — synthétique si absent
            msg_id = msg["id"] or _synthetic_id(
                "crush", session_id, created_ms, model, input_tokens, output_tokens)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_crush_collector.py -v`
Expected: PASS (les tests existants du fichier valident que le format nominal est inchangé).

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/collectors/crush.py tests/test_crush_collector.py
git commit -m "fix: ids synthétiques déterministes pour les events Crush sans identifiant (N1)"
```

---

### Task 8: N2 — timestamps canoniques UTC en DB (+ micro-perf add_pending)

**Files:**

- Modify: `agent_carbon/store/db.py` (`__init__` migration, `ingest`, `add_pending`)
- Test: `tests/test_store.py`

**Interfaces:**

- Consumes: `_parse_ts` existant (`db.py:46`).
- Produces: `_canonical_ts(ts: str) -> str` (ISO UTC `+00:00` ; entrée invalide renvoyée telle quelle) ; migration à l'ouverture (suffixe `Z` → `+00:00` dans `events.timestamp` et `sessions.started_at/ended_at`) ; `add_pending` ne commit plus (le commit final d'`ingest` couvre).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_store.py` :

```python
def test_ingest_normalizes_timestamp_to_utc_canonical(tmp_path):
    """N2 : un timestamp « Z » est stocké en ISO UTC canonique (+00:00)."""
    from agent_carbon.store.db import SQLiteStore, _canonical_ts
    assert _canonical_ts("2026-07-02T10:00:00Z") == "2026-07-02T10:00:00+00:00"
    assert _canonical_ts("2026-07-02T12:00:00+02:00") == "2026-07-02T10:00:00+00:00"
    assert _canonical_ts("pas-une-date") == "pas-une-date"  # laissé tel quel


def test_open_migrates_legacy_z_timestamps(tmp_path):
    """N2 : à l'ouverture, les vieux timestamps « …Z » sont convertis en +00:00."""
    import sqlite3
    from agent_carbon.store.db import SQLiteStore
    db = str(tmp_path / "t.db")
    s = SQLiteStore(db)
    s.conn.execute(
        "INSERT INTO events VALUES ('s1','m1','p','mod',1,2,0,0,"
        "'2026-07-02T10:00:00Z','proj',0,'')")
    s.conn.execute(
        "INSERT INTO sessions VALUES ('s1','proj','2026-07-02T10:00:00Z','2026-07-02T11:00:00Z')")
    s.conn.commit()
    s.conn.close()
    s2 = SQLiteStore(db)  # la migration tourne à l'ouverture
    ts = s2.conn.execute("SELECT timestamp FROM events").fetchone()[0]
    assert ts == "2026-07-02T10:00:00+00:00"
    row = s2.conn.execute("SELECT started_at, ended_at FROM sessions").fetchone()
    assert row[0].endswith("+00:00") and row[1].endswith("+00:00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store.py -v -k "canonical or migrates_legacy"`
Expected: FAIL — `ImportError: cannot import name '_canonical_ts'`.

- [ ] **Step 3: Write minimal implementation**

`agent_carbon/store/db.py` — en tête ajouter `from datetime import datetime, timezone` (remplace l'import `datetime` seul), puis :

```python
def _canonical_ts(ts: str) -> str:
    """ISO UTC canonique (+00:00) : un seul format en DB → comparaisons
    lexicales sûres (N2). Entrée non parsable renvoyée telle quelle."""
    dt = _parse_ts(ts)
    if dt is None:
        return ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
```

Dans `SQLiteStore.__init__`, après les migrations de colonnes :

```python
        # Migration N2 : timestamps hérités « …Z » → format canonique « +00:00 »
        # (idempotent : ne touche que les lignes au vieux format).
        self.conn.execute(
            "UPDATE events SET timestamp = replace(timestamp,'Z','+00:00') "
            "WHERE timestamp LIKE '%Z'")
        self.conn.execute(
            "UPDATE sessions SET started_at = replace(started_at,'Z','+00:00'), "
            "ended_at = replace(ended_at,'Z','+00:00') "
            "WHERE started_at LIKE '%Z' OR ended_at LIKE '%Z'")
        self.conn.commit()
```

Dans `ingest`, normaliser avant insertion (début de la boucle `for e in events:`) :

```python
        for e in events:
            e.timestamp = _canonical_ts(e.timestamp)
```

(Si `InferenceEvent` est un dataclass frozen, utiliser `dataclasses.replace(e, timestamp=_canonical_ts(e.timestamp))` — vérifier `agent_carbon/models.py`.)

Dans `add_pending`, retirer la ligne `self.conn.commit()` (le commit final d'`ingest` couvre ; `list_pending`/`clear_pending` gardent le leur) :

```python
    def add_pending(self, provider: str, model: str, ts: str) -> None:
        self.conn.execute(
            "INSERT INTO pending_models (provider, model, first_seen, occurrences) "
            "VALUES (?,?,?,1) "
            "ON CONFLICT(provider, model) DO UPDATE SET occurrences = occurrences + 1",
            (provider, model, ts),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_pending_models.py tests/test_cli_end_to_end.py -v`
Expected: PASS. Si un test de `test_pending_models.py` appelait `add_pending` hors ingest et relisait via une **autre connexion**, ajouter un `store.conn.commit()` dans le test (même connexion : aucun impact).

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/store/db.py tests/test_store.py
git commit -m "fix: timestamps ISO UTC canoniques en DB + migration des anciens (N2)"
```

---

### Task 9: N3 — `--retry-hf` et aide CLI explicite pour `--recompute`

**Files:**

- Modify: `agent_carbon/__main__.py` (parser `resolve`, lignes ~218-227)
- Modify: `agent_carbon/resolve/cli.py` (`cmd_resolve`)
- Modify: `agent_carbon/store/db.py` (`recompute_errors` — paramètre `retry_all`, nouvelle méthode `uncovered_keys`)
- Test: `tests/test_resolve_cli.py`

**Interfaces:**

- Consumes: `Config.hf_unresolved` (Task 2), `recompute_errors(engine, config)` existant.
- Produces: `SQLiteStore.uncovered_keys() -> list[tuple[str, str]]` (couples provider/model en erreur, hors `<synthetic>`) ; `recompute_errors(engine, config, retry_all: bool = False)` (True = ne pas filtrer sur les mappings → la cascade HF est retentée) ; flag CLI `resolve --retry-hf`.

- [ ] **Step 1: Write the failing test**

Ajouter à `tests/test_resolve_cli.py` (reprendre le style du fichier : construction d'un store tmp + `argparse.Namespace`) :

```python
def test_retry_hf_resolves_uncovered_via_cascade(tmp_path, monkeypatch):
    """N3 : --retry-hf purge le cache négatif et retente la cascade HF sur les
    non couverts (sans mapping manuel)."""
    import json as _json
    from types import SimpleNamespace
    import agent_carbon.impact.params as params_mod
    from agent_carbon.impact.params import ParamsResult
    from agent_carbon.config import Config
    from agent_carbon.resolve.cli import cmd_resolve
    from agent_carbon.store.db import SQLiteStore

    db = str(tmp_path / "t.db")
    store = SQLiteStore(db)
    store.conn.execute(
        "INSERT INTO events VALUES ('s1','m1','ollama','org/nouveau',1,2,0,0,"
        "'2026-07-02T00:00:00+00:00','p',0,'')")
    store.conn.execute(
        "INSERT INTO impacts VALUES ('s1','m1','org/nouveau','WOR','v',"
        "NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
        "'{}','[]','model-params-unresolved')")
    store.conn.commit()
    store.conn.close()

    # Config isolée (ne pas toucher ~/.agent-carbon) + HF factice qui réussit
    cfg = Config(electricity_mix_zone="WOR",
                 hf_unresolved={"ollama/org/nouveau": "2026-07-02T00:00:00+00:00"})
    monkeypatch.setattr(Config, "load", classmethod(lambda cls, path=None: cfg))
    monkeypatch.setattr(Config, "save", lambda self, path=None: None)
    monkeypatch.setattr(params_mod, "fetch_hf_params",
                        lambda repo: ParamsResult(active=7.0, total=7.0,
                                                  arch="dense", source="huggingface"))

    args = SimpleNamespace(db=db, since=None, list=False, json=False,
                           set=[], forget=[], recompute=False, retry_hf=True)
    assert cmd_resolve(args) == 0
    assert "ollama/org/nouveau" not in cfg.hf_unresolved  # purgé avant retente
    check = SQLiteStore(db)
    assert check.coverage()["uncovered"] == 0             # résolu par la cascade
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_resolve_cli.py::test_retry_hf_resolves_uncovered_via_cascade -v`
Expected: FAIL — `AttributeError: 'SimpleNamespace' object has no attribute 'retry_hf'` n'arrive pas (l'attr existe dans le Namespace) mais `cmd_resolve` l'ignore → `uncovered == 1`.

- [ ] **Step 3: Write minimal implementation**

`agent_carbon/store/db.py` :

```python
    def uncovered_keys(self) -> list[tuple[str, str]]:
        """Couples (provider, model) des events à impact non estimé,
        hors placeholders `<synthetic>`."""
        return [(r["provider"], r["model"]) for r in self.conn.execute(
            "SELECT DISTINCT e.provider, e.model FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NOT NULL AND e.model != '<synthetic>'")]
```

Dans `recompute_errors`, signature et filtre :

```python
    def recompute_errors(self, engine: EcoLogitsEngine, config: Config,
                         retry_all: bool = False) -> dict:
        """Recalcule l'impact des events en erreur.

        Par défaut, seuls les modèles ayant un mapping dans config.model_params
        sont repris (évite les calculs inutiles) — donc **sans mapping,
        --recompute seul ne tente rien**. Avec retry_all=True (--retry-hf),
        tous les events en erreur (hors <synthetic>) repassent par la cascade,
        y compris le tier Hugging Face."""
        before = self.coverage()["uncovered"]
        rows = self.conn.execute(
            "SELECT e.* FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NOT NULL AND e.model != '<synthetic>'"
        ).fetchall()
        if not retry_all:
            mapped_keys = set(config.model_params.keys())
            rows = [r for r in rows
                    if f"{r['provider']}/{r['model']}" in mapped_keys] if mapped_keys else []
        ...  # (boucle batch existante inchangée)
```

`agent_carbon/__main__.py`, parser `resolve` :

```python
    p_res.add_argument("--recompute", action="store_true",
                       help="recalcule les events en erreur des modèles déjà mappés "
                            "(ne tente PAS de nouvelle résolution — voir --retry-hf)")
    p_res.add_argument("--retry-hf", dest="retry_hf", action="store_true",
                       help="purge le cache négatif des non couverts et retente la "
                            "cascade Hugging Face sur tous les events en erreur")
```

`agent_carbon/resolve/cli.py`, dans `cmd_resolve` (après le bloc `forgotten_models`, avant le `if args.recompute or changed:`) :

```python
    retry_hf = getattr(args, "retry_hf", False)
    if retry_hf:
        # Purge du cache négatif pour les modèles encore non couverts, puis
        # recompute complet : la cascade retentera le tier Hugging Face.
        for provider, model in store.uncovered_keys():
            config.hf_unresolved.pop(f"{provider}/{model}", None)
    if args.recompute or retry_hf or changed:
        engine = EcoLogitsEngine(ModelResolver(config.model_aliases))
        _print_recompute(store.recompute_errors(engine, config, retry_all=retry_hf))
        if retry_hf:
            config.save()  # persiste les succès (cache positif) et les nouveaux échecs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_resolve_cli.py tests/test_resolve.py tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/__main__.py agent_carbon/resolve/cli.py agent_carbon/store/db.py tests/test_resolve_cli.py
git commit -m "feat: resolve --retry-hf retente la cascade HF sur les non couverts (N3)"
```

---

### Task 10: N4 — plafonds de la méthode 3 + validation du format de repo

**Files:**

- Modify: `agent_carbon/impact/params.py` (`_fetch_safetensors_index_bytes`, `_fetch_hf_total_params`)
- Test: `tests/test_params_huggingface.py`

**Interfaces:**

- Consumes: méthode 3 existante (index.json + HEAD).
- Produces: constantes `_MAX_INDEX_FILES = 30` et `_INDEX_BUDGET_SECONDS = 60` ; regex `_REPO_RE` — un repo au format invalide (`espaces`, pas de `/`, chemins `..`) court-circuite **toute** la cascade HF (aucune requête réseau).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_params_huggingface.py` :

```python
def test_invalid_repo_format_short_circuits_without_network(monkeypatch):
    """Mineur : un identifiant non « org/name » ne déclenche aucune requête."""
    import agent_carbon.impact.params as params_mod
    called = []
    mod = types.ModuleType("huggingface_hub")
    mod.model_info = lambda repo_id, **kw: called.append(repo_id)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    monkeypatch.setattr(params_mod, "_fetch_hf_cli_info",
                        lambda repo: called.append(repo))
    monkeypatch.setattr(params_mod, "_fetch_safetensors_index_bytes",
                        lambda repo: called.append(repo))
    assert fetch_hf_params("<synthetic>") is None
    assert fetch_hf_params("juste-un-nom") is None
    assert fetch_hf_params("org/../etc") is None
    assert called == []  # aucune méthode réseau appelée


def test_index_with_too_many_files_aborts(monkeypatch):
    """N4 : index.json avec plus de _MAX_INDEX_FILES shards → abandon propre."""
    import io
    import json as _json
    import urllib.request
    from agent_carbon.impact.params import _fetch_safetensors_index_bytes
    index = {"weight_map": {f"w{i}": f"shard-{i}.safetensors" for i in range(31)}}
    head_calls = []

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("index.json"):
            return io.BytesIO(_json.dumps(index).encode())
        head_calls.append(url)
        resp = io.BytesIO(b"")
        resp.headers = {"Content-Length": "1000"}
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert _fetch_safetensors_index_bytes("org/gros-modele") is None
    assert head_calls == []  # aucun HEAD lancé au-delà du plafond
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py -v -k "invalid_repo or too_many_files"`
Expected: FAIL — `called` non vide / 31 HEAD effectués.

- [ ] **Step 3: Write minimal implementation**

`agent_carbon/impact/params.py` — constantes et regex au niveau module :

```python
# N4 : plafonds de la méthode 3 (index.json + HEAD séquentiels).
_MAX_INDEX_FILES = 30
_INDEX_BUDGET_SECONDS = 60.0

# Identifiant de repo HF valide : « org/name » (lettres, chiffres, . _ -).
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")
```

Dans `_fetch_hf_total_params`, tout en haut (avant l'import huggingface_hub) :

```python
    if not _REPO_RE.match(repo):
        # Identifiant impossible sur le Hub (placeholder, nom local, path
        # traversal) : aucune requête réseau.
        return None
```

Dans `_fetch_safetensors_index_bytes`, après extraction de `files` (ajouter `import time` en tête de fichier) :

```python
        files = sorted(set(weight_map.values()))
        if len(files) > _MAX_INDEX_FILES:
            return None  # trop de shards : budget réseau déraisonnable, on abandonne

        base_url = f"https://huggingface.co/{repo}/resolve/main/"
        total_bytes = 0
        start = time.monotonic()
        for f in files:
            if time.monotonic() - start > _INDEX_BUDGET_SECONDS:
                return None  # budget temps global dépassé
            try:
                ...  # (HEAD existant inchangé)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_params_huggingface.py -v`
Expected: PASS. Bonus : `test_huggingface_network_error_returns_none` (repo `whatever`, sans `/`) devient hermétique — il ne peut plus déclencher de vraie requête vers huggingface.co.

- [ ] **Step 5: Commit**

```bash
git add agent_carbon/impact/params.py tests/test_params_huggingface.py
git commit -m "fix: plafonds réseau méthode 3 et validation du format de repo (N4)"
```

---

### Task 11: Documentation, statut de la spec et validation finale

**Files:**

- Modify: `CONTRIBUTING.md` (section « Résolution de modèles », section Backlog)
- Modify: `docs/METHODOLOGY.md` (estimation des params auto-hébergés)
- Modify: `docs/SPEC-qualite-lecture-resolution.md` (marquer les items livrés)
- Modify: `agent_carbon/impact/params.py` (docstring de `_fetch_hf_cli_info` — heuristique du binaire)

**Interfaces:**

- Consumes: tout ce qui précède.
- Produces: doc à jour ; suite complète verte.

- [ ] **Step 1: Documenter l'heuristique du binaire `hf`**

Dans `agent_carbon/impact/params.py`, compléter la docstring de `_fetch_hf_cli_info` :

```python
def _fetch_hf_cli_info(repo: str) -> dict | None:
    """Récupère les infos d'un repo HF via le CLI `hf models info`.
    Retourne le dict d'info ou None en cas d'échec.

    Heuristique de localisation du binaire (fail-safe : introuvable → None,
    la cascade continue) : 1) PATH, 2) venv actif (déduit de sys.executable),
    3) `.venv/bin/hf` du cwd puis de ~/.agent-carbon/src (clone installé)."""
```

- [ ] **Step 2: Mettre à jour CONTRIBUTING.md**

Dans la section « Résolution de modèles » (ligne ~140), remplacer le paragraphe par :

```markdown
- **Résolution de modèles** : la cascade vit dans `impact/params.py` ; la CLI
  `resolve` (déterministe : HF + recompute) dans `resolve/cli.py` ; le mapping
  nom→repo (jugement) dans le skill `/agent-carbon-resolve`. Les échecs HF sont
  mémorisés (cache négatif en mémoire + persisté dans `config.json`, TTL 7 jours) ;
  `resolve --retry-hf` purge ce cache et retente la cascade sur les non couverts.
  Les params estimés depuis la taille des fichiers portent des warnings de
  provenance (`params-bytes-per-param:<n>`, `params-range-unknown-dtype`) et sont
  signalés dans le rapport.
```

- [ ] **Step 3: Mettre à jour docs/METHODOLOGY.md**

Ajouter (dans la section qui traite des modèles auto-hébergés / paramètres, à la fin si aucune ne convient) :

```markdown
## Estimation des paramètres des modèles auto-hébergés

Quand un modèle n'est ni dans le registre EcoLogits ni doté de metadata
safetensors, ses paramètres sont **estimés depuis la taille des fichiers** du
repo Hugging Face. Le dtype (octets/param) est déduit du nom du repo
(`-4bit` → 0.5, `-int8` → 1, `-fp16`/`-bf16` → 2, `-fp32` → 4) ; s'il est
indétectable, on produit une **fourchette** (0.5–2 octets/param, soit un
rapport 1:4 sur les params) plutôt qu'une valeur unique. Ces estimations
portent un warning de provenance en base et les modèles concernés sont
signalés dans le rapport (« Params estimés depuis la taille des fichiers »).
```

- [ ] **Step 4: Marquer la spec**

Dans `docs/SPEC-qualite-lecture-resolution.md`, préfixer chaque titre d'item livré : `### M1 — …` → `### ✅ M1 — …` (M1, M2, M3, N1, N2, N3, N4) et les 4 puces mineures → préfixe `✅`. Ajouter sous le titre du document : `> Statut : correctifs livrés le <date du jour> (voir CHANGELOG).`

- [ ] **Step 5: Validation finale**

Run: `.venv/bin/python -m pytest -q`
Expected: tous PASS (~180 tests).

Run: `.venv/bin/python -m agent_carbon report --db /tmp/inexistant-test.db 2>&1 | head -5` _(sanity : la CLI démarre sans stacktrace sur une DB vierge — utiliser le scratchpad de session plutôt que /tmp si disponible)_
Expected: rapport vide sans erreur.

- [ ] **Step 6: Commit**

```bash
git add CONTRIBUTING.md docs/METHODOLOGY.md docs/SPEC-qualite-lecture-resolution.md agent_carbon/impact/params.py
git commit -m "docs: méthodologie d'estimation des params et statut de la spec qualité"
```

---

## Self-Review

- **Spec coverage** : M1 → Tasks 1-2 ; M2 → Tasks 4-6 ; M3 → Task 3 ; N1 → Task 7 ; N2 → Task 8 ; N3 → Task 9 ; N4 + validation repo → Task 10 ; mineurs `ID` mort → Task 7, `add_pending` commit → Task 8, doc heuristique `hf` → Task 11. L'évolution 🔵 (recherche web) est **déjà livrée** (édition de `skills/agent-carbon-resolve/SKILL.md`, commit `7bc0140`) — hors périmètre de ce plan.
- **Types cohérents** : `ParamsResult.active/total: float | RangeValue` (Task 5) est consommé par `engine._compute_selfhosted` (passe tel quel à `compute_llm_impacts`), `resolve/cli.set_mappings` (via `fmt_params_md`/`total_max`) et `__main__._cmd_models` (via `_param_from_json`). `hf_unresolved: dict[str, str]` défini Task 2, purgé Task 9. `recompute_errors(..., retry_all=False)` défini Task 9, compatible avec l'appel existant sans le paramètre.
- **Rappel deux codebases** : après merge sur `main`, faire une release (`agent-carbon release bump minor`) puis relancer le script d'install pour aligner `~/.agent-carbon/src` (cf. AGENTS.md).
