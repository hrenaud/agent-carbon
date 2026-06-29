# agent-carbon-resolve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de résoudre les modèles « non couverts » (impact non estimé) en mappant leur nom vers un repo Hugging Face, en récupérant les paramètres sur HF, et en recalculant les impacts déjà en base.

**Architecture :** Primitives CLI fines et déterministes (`agent-carbon resolve --list/--set/--recompute/--forget`) testables sans LLM, orchestrées par un skill `/agent-carbon-resolve` où le LLM fournit le mapping nom→repo. Les paramètres viennent toujours de HF (vérifiables) ; un recompute met à jour les impacts en base.

**Tech Stack :** Python 3.10+, sqlite3, EcoLogits, huggingface_hub, pytest, argparse.

## Global Constraints

- Réponses et messages produits en **français**.
- Tests **avant** implémentation (TDD) : écrire le test, le voir échouer, implémenter, le voir passer, committer.
- Paramètres EcoLogits **en milliards** partout (`ParamsResult.active/total`, `model_params`). `safetensors.total` (HF) = compte brut → `÷ 1e9`.
- Ne jamais utiliser `rm` (utiliser `trash`).
- Commits sémantiques (`feat:`, `refactor:`, `docs:`, `test:`).
- Lancer les tests avec `.venv/bin/python -m pytest`.
- Mettre à jour CHANGELOG/doc en même temps que le code.
- `fetch_hf_params` et toute interaction HF doivent être **offline-safe** : lib absente, réseau, 404, identifiant invalide → `None`, jamais d'exception.

---

## Task 0 : Base de travail — committer la feature « Modèles non couverts »

La feature « Modèles non couverts » (section rapport + exclusion des `<synthetic>`) est déjà implémentée et testée mais **non commitée**. Le chantier resolve s'appuie dessus (`store.uncovered_by_model`, `render_uncovered`). On la committe d'abord sur une branche dédiée.

**Files :**

- Modify (déjà éditées, à committer) : `agent_carbon/store/db.py`, `agent_carbon/report/cli.py`, `agent_carbon/__main__.py`, `skills/agent-carbon-report/SKILL.md`, `README.md`, `CHANGELOG.md`, `tests/test_store.py`, `tests/test_report.py`

- [ ] **Step 1 : Vérifier que la suite est verte**

Run : `.venv/bin/python -m pytest -q`
Expected : `75 passed`

- [ ] **Step 2 : Créer la branche et committer**

```bash
git checkout -b feat/agent-carbon-resolve
git add -A
git commit -m "feat: section « Modèles non couverts » + exclusion des <synthetic>"
```

---

## Task 1 : Helper `fetch_hf_params(repo)` (extraction repo→params)

Extraire la partie « repo HF → paramètres » de `_from_huggingface` en fonction de module réutilisable, pour qu'un repo **arbitraire** (≠ nom du modèle) puisse être interrogé par `resolve --set`.

**Files :**

- Modify : `agent_carbon/impact/params.py`
- Test : `tests/test_params_huggingface.py`

**Interfaces :**

- Produces : `fetch_hf_params(repo: str) -> ParamsResult | None` (module-level dans `params.py`). `ParamsResult.source == "huggingface"`, `arch == "dense"`, `warnings == ["moe-assumed-dense"]`, `active == total == safetensors.total / 1e9`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter dans `tests/test_params_huggingface.py` (le helper `_fake_hf` existe déjà dans ce fichier) :

```python
from agent_carbon.impact.params import fetch_hf_params


def test_fetch_hf_params_returns_billions(monkeypatch):
    _fake_hf(7_000_000_000, monkeypatch)
    res = fetch_hf_params("Org/Repo")
    assert res is not None
    assert res.active == res.total == 7.0
    assert res.arch == "dense"
    assert res.source == "huggingface"


def test_fetch_hf_params_missing_lib_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    assert fetch_hf_params("Org/Repo") is None


def test_fetch_hf_params_no_safetensors_returns_none(monkeypatch):
    import types as _t
    mod = _t.ModuleType("huggingface_hub")
    mod.model_info = lambda repo_id, **kw: _t.SimpleNamespace(safetensors=None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    assert fetch_hf_params("Org/Repo") is None
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run : `.venv/bin/python -m pytest tests/test_params_huggingface.py -q`
Expected : FAIL `ImportError: cannot import name 'fetch_hf_params'`

- [ ] **Step 3 : Implémenter le helper et refactorer `_from_huggingface`**

Dans `agent_carbon/impact/params.py`, ajouter au niveau module (après les imports/`ParamsResult`) :

```python
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
        total = float(info.safetensors.total) / 1e9
    except Exception:
        return None
    if total <= 0:
        return None
    return ParamsResult(active=total, total=total, arch="dense",
                        source="huggingface", warnings=["moe-assumed-dense"])
