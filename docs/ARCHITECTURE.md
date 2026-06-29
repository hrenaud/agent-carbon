# Architecture technique

## Pipeline général

```
JSONL Claude Code (~/.claude/projects/**/*.jsonl)
    ↓
ClaudeCodeCollector (parse, normalise, temps actif, client)
    ↓
InferenceEvent[]  (provider, model, tokens, timestamp, session, projet, active_seconds, client)
    ↓
EcoLogitsEngine (offline, EcoLogits 0.11.0)
    ├─ modèle reconnu par EcoLogits → llm_impacts()
    └─ sinon → fallback auto-hébergé : ModelParamsResolver + compute_llm_impacts()
    ↓
ImpactRecord (5 critères min/max, phases usage/embodied, warnings, error)
    ↓
SQLiteStore (idempotent ; events / impacts / sessions / pending_models)
    ↓
CLI : report · statusline · resolve · models   (lisent la DB, jamais les JSONL)
```

## Collecte (ClaudeCodeCollector)

**Source** : `~/.claude/projects/**/*.jsonl` (défaut ; `--source`). Peut aussi cibler un seul transcript (statusline en session).

**Traitement** : pour chaque ligne JSON, ignore les non-`assistant` et les messages sans `message.usage`, puis extrait `model`, les 4 compteurs de tokens, `timestamp`, `cwd` (→ projet = dernier segment), `sessionId`, `uuid`. Normalise en `InferenceEvent`.

- **`active_seconds`** : temps actif estimé par delta de timestamps entre messages consécutifs d'une session, plafonné (anti-pause) — sert à l'intensité (impact/h).
- **`client`** : outil à l'origine de l'event (`claude-code`, `opencode`…) — dimension de ventilation.

**Confidentialité** : aucun contenu de prompt/réponse n'est extrait — uniquement métadonnées et usage.

**Provider** : `"anthropic"` par défaut (le champ existe pour de futurs collecteurs).

## Impact (EcoLogitsEngine)

**Principes** : offline ; piloté par les **tokens de sortie** uniquement ; latence estimée `output_tokens / throughput_tok_s` (défaut 50, min 0.5 s) ; chaque critère retourne `(min, max)`.

**Deux chemins** (`engine.compute`) :

1. **Modèle reconnu EcoLogits** → `ecologits.tracers.utils.llm_impacts()`.
2. **Modèle inconnu** (erreur `model-not-registered`) → `_compute_selfhosted` : résout les paramètres puis appelle `compute_llm_impacts()` directement avec le mix électrique de la zone configurée. La plage **PUE** (min/max) propage une fourchette min/max sur les résultats.

**5 critères** (`CRITERIA`) : `energy` (kWh), `gwp` (kg CO₂eq), `adpe` (kg Sbeq), `pe` (MJ), `wcf` (L). **Phases** : `usage` (inférence) et `embodied` (fabrication : gwp/adpe/pe).

**ModelResolver** (`impact/resolver.py`) : applique les alias `Config.model_aliases` au nom de modèle ; signale `alias:ancien->nouveau` dans les warnings.

**ModelParamsResolver** (`impact/params.py`) — cascade pour les modèles auto-hébergés/tiers :

1. **Registre EcoLogits** (`models.find_model`) — gère dense et MoE (`active`/`total`), et `RangeValue` (moyenne).
2. **Cache config** (`config.model_params["provider/model"]`) — params déclarés ou résolus précédemment (clés `active`, `total`, `arch`, `source`, et `hf_repo` si résolu via resolve).
3. **Hugging Face** (`fetch_hf_params(repo)`) — métadonnées safetensors, `total ÷ 1e9` (milliards), **offline-safe** (lib absente/réseau/404/identifiant invalide → `None`), suppose dense (`moe-assumed-dense`), met en cache.
4. **Échec** → `error="model-params-unresolved"`, modèle ajouté à `pending_models`.

