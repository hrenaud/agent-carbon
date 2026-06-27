# agent-carbon — Design MVP

> Spec issu du brainstorming du 2026-06-27, à partir de `KICKOFF.md`.
> But : compteur d'impact **vendor-neutral** et **multi-critères** pour les outils d'IA agentique, qui **délègue le calcul d'impact à EcoLogits** au lieu de réécrire un modèle.

## Principe directeur

Le cœur est **vendor-neutral**. Tout ce qui est spécifique à un outil (Claude Code) ou à une cible de sortie (statusline) vit dans des **adaptateurs** branchés sur des interfaces stables. On n'écrit **aucun modèle d'impact** : EcoLogits s'en charge.

La philosophie d'incertitude est explicite : l'incertitude principale (facteur ~8, piloté par la région datacenter d'Anthropic non publiée) est **irréductible**. Un bon outil ne la masque pas, il l'**affiche en fourchette** (min/max). On ne produit jamais un chiffre unique de fausse précision.

### Principes transverses (inspirés de l'état de l'art)

Après revue de **CodeCarbon** (offline tracker + `country_iso_code`, mono-critère CO₂, orienté live) et **thirsty-llm** (offline-first, fourchettes, logging minimal — mais modèle d'impact _dérivé du prix_, exactement ce que l'on rejette en passant par EcoLogits), trois principes sont retenus :

1. **Confidentialité par conception** : on ne stocke **que** `{model, tokens, timestamp, project, identifiants}` — **jamais** de contenu de prompt ou de réponse.
2. **Méthodologie versionnée par record** : chaque impact stocke la version d'EcoLogits, la version de notre engine et la zone élec utilisée. C'est la réponse directe au **trou #6** de claude-carbon (lignes legacy figées) : on peut recalculer et comparer sans figer du biais.
3. **Source de vérité unique pour nos constantes** : un fichier de config porte _nos_ paramètres (zone défaut `USA`, facteur Wh/token local en placeholder), pas dispersés dans le code. Les constantes d'impact, elles, restent dans EcoLogits.

## Décisions tranchées (brainstorming)

| #   | Décision               | Choix retenu                                                                                                                                                                  |
| --- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Périmètre MVP          | **Claude / Claude Code uniquement**, mais coutures d'extensibilité posées dès le départ (interface `Collector` + stubs) pour ajouter outils/modes **sans refacto**            |
| 2   | Alimentation EcoLogits | **Offline** depuis tokens stockés, via EcoLogits **`mlco2/ecologits@0.11.0`** (tag git épinglé : 5 critères dont eau + modèles actuels — cf. spike) ; mode `live` placeholder |
| 3   | Source des données     | **JSONL** (source de vérité) → ingestion → **notre propre DB SQLite** → reporting ; démarrage propre, backfill `carbon.db` en placeholder                                     |
| 4   | Inférence locale       | **Hors MVP**, module placeholder (`énergie_machine × grille FRA`, facteur Wh/token à fixer plus tard)                                                                         |
| 5   | Sortie                 | **Rapport CLI + statusline**, branchés sur la DB                                                                                                                              |
| 6   | Langage / runtime      | **Tout Python ≥ 3.10** (exigé par EcoLogits `main` ; EcoLogits est Python, on parse du JSONL)                                                                                 |

Paramètres validés : zone électrique par défaut **`USA`** (configurable, fourchette toujours affichée) ; granularité du rapport = **par modèle + par projet + total**, filtre `--since`.

## Pipeline

```
JSONL Claude Code (~/.claude/projects/**/*.jsonl)
   ↓  ClaudeCodeCollector (parse)
InferenceEvent[]   {provider, model, input/output/cache_creation/cache_read tokens, ts, project, session_id, msg_id}
   ↓  EcoLogitsEngine (offline, par zone élec)
ImpactRecord[]     {gwp, adpe, pe, energy, wcf} × {usage, embodied} × RangeValue(min/max) + warnings
   ↓  SQLiteStore (ingestion idempotente)
notre DB SQLite
   ↓
report CLI  +  statusline
```

## Composants & coutures d'extensibilité

| Module        | MVP (réel)                                                                                       | Placeholder (extension sans refacto)                                                            |
| ------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| `collectors/` | `Collector` (ABC) + `ClaudeCodeCollector` (parse JSONL)                                          | `CodexCollector`, `PICollector`, `LocalInferenceCollector` → stubs levant `NotImplementedError` |
| `impact/`     | `EcoLogitsEngine.compute(event, zone)` — mode **offline** (5 critères) + `ModelResolver` (filet) | `compute_live()` posée en stub                                                                  |
| `store/`      | `SQLiteStore` : tables `events` + `impacts`, ingestion idempotente                               | `import_legacy(carbon_db_path)` stub (backfill `carbon.db`)                                     |
| `report/`     | commande `report` : tableau multi-critères + fourchettes, par modèle/projet/total, `--since`     | export `--format md/json` en extension                                                          |
| `statusline/` | commande compacte lisant l'agrégat en DB                                                         | —                                                                                               |
| `config`      | `electricity_mix_zone` configurable (défaut `USA`)                                               | —                                                                                               |

### Interface `Collector` (contrat)

- **Rôle** : transformer une source spécifique à un outil en `InferenceEvent[]` normalisés.
- **Entrée** : chemin(s) de source (pour Claude Code : répertoire des JSONL).
- **Sortie** : itérable d'`InferenceEvent`.
- **Dépendances** : aucune sur l'impact ou le store (couplage faible).

### Modèle `InferenceEvent` (normalisé, neutre)

```
InferenceEvent
  provider            # "anthropic"
  model               # nom modèle exact issu du JSONL
  input_tokens
  output_tokens
  cache_creation_tokens
  cache_read_tokens
  timestamp           # ISO, UTC
  project             # dossier projet (dérivé du chemin JSONL)
  session_id
  msg_id              # identifiant message → clé d'idempotence
```

> **Note tokens** : EcoLogits ne modélise l'impact qu'à partir des **tokens de sortie** (cf. `EcoLogitsEngine`). On collecte tout de même input/cache pour la complétude de `events`, l'audit et les usages futurs — mais ils n'entrent **pas** dans le calcul d'impact.

### Choix de version EcoLogits (vérifié par le spike)

Dépôt canonique : **`mlco2/ecologits`** (`genai-impact/ecologits` redirige 301 vers lui), site `ecologits.ai`. Trois surfaces existent et **diffèrent** :

- **PyPI `ecologits` 0.8.2** (dernière publiée sur PyPI) : offline, mais **4 critères seulement (pas d'eau)** et registre figé à `claude-opus-4-1` / `claude-sonnet-4-20250514` → les modèles actuels de Claude Code renvoient `model-not-registered`.
- **Tags GitHub jusqu'à `0.11.0`** (0.9.x → 0.11.0, taggés mais **non publiés sur PyPI**) : offline, **5 critères dont l'eau (`wcf`)**, registre **à jour** (opus-4-8/4-7/4-6/4-5, sonnet-4-6/4-5, haiku-4-5 — vérifié par appel réel offline sur `claude-opus-4-8`, `errors: None`). `requires-python = ">=3.10,<4"`.
- **API REST hébergée `api.ecologits.ai`** : même résultat à jour **mais impose le réseau** → écartée (contredit l'offline-first et la confidentialité).

**Décision : dépendance épinglée sur le tag stable `git+https://github.com/mlco2/ecologits.git@0.11.0`** → offline + 5 critères + modèles actuels, et reproductible (tag, pas `main` mouvant). Coût : **Python ≥ 3.10** requis. On rebascule sur un pin PyPI normal dès que ≥ 0.9 est publié sur PyPI. Le registre de modèles vit dans `ecologits/data/models.json` — point à surveiller quand un nouveau modèle Claude sort (cf. `ModelResolver`).

### `ModelResolver` (filet de sécurité, plus brique critique)

Le registre `main` couvrant déjà les modèles actuels, ce module devient un **simple garde-fou** : si un futur modèle n'est pas encore au registre, `resolve(model)` applique un **alias explicite** (dans la config, source de vérité) vers le plus proche connu, sinon laisse passer tel quel.

- Tout alias appliqué est **tracé** (warning + champ dédié dans `impacts`) ; modèle ni connu ni aliasé → impact `null` + warning, pas de crash.
- Table vide au départ (rien à aliaser) ; on l'alimente uniquement quand un nouveau modèle sort avant son enregistrement upstream.

### `EcoLogitsEngine`

- **Mécanique vérifiée par le spike** (EcoLogits `0.11.0`, appel réel offline sur `claude-opus-4-8`, sans SDK / clé / réseau) :
  ```python
  from ecologits.tracers.utils import llm_impacts
  out = llm_impacts(provider="anthropic", model_name=<résolu>,
                    output_token_count=N, request_latency=L,
                    electricity_mix_zone="USA")
  ```
- **`request_latency` est obligatoire** et absente en offline → **estimée** : `latency ≈ output_tokens / débit_typique` (~~50 tok/s, paramètre de config). Sensibilité mesurée modérée (~~+6 % de 1 s→10 s), absorbée dans la fourchette.
- **Sortie** : `ImpactRecord` reflétant `ImpactsOutput` — **5 critères** : `energy` (kWh), `gwp` (kgCO₂eq), `adpe` (kgSbeq), `pe` (MJ), **`wcf` (L, eau)**, chacun en `.usage`/`.embodied`, valeurs `RangeValue(min/max)`, plus `warnings`/`errors`.

## Modèle de données (notre schéma SQLite)

- **`events`** : une ligne par message d'inférence normalisé (conservée même après la purge JSONL ~30 j). Clé naturelle = `(session_id, msg_id)`. **Confidentialité** : uniquement `{model, tokens, timestamp, project, ids}` — aucun contenu de prompt/réponse.
- **`impacts`** : résultat EcoLogits par event — 5 critères (energy, gwp, adpe, pe, **wcf**) × 2 phases (usage/embodied) × (min/max) + warnings + zone élec + **`methodology_version`** (version EcoLogits + version de notre engine), horodatés. Permet de recalculer/comparer sans figer de biais (anti-trou #6).
- Séparation `events`/`impacts` volontaire : on peut **recalculer** les impacts (autre zone, nouvelle version EcoLogits) **sans re-parser** les JSONL.
- **`sessions`** : un agrégat par `session_id` avec sa **durée** = `ts(dernier message) − ts(premier message)`. Métadonnée captée dès le MVP (calcul exact, gratuit depuis les timestamps), **sans** conversion énergétique. Utile pour croiser impact/temps et l'intensité d'usage.
- **`config`** : nos constantes (zone défaut `USA`, facteur Wh/token local en placeholder) dans un fichier source-de-vérité unique, pas dispersées dans le code.

## Flux d'ingestion (idempotent)

1. `ClaudeCodeCollector` lit les JSONL → `InferenceEvent[]`.
2. Pour chaque event non déjà présent (`(session_id, msg_id)`), insertion dans `events`.
3. `EcoLogitsEngine.compute` → insertion dans `impacts`.
4. Rejouer les mêmes JSONL ne crée aucun doublon (la purge 30 j n'efface donc pas l'historique déjà ingéré).

## Gestion d'erreurs

- **Modèle inconnu d'EcoLogits** : l'event est stocké, l'impact est `null` + warning loggé. Pas de crash.
- **Warnings EcoLogits** (ex. « architecture du modèle non divulguée » pour Claude) : conservés par record et affichés en note de bas de rapport.
- **Idempotence** : protège contre le double comptage en cas de ré-ingestion.

## Sortie

- **Rapport CLI** : tableau multi-critères (gwp/adpe/pe/énergie/eau) avec fourchettes **min–max**, dimensions **par modèle**, **par projet**, et **total global** ; filtre temporel `--since`. La zone élec et l'incertitude sont rappelées explicitement.
- **Statusline** : ligne compacte (adaptateur de sortie spécifique Claude Code) lisant l'agrégat déjà calculé en DB. Pas de hook live requis dans le MVP.

## Stratégie de test (TDD — tests écrits avant implémentation)

1. **Spike fondateur — ✅ réalisé en brainstorming, à verrouiller en test de non-régression** : `llm_impacts("anthropic", "claude-opus-4-8", output_token_count, request_latency, "USA")` sous EcoLogits `main` (offline) renvoie bien `errors: None` + les **5 critères** (energy/gwp/adpe/pe/wcf) en `RangeValue(min/max)`, usage + embodied. Test gardé pour détecter toute régression du pin EcoLogits.
2. `ClaudeCodeCollector` : fixture JSONL réelle (anonymisée) → `InferenceEvent[]` attendus, y compris dérivation du `project` depuis le chemin.
3. `SQLiteStore` : test d'ingestion idempotente (rejouer = aucun doublon) + recalcul d'impact sans re-parse.
4. `report` : snapshot du tableau CLI sur DB de test (par modèle / par projet / total).

## Hors MVP (assumé, posé en coutures)

Inférence locale (câblage + facteur Wh/token Apple Silicon), **énergie du poste de travail** (durée de session × puissance × grille — placeholder séparé, **jamais agrégé au total d'impact**, étiqueté de ses caveats : la durée wall-clock est surtout du temps mort, et la conso du poste n'est pas marginale à l'usage IA ; ordre de grandeur ~0,3–2 % du cloud), terminal utilisateur, backfill `carbon.db`, mode live, export fichier (md/json), **« équivalents parlants »** dans le rapport (km voiture, etc. — type CodeCarbon, mis de côté pour éviter la fausse précision sur une fourchette) — tous **posés en placeholders**, **aucun implémenté** dans le MVP.

## Maintenance — suivi de version EcoLogits (post-MVP)

Objectif : **détecter** les nouvelles versions d'EcoLogits automatiquement, mais les **adopter délibérément** (jamais de bump silencieux qui changerait tous les chiffres — cf. principe de méthodologie versionnée / trou #6).

Contrainte : EcoLogits **n'est plus publié sur PyPI depuis 0.8.2** ; les versions récentes n'existent qu'en **tags git**. Dependabot (pip) ne les voit donc pas.

Procédé retenu (à implémenter **après** le MVP) : un **GitHub Action planifié** (hebdomadaire) qui

1. interroge l'API des tags de `mlco2/ecologits` ;
2. si un tag est plus récent que notre pin → **ouvre une PR** bumpant le pin ;
3. la CI de la PR exécute le **test de non-régression du spike** (5 critères sur `claude-opus-4-8`) **+ un diff de recalcul** sur un fixture (montre de combien les valeurs bougent) ;
4. **revue humaine + merge** → incrémente `methodology_version`.

Détection automatique, adoption humaine. Pas d'auto-merge, pas de service tiers. (Renovate sait suivre des tags git, mais pour une seule dépendance git le GHA maison est plus simple.)