```

Puis remplacer le corps de `ModelParamsResolver._from_huggingface` par un appel au helper (en conservant la mise en cache) :

```python
    def _from_huggingface(self, provider: str, model: str) -> ParamsResult | None:
        """Tier 3 : params depuis le Hub via fetch_hf_params, puis mise en cache."""
        res = fetch_hf_params(model)
        if res is None:
            return None
        self.config.model_params[f"{provider}/{model}"] = {
            "active": res.active, "total": res.total,
            "arch": res.arch, "source": res.source}
        return res
```

- [ ] **Step 4 : Lancer les tests pour les voir passer**

Run : `.venv/bin/python -m pytest tests/test_params_huggingface.py -q`
Expected : PASS (anciens tests HF inclus, inchangés)

- [ ] **Step 5 : Committer**

```bash
git add agent_carbon/impact/params.py tests/test_params_huggingface.py
git commit -m "refactor: extraire fetch_hf_params (repo→params réutilisable)"
```

---

## Task 2 : `store.recompute_errors(engine, config)`

Recalculer les impacts de tous les events en erreur, pour que les modèles fraîchement résolus passent « couverts ».

**Files :**

- Modify : `agent_carbon/store/db.py`
- Test : `tests/test_store.py`

**Interfaces :**

- Consumes : `EcoLogitsEngine.compute`, `self._store_impact`, `self.coverage`, `InferenceEvent` (déjà importé dans `db.py`).
- Produces : `SQLiteStore.recompute_errors(engine, config) -> dict` retournant `{"before": int, "after": int}` (nombre de non couverts avant/après).

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter dans `tests/test_store.py` :

```python
def test_recompute_errors_resolves_after_params_added(tmp_path):
    store = SQLiteStore(str(tmp_path / "c.db"))
    # « x:y » : le « : » fait échouer HF sans réseau → event en erreur
    events = [
        InferenceEvent("ollama", "x:y", 100, 200, 0, 0,
                       "2026-06-27T10:00:00.000Z", "p", "s", "u1"),
        InferenceEvent("anthropic", "<synthetic>", 0, 0, 0, 0,
                       "2026-06-27T10:01:00.000Z", "p", "s", "u2"),
    ]
    store.ingest(events, _engine(), Config())
    assert store.coverage()["uncovered"] == 2
    cfg = Config(electricity_mix_zone="FRA",
                 model_params={"ollama/x:y": {
                     "active": 7.0, "total": 7.0, "arch": "dense",
                     "source": "resolve", "hf_repo": "Org/Repo"}})
    delta = store.recompute_errors(_engine(), cfg)
    assert delta == {"before": 2, "after": 1}   # x:y résolu, <synthetic> reste
    covered = [r for r in store.rows_for_report() if r["model"] == "ollama/x:y"]
    assert covered and covered[0]["gwp_min"] > 0
```

- [ ] **Step 2 : Lancer le test pour le voir échouer**

Run : `.venv/bin/python -m pytest tests/test_store.py::test_recompute_errors_resolves_after_params_added -q`
Expected : FAIL `AttributeError: 'SQLiteStore' object has no attribute 'recompute_errors'`

- [ ] **Step 3 : Implémenter `recompute_errors`**

Dans `agent_carbon/store/db.py`, ajouter la méthode (par ex. juste avant `coverage`) :

```python
    def recompute_errors(self, engine: EcoLogitsEngine, config: Config) -> dict:
        """Recalcule l'impact de tous les events en erreur (utile après ajout de
        params). Retourne {before, after} = nombre de non couverts avant/après."""
        before = self.coverage()["uncovered"]
        rows = self.conn.execute(
            "SELECT e.* FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NOT NULL"
        ).fetchall()
        for r in rows:
            e = InferenceEvent(
                provider=r["provider"], model=r["model"],
                input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
                cache_creation_tokens=r["cache_creation_tokens"],
                cache_read_tokens=r["cache_read_tokens"],
                timestamp=r["timestamp"], project=r["project"],
                session_id=r["session_id"], msg_id=r["msg_id"],
                active_seconds=r["active_seconds"], client=r["client"])
            self._store_impact(e, engine.compute(e, config))
        self.conn.commit()
        after = self.coverage()["uncovered"]
        return {"before": before, "after": after}