> **Unité (piège)** : les params EcoLogits sont **en milliards** partout (registre, cache, HF `÷ 1e9`, saisie `models`).

**Méthodologie** : `methodology_version = f"engine={ENGINE_VERSION};ecologits={ecologits.__version__}"`, stockée par record (reproductibilité / recalculs).

## Stockage (SQLiteStore)

**Base** : `~/.agent-carbon/carbon.db` (`--db`). Connexion `row_factory = Row`. Migrations additives par `ALTER TABLE` (colonnes ajoutées après coup).

### `events` (brutes, normalisées)

```sql
CREATE TABLE events (
  session_id TEXT, msg_id TEXT,
  provider TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  cache_creation_tokens INTEGER, cache_read_tokens INTEGER,
  timestamp TEXT,            -- ISO 8601
  project TEXT,              -- dérivé du cwd
  active_seconds REAL DEFAULT 0,   -- temps actif estimé
  client TEXT DEFAULT '',          -- outil source
  PRIMARY KEY (session_id, msg_id)
);
```

### `impacts` (résultats du calcul)

```sql
CREATE TABLE impacts (
  session_id TEXT, msg_id TEXT,
  model_resolved TEXT, zone TEXT, methodology_version TEXT,
  energy_min REAL, energy_max REAL, gwp_min REAL, gwp_max REAL,
  adpe_min REAL, adpe_max REAL, pe_min REAL, pe_max REAL,
  wcf_min REAL, wcf_max REAL,
  breakdown_json TEXT,       -- {"usage": {...}, "embodied": {...}}
  warnings TEXT, error TEXT, -- error non NULL = non couvert
  PRIMARY KEY (session_id, msg_id)
);
```

### `sessions` (plage temporelle) · `pending_models` (file d'attente)

```sql
CREATE TABLE sessions (session_id TEXT PRIMARY KEY, project TEXT, started_at TEXT, ended_at TEXT);
CREATE TABLE pending_models (provider TEXT, model TEXT, first_seen TEXT, occurrences INTEGER DEFAULT 0,
                             PRIMARY KEY (provider, model));
```

**Idempotence** : `INSERT OR IGNORE` sur `(session_id, msg_id)`. À la ré-ingestion d'un event connu, l'impact n'est **pas** recalculé, mais `active_seconds`/`client` sont rétro-remplis s'ils manquaient.

**Méthodes de lecture/agrégation** (toutes filtrables par `since`, comparaison lexicographique sur `timestamp`) :

- `rows_for_report(since, session_id)` — lignes brutes (impact non NULL) pour le total/projets ; expose `client`.
- `tokens_by_model(since)` — par modèle : tokens totaux (entrée+sortie+cache) + centrale et **bornes min/max** par critère.
- `intensity_by_model(since)` — par modèle, sur les events à temps actif > 0 : heures, tokens de sortie, centrale + **bornes min/max** (→ tok/h et impact/h).
- `uncovered_by_model(since)` — modèles à `error` non NULL, **hors `<synthetic>`** : tokens générés + nombre d'events.
- `coverage()` — `{total, measured, uncovered}`.

**Recalcul** :