```

- [ ] **Step 4 : Lancer le test pour le voir passer**

Run : `.venv/bin/python -m pytest tests/test_store.py -q`
Expected : PASS

- [ ] **Step 5 : Committer**

```bash
git add agent_carbon/store/db.py tests/test_store.py
git commit -m "feat: store.recompute_errors (recalcule les impacts en erreur)"
```

---

## Task 3 : Module `resolve/cli.py` — actions `set` / `forget`

Logique pure de mutation de config : poser un mapping (params via HF) et l'oublier. Séparée de `__main__` pour rester focalisée et testable.

**Files :**

- Create : `agent_carbon/resolve/__init__.py` (vide)
- Create : `agent_carbon/resolve/cli.py`
- Test : `tests/test_resolve.py`

**Interfaces :**

- Consumes : `fetch_hf_params` (Task 1), `Config.model_params`.
- Produces :
  - `parse_mapping(spec: str) -> tuple[str, str]` → `("provider/model", "hf_repo")`.
  - `set_mappings(config, specs: list[str]) -> list[dict]` → items `{"key", "repo", "ok": bool, "params"?: float, "error"?: str}`. Écrit dans `config.model_params[key] = {active, total, arch, source:"resolve", hf_repo}` sur succès.
  - `forget(config, keys: list[str]) -> list[dict]` → items `{"key", "removed": bool}`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_resolve.py` :

```python
import sys
import types
from agent_carbon.config import Config
from agent_carbon.resolve.cli import parse_mapping, set_mappings, forget


def _fake_hf(total, monkeypatch):
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def test_parse_mapping_splits_on_first_equals():
    assert parse_mapping("anthropic/z-ai/glm:free=zai-org/GLM-4.5-Air") == (
        "anthropic/z-ai/glm:free", "zai-org/GLM-4.5-Air")


def test_set_mappings_writes_params_with_provenance(monkeypatch):
    _fake_hf(110_000_000_000, monkeypatch)
    cfg = Config()
    results = set_mappings(cfg, ["anthropic/glm:free=zai-org/GLM-4.5-Air"])
    assert results[0]["ok"] is True
    entry = cfg.model_params["anthropic/glm:free"]
    assert entry["total"] == 110.0
    assert entry["source"] == "resolve"
    assert entry["hf_repo"] == "zai-org/GLM-4.5-Air"


def test_set_mappings_reports_hf_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)  # HF indisponible
    cfg = Config()
    results = set_mappings(cfg, ["anthropic/foo=bar/baz"])
    assert results[0]["ok"] is False
    assert "anthropic/foo" not in cfg.model_params


def test_set_mappings_reports_bad_format():
    cfg = Config()
    results = set_mappings(cfg, ["pas-de-egal"])
    assert results[0]["ok"] is False
    assert results[0]["error"] == "format"


def test_forget_removes_entry():
    cfg = Config(model_params={"anthropic/glm:free": {"active": 110.0}})
    results = forget(cfg, ["anthropic/glm:free", "absent/xx"])
    assert results[0]["removed"] is True
    assert results[1]["removed"] is False
    assert "anthropic/glm:free" not in cfg.model_params
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run : `.venv/bin/python -m pytest tests/test_resolve.py -q`
Expected : FAIL `ModuleNotFoundError: No module named 'agent_carbon.resolve'`

- [ ] **Step 3 : Créer le package et implémenter les fonctions**

Créer `agent_carbon/resolve/__init__.py` (vide).

Créer `agent_carbon/resolve/cli.py` :

```python
from agent_carbon.impact.params import fetch_hf_params


def parse_mapping(spec: str) -> tuple[str, str]:
    """ 'provider/model=hf_repo' → ('provider/model', 'hf_repo'). Coupe au 1er '='."""
    key, _, repo = spec.partition("=")
    return key.strip(), repo.strip()


def set_mappings(config, specs: list[str]) -> list[dict]:
    """Pour chaque mapping, récupère les params sur HF et les persiste sous la clé
    provider/model avec provenance. Échec géré par item, sans interrompre les autres."""
    results = []
    for spec in specs:
        key, repo = parse_mapping(spec)
        if not key or not repo:
            results.append({"key": key, "repo": repo, "ok": False, "error": "format"})
            continue
        params = fetch_hf_params(repo)
        if params is None:
            results.append({"key": key, "repo": repo, "ok": False,
                            "error": "hf-unresolved"})
            continue
        config.model_params[key] = {
            "active": params.active, "total": params.total, "arch": params.arch,
            "source": "resolve", "hf_repo": repo}
        results.append({"key": key, "repo": repo, "ok": True, "params": params.total})
    return results


def forget(config, keys: list[str]) -> list[dict]:
    """Retire chaque clé de model_params (revert d'un mapping)."""
    return [{"key": k, "removed": config.model_params.pop(k, None) is not None}
            for k in keys]
```

- [ ] **Step 4 : Lancer les tests pour les voir passer**

Run : `.venv/bin/python -m pytest tests/test_resolve.py -q`
Expected : PASS

- [ ] **Step 5 : Committer**

```bash
git add agent_carbon/resolve/__init__.py agent_carbon/resolve/cli.py tests/test_resolve.py
git commit -m "feat: resolve set_mappings/forget (mapping nom→repo HF + provenance)"
```

---

## Task 4 : Sous-commande CLI `agent-carbon resolve` (orchestration + sortie)

Câbler le sous-parseur `resolve` et l'orchestrateur `cmd_resolve` (list / set / recompute / forget + sortie texte/JSON), avec recompute automatique quand la config change.

**Files :**

- Modify : `agent_carbon/resolve/cli.py` (ajout de `cmd_resolve` + helpers d'impression)
- Modify : `agent_carbon/__main__.py` (sous-parseur + dispatch)
- Test : `tests/test_resolve_cli.py`

**Interfaces :**

- Consumes : `set_mappings`, `forget` (Task 3), `store.uncovered_by_model` (Task 0), `store.recompute_errors` (Task 2), `Config.load/save`, `EcoLogitsEngine`, `ModelResolver`.
- Produces : `cmd_resolve(args) -> int`. `args` porte : `db, since, list (bool), json (bool), set (list[str]), forget (list[str]), recompute (bool)`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_resolve_cli.py` :

```python
import io
import json
import sys
import types
from contextlib import redirect_stdout
from agent_carbon import __main__ as cli
from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.models import InferenceEvent
from agent_carbon.store.db import SQLiteStore


def _engine():
    return EcoLogitsEngine(ModelResolver({}))


def _fake_hf(total, monkeypatch):
    mod = types.ModuleType("huggingface_hub")
    info = types.SimpleNamespace(safetensors=types.SimpleNamespace(total=total))
    mod.model_info = lambda repo_id, **kw: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def _patch_config(monkeypatch, path):
    original_load = Config.load.__func__
    original_save = Config.save
    def load(cls, p=None):
        return original_load(cls, p or path)
    def save(self, p=None):
        return original_save(self, p or path)
    monkeypatch.setattr(Config, "load", classmethod(load))
    monkeypatch.setattr(Config, "save", save)


def _ingest_error_event(db):
    s = SQLiteStore(db)
    s.ingest([InferenceEvent("ollama", "x:y", 100, 200, 0, 0,
              "2026-06-27T10:00:00.000Z", "p", "s", "u1")],
             _engine(), Config(electricity_mix_zone="FRA"))
    return s


def test_resolve_list_json(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    _patch_config(monkeypatch, str(tmp_path / "config.json"))
    _ingest_error_event(db)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["resolve", "--db", db, "--list", "--json"])
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data[0]["model"] == "x:y"
    assert data[0]["tokens"] == 200


def test_resolve_set_recompute_covers_model(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    Config(electricity_mix_zone="FRA").save(config_path)
    _patch_config(monkeypatch, config_path)
    _ingest_error_event(db)                      # HF réel : x:y invalide → erreur
    assert SQLiteStore(db).coverage()["uncovered"] == 1
    _fake_hf(7_000_000_000, monkeypatch)         # mock pour le --set
    with redirect_stdout(io.StringIO()):
        rc = cli.main(["resolve", "--db", db, "--set", "ollama/x:y=Org/Repo"])
    assert rc == 0
    assert SQLiteStore(db).coverage()["uncovered"] == 0
    reloaded = Config.load(config_path)
    assert reloaded.model_params["ollama/x:y"]["source"] == "resolve"
    assert reloaded.model_params["ollama/x:y"]["hf_repo"] == "Org/Repo"


def test_resolve_forget_reverts(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    config_path = str(tmp_path / "config.json")
    Config(electricity_mix_zone="FRA").save(config_path)
    _patch_config(monkeypatch, config_path)
    _ingest_error_event(db)
    _fake_hf(7_000_000_000, monkeypatch)
    with redirect_stdout(io.StringIO()):
        cli.main(["resolve", "--db", db, "--set", "ollama/x:y=Org/Repo"])
    assert SQLiteStore(db).coverage()["uncovered"] == 0
    # HF indisponible → le recompute du forget ne peut pas re-résoudre x:y
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with redirect_stdout(io.StringIO()):
        rc = cli.main(["resolve", "--db", db, "--forget", "ollama/x:y"])
    assert rc == 0
    assert SQLiteStore(db).coverage()["uncovered"] == 1
    assert "ollama/x:y" not in Config.load(config_path).model_params
```