- `recompute_errors(engine, config)` — recalcule les impacts des events en `error` (utile après résolution de params) ; retourne `{before, after}` de couverture.
- `mark_model_events_error(provider, model, error)` — repasse en erreur les events d'un modèle (appariement `(session_id, msg_id)`), pour qu'un recompute les reprenne (revert d'un mapping).

## Restitution

### Report (`agent-carbon report`)

Cinq sections (lisent la DB) :

1. **Impact total** — 5 critères, valeur centrale `~` + plage min–max.
2. **Projets les plus impactants** — triés par GWP (top 5 + « autres » ; `--all-projects` pour tout).
3. **Tokens & impact par modèle** — tokens totaux + impact des 5 critères.
4. **Modèles non couverts** — tokens générés des modèles à impact non estimé (hors `<synthetic>`) + invite `/agent-carbon-resolve`.
5. **Intensité par modèle** — tok/h et émissions/h, par heure de travail effectif.

Options : `--since <date>` (date simple `2026-06-27`, `27/06/2026`, `27/06/26`, ou ISO 8601 complet — normalisée par `agent_carbon/dates.py`), `--detail`/`--detailed` (fourchettes min–max au lieu de la centrale, dans les tableaux par modèle/projet), `--all-projects`, `--db`. Chaque rapport se termine par un rappel `--help` + skill `/agent-carbon-help`.

### Resolve (`agent-carbon resolve`)

Résout les modèles non couverts : `--list [--json]`, `--set "provider/model=hf_repo"` (params via HF + provenance), `--recompute` (auto après un set), `--forget` (revert). Le mapping nom→repo relève du skill `/agent-carbon-resolve` (le LLM propose le repo, la CLI vérifie via HF) ; les params viennent toujours de HF, jamais d'une estimation inventée.

### Statusline (`agent-carbon statusline`)

Ligne compacte. Claude Code fournit la session courante (`session_id`, `transcript_path`) sur stdin → ingestion à la volée du transcript courant (idempotente) puis filtrage sur cette session. En lancement manuel (sans stdin), retombe sur le total global.

### Models (`agent-carbon models`)

Liste / renseigne (interactif) les modèles auto-hébergés en attente (`pending_models`).

## Configuration

Fichier **`~/.agent-carbon/config.json`** (`agent_carbon/config.py`, dataclass `Config`) :

| Champ                  | Défaut                                | Rôle                                                                      |
| ---------------------- | ------------------------------------- | ------------------------------------------------------------------------- |
| `electricity_mix_zone` | `None` (détecté à la 1re utilisation) | zone du mix électrique                                                    |
| `throughput_tok_s`     | 50                                    | tokens/s pour estimer la latence                                          |
| `model_aliases`        | `{}`                                  | alias de noms de modèles                                                  |
| `datacenter_pue`       | `RangeValue(1.1, 1.5)`                | PUE (plage → fourchette min/max)                                          |
| `datacenter_wue`       | 0.0                                   | WUE                                                                       |
| `model_params`         | `{}`                                  | params auto-hébergés/résolus (`active`/`total`/`arch`/`source`/`hf_repo`) |
| `local_wh_per_token`   | `None`                                | (réservé) énergie locale par token                                        |

## Skills Claude Code

`skills/` (déployés par symlink dans `~/.claude/skills/`) : `/agent-carbon-report`, `/agent-carbon-resolve`, `/agent-carbon-config`, `/agent-carbon-help`.

## Incertitude & méthodologie

- **Fourchettes** min–max partout (région datacenter inconnue, mix électrique, plage PUE) — jamais réduites à un point ; la centrale `~` est marquée comme approximative.
- **Warnings** par record (`alias:…`, `moe-assumed-dense`, warnings EcoLogits) — silencés en sortie d'ingestion pour ne pas faire craindre un plantage, mais conservés.
- **Errors** : `impacts.error` non NULL = non couvert ; l'event est conservé, exclu des totaux (`WHERE error IS NULL`).
- **`methodology_version`** par record → recalculs / comparaisons inter-versions.

## Hors périmètre actuel (coutures)

- Collecteurs tiers (Codex, inférence locale) : stubs.
- `compute_live()` (instrumentation SDK temps réel) : non implémenté.
- `import_legacy()` (backfill `carbon.db` ancien) : non implémenté.
- Énergie du poste de travail, export CSV/JSON : hors périmètre.
- Couple MoE à la résolution (`resolve --set` suppose dense) et étape WebSearch dans la cascade : cf. `docs/TODO-self-hosted-models.md` (Suites 3 & 4).

## Références

- EcoLogits : https://github.com/mlco2/ecologits
- CodeCarbon : https://github.com/mlco2/codecarbon
- claude-carbon : audit original et UX reporting