- [ ] **Step 2 : Lancer les tests pour les voir échouer**

Run : `.venv/bin/python -m pytest tests/test_resolve_cli.py -q`
Expected : FAIL (argument `resolve` invalide / `cmd_resolve` absent)

- [ ] **Step 3 : Implémenter `cmd_resolve` + helpers d'impression**

Ajouter dans `agent_carbon/resolve/cli.py` :

```python
import json

from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.store.db import SQLiteStore


def _print_set(results: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(results, ensure_ascii=False))
        return
    for r in results:
        if r["ok"]:
            print(f"✓ {r['key']} → {r['repo']} ({r['params']:.1f} Md)")
        else:
            print(f"✗ {r['key']} → {r['repo'] or '?'} : {r['error']}")


def _print_forget(results: list[dict]) -> None:
    for r in results:
        print(f"{'retiré' if r['removed'] else 'absent'} : {r['key']}")


def _print_recompute(delta: dict) -> None:
    print(f"Recompute : {delta['before']} → {delta['after']} non couverts")


def _print_list(rows: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        print("Aucun modèle non couvert.")
        return
    for r in rows:
        print(f"· {r['model']} ({r['tokens']} tokens générés, {r['events']} events)")


def cmd_resolve(args) -> int:
    store = SQLiteStore(args.db)
    config = Config.load()
    changed = False

    if args.set:
        results = set_mappings(config, args.set)
        changed = any(r["ok"] for r in results) or changed
        _print_set(results, args.json)
    if args.forget:
        results = forget(config, args.forget)
        changed = any(r["removed"] for r in results) or changed
        _print_forget(results)
    if changed:
        config.save()
    if args.recompute or changed:
        engine = EcoLogitsEngine(ModelResolver(config.model_aliases))
        _print_recompute(store.recompute_errors(engine, config))
    if args.list:
        _print_list(store.uncovered_by_model(args.since), args.json)
    return 0
```

Dans `agent_carbon/__main__.py`, ajouter l'import en tête :

```python
from agent_carbon.resolve.cli import cmd_resolve
```

Ajouter le sous-parseur (après le bloc `p_mod`) :

```python
    p_res = sub.add_parser("resolve",
                           help="résoudre les modèles non couverts (params HF) et recalculer")
    p_res.add_argument("--db", default=_DEFAULT_DB)
    p_res.add_argument("--since", default=None)
    p_res.add_argument("--list", action="store_true")
    p_res.add_argument("--json", action="store_true")
    p_res.add_argument("--set", action="append", default=[], metavar="P/M=REPO")
    p_res.add_argument("--forget", action="append", default=[], metavar="P/M")
    p_res.add_argument("--recompute", action="store_true")
```

Ajouter le dispatch (avant `return 1`) :

```python
    if args.cmd == "resolve":
        return cmd_resolve(args)
```

- [ ] **Step 4 : Lancer les tests pour les voir passer**

Run : `.venv/bin/python -m pytest tests/test_resolve_cli.py -q`
Expected : PASS

- [ ] **Step 5 : Lancer toute la suite**

Run : `.venv/bin/python -m pytest -q`
Expected : PASS (aucune régression)

- [ ] **Step 6 : Committer**

```bash
git add agent_carbon/resolve/cli.py agent_carbon/__main__.py tests/test_resolve_cli.py
git commit -m "feat: sous-commande agent-carbon resolve (list/set/recompute/forget)"
```

---

## Task 5 : Skill `/agent-carbon-resolve` + CTA du rapport + doc

Créer le skill orchestrateur et faire pointer la CTA du rapport vers lui. Mettre à jour CHANGELOG/README.

**Files :**

- Create : `skills/agent-carbon-resolve/SKILL.md`
- Modify : `agent_carbon/report/cli.py` (CTA de `render_uncovered`)
- Modify : `CHANGELOG.md`, `README.md`
- Test : `tests/test_report.py`

**Interfaces :**

- Consumes : la sous-commande `agent-carbon resolve` (Task 4).

- [ ] **Step 1 : Écrire le test qui échoue (CTA pointe vers le skill)**

Modifier dans `tests/test_report.py` le test `test_render_uncovered_lists_tokens_and_suggests_resolve` en remplaçant l'assertion :

```python
    assert "/agent-carbon-resolve" in out      # invite à lancer le skill
```

- [ ] **Step 2 : Lancer le test pour le voir échouer**

Run : `.venv/bin/python -m pytest tests/test_report.py::test_render_uncovered_lists_tokens_and_suggests_resolve -q`
Expected : FAIL (la sortie contient `agent-carbon-resolve` sans `/`)

- [ ] **Step 3 : Mettre à jour la CTA dans `render_uncovered`**

Dans `agent_carbon/report/cli.py`, remplacer la dernière ligne de `render_uncovered` :

```python
    out.append("  → lance le skill `/agent-carbon-resolve` pour tenter de les résoudre via Hugging Face.")
```

- [ ] **Step 4 : Lancer le test pour le voir passer**

Run : `.venv/bin/python -m pytest tests/test_report.py -q`
Expected : PASS

- [ ] **Step 5 : Créer le skill**

Créer `skills/agent-carbon-resolve/SKILL.md` :

````markdown
---
name: agent-carbon-resolve
description: Résout les modèles « non couverts » d'agent-carbon (impact non estimé) en mappant leur nom vers un repo Hugging Face, récupère les paramètres et recalcule les impacts. À utiliser quand le rapport agent-carbon liste des modèles non couverts, ou via /agent-carbon-resolve.
---

Résout les modèles à impact non estimé : tu fournis le mapping nom→repo Hugging Face (ta connaissance du monde), la CLI vérifie les paramètres sur HF et recalcule les impacts en base. Applique automatiquement puis présente un récap corrigeable.

## Localiser le binaire

```bash
AC="$(command -v agent-carbon || echo "$HOME/.agent-carbon/src/.venv/bin/agent-carbon")"
[ -x "$AC" ] || { echo "agent-carbon non installé."; exit 1; }
```
````

## Étapes

1. **Lister les non couverts** : `"$AC" resolve --list --json`. Si la liste est vide, informer qu'il n'y a rien à résoudre et s'arrêter.

2. **Proposer un repo HF canonique pour chaque modèle**, à partir de l'identifiant brut. Retirer les suffixes de routeur (`:free`), les suffixes de date (`-YYYYMMDD`), corriger les noms d'organisation (ex. `z-ai` → `zai-org`, `openai/gpt-oss-120b:free` → `openai/gpt-oss-120b`). **Laisser de côté** les modèles propriétaires ou introuvables sur HF (ex. `poolside/…`) : ne pas inventer de repo.

3. **Appliquer le mapping et recalculer** en une invocation (un seul recompute) :

```bash
"$AC" resolve \
  --set "anthropic/z-ai/glm-4.5-air:free=zai-org/GLM-4.5-Air" \
  --set "anthropic/openai/gpt-oss-120b:free=openai/gpt-oss-120b" \
  --list --json
```

`--set` récupère les params sur HF (échec géré par item) ; le recompute est automatique quand la config change ; `--list --json` final montre ce qui reste non couvert.

4. **Présenter un récap** : pour chaque modèle — repo retenu, params (Md), succès/échec. Lister les modèles laissés de côté (propriétaires/introuvables) et ceux dont le `--set` a échoué. Indiquer le delta de couverture (sortie « Recompute : X → Y »).

5. **Rappeler le revert** : un mapping douteux se retire avec
   `"$AC" resolve --forget "<provider>/<model>"` (retire l'entrée et recalcule).

## Garde-fous

- Les **paramètres viennent toujours de HF** (vérifiables) ; tu ne fournis que le nom du repo, jamais une taille inventée.
- Un modèle sans repo HF réel reste non couvert — c'est honnête, ne pas forcer.
- Les placeholders `<synthetic>` n'apparaissent jamais ici (déjà exclus des non couverts).

````

- [ ] **Step 6 : Déployer le skill en local (dev) et mettre à jour la doc**

```bash
ln -sfn "$(pwd)/skills/agent-carbon-resolve" "$HOME/.claude/skills/agent-carbon-resolve"
````

Dans `CHANGELOG.md`, sous `### Ajouté`, ajouter :

```markdown
- **`agent-carbon resolve` + skill `/agent-carbon-resolve`** : résolution des modèles non couverts. La CLI mappe un nom de modèle vers un repo Hugging Face (`--set "provider/model=repo"`), en récupère les paramètres (safetensors), recalcule les impacts en base (`--recompute`, automatique après un set) et sait annuler un mapping (`--forget`). Le skill orchestre : le LLM propose le repo HF, la CLI vérifie et recalcule, puis affiche un récap corrigeable. Provenance (`source: "resolve"`, `hf_repo`) persistée dans `config.model_params`.
```

Dans `README.md`, après la ligne de la commande `report`, ajouter le bloc d'usage :

```markdown
# Résoudre les modèles non couverts (mapping nom→repo HF + recompute)

agent-carbon resolve --list [--json]
agent-carbon resolve --set "provider/model=org/repo" # params HF + recompute auto
agent-carbon resolve --forget "provider/model" # annule un mapping
```

- [ ] **Step 7 : Lancer toute la suite**

Run : `.venv/bin/python -m pytest -q`
Expected : PASS

- [ ] **Step 8 : Committer**

```bash
git add skills/agent-carbon-resolve/SKILL.md agent_carbon/report/cli.py CHANGELOG.md README.md tests/test_report.py
git commit -m "feat: skill /agent-carbon-resolve + CTA rapport vers le skill"
```

---

## Task 6 : Validation terrain + nettoyage TODO

Vérifier le flux complet sur la vraie base, puis acter dans le TODO.

**Files :**

- Modify : `docs/TODO-self-hosted-models.md`

- [ ] **Step 1 : Lister les non couverts réels**

Run : `.venv/bin/python -m agent_carbon resolve --list`
Expected : les 4 modèles `:free` (nemotron, gpt-oss, laguna, glm) listés avec leurs tokens ; `<synthetic>` absent.

- [ ] **Step 2 : Résoudre les modèles mappables (réseau requis)**

Run :

```bash
.venv/bin/python -m agent_carbon resolve \
  --set "anthropic/openai/gpt-oss-120b:free=openai/gpt-oss-120b" \
  --set "anthropic/z-ai/glm-4.5-air:free=zai-org/GLM-4.5-Air" \
  --list
```

Expected : `✓` pour gpt-oss et glm avec leurs params (Md) ; ligne « Recompute : N → M non couverts » avec M < N ; nemotron/laguna restent listés (pas de repo public évident).

- [ ] **Step 3 : Acter dans le TODO**

Dans `docs/TODO-self-hosted-models.md`, remplacer la mention « modèles externes `:free` écartés » par une note renvoyant à `agent-carbon resolve` / `/agent-carbon-resolve` comme voie de résolution, et noter que le recompute est désormais une commande (`resolve --recompute`), plus un script jetable.

- [ ] **Step 4 : Committer**

```bash
git add docs/TODO-self-hosted-models.md
git commit -m "docs: TODO — resolve remplace le script jetable de recompute"
```

---

## Finalisation (hors tâches numérotées)

Après validation des tâches, terminer la branche via la skill `superpowers:finishing-a-development-branch` (merge `--no-ff` dans `main`, push, suppression de la branche), conformément à la convention du repo.
