# TODO — modèles auto-hébergés (suites)

> État au 2026-06-29. La feature « évaluation des modèles auto-hébergés » est
> **livrée, mergée et poussée** sur `origin/main` (merges `0efbcac` puis `0ca908c`).
> Spec : `docs/superpowers/specs/2026-06-29-self-hosted-models-design.md`.
> Plan : `docs/superpowers/plans/2026-06-29-self-hosted-models.md`.

## Ce qui est déjà fait

- Chaîne de résolution des params : registre EcoLogits → cache config → Hugging Face → file d'attente (`agent_carbon/impact/params.py`).
- Config persistée `~/.agent-carbon/config.json` : mix détecté à la 1re utilisation, PUE (plage 1.1–1.5) / WUE (0).
- Moteur : fallback `compute_llm_impacts()` pour modèles inconnus, plage PUE → min/max (`agent_carbon/impact/engine.py`, helper `_extract_impacts`).
- File `pending_models` en DB + sous-commande `agent-carbon models` (interactive, hors batch).
- Skill `agent-carbon-config`.
- **Bug d'unité corrigé** : EcoLogits attend les params **en milliards** ; le tier HF convertit désormais `safetensors.total ÷ 1e9`, la saisie `models` demande des milliards. (Le tier registre était déjà correct.)
- 64 tests verts.

## Validation terrain (vraies données, `~/.agent-carbon/carbon.db`)

Modèles auto-hébergés réels présents (taggés `provider=anthropic`, endpoint MLX local) :
`qwen/qwen3.6-35b-a3b` (6834 events), `Qwen3.6-35B-A3B-4bit` (1377), `gpt-oss-20b-MXFP4-Q8`, `Qwen3-Coder-30B-A3B-Instruct-4bit`, `Qwen3.5-27B-...-Distilled`, etc.

Intensité mesurée (mix FRA, MoE 35B-A3B = actif ~3 / total ~35 Md) :

- Qwen3-35B-A3B local ≈ **12,5 gCO₂eq / M tokens**
- Opus cloud ≈ **287 gCO₂eq / M tokens** (~23× plus élevé)

Script de validation jetable (hors repo, à recréer si besoin) : il lit la base en
lecture seule, déclare les params en milliards dans un `Config` en mémoire, et
recalcule via `EcoLogitsEngine`. Logique : pour chaque event → `engine.compute()`,
on somme `rec.totals[crit]` (min/max). Référence cloud = `claude-opus-4-8` (tier 1).

## Suite 1 — Recalculer les impacts en base — ✅ FAIT (2026-06-29)

**Problème** : les events Qwen déjà en base avaient un impact « non couvert »
(`error` non nul) calculé par l'**ancien** moteur. L'ingestion étant idempotente
par `msg_id`, relancer `agent-carbon ingest` ne les recalculait pas.

**Décision (historique)** : le premier recompute s'est fait via un **script jetable**
(scratchpad, `recompute.py`). Depuis le chantier `agent-carbon-resolve`, le recompute
est une **commande de premier ordre** : `agent-carbon resolve --recompute` (et
`store.recompute_errors()` en interne) — plus besoin de script jetable.

**Résultat terrain** : non couverts **8360 → 82** (8278 résolus ; les 82 restants =
`<synthetic>` à 0 token + modèles externes `:free`). Intensité
Qwen3.6-35B-A3B confirmée ≈ **12,4 gCO₂eq/M tokens**. Params persistés dans
`config.json` (milliards + `arch=moe`) → futurs `ingest` résolus aussi.

**Suite (2026-06-29) — `agent-carbon-resolve`** : les modèles externes `:free` ne
sont plus « écartés ». La commande `agent-carbon resolve` (et le skill
`/agent-carbon-resolve`) mappe leur nom brut vers un repo Hugging Face, récupère les
params (safetensors) et recalcule. Validation terrain : `openai/gpt-oss-120b:free`
→ `openai/gpt-oss-120b` (120,4 Md) et `z-ai/glm-4.5-air:free` → `zai-org/GLM-4.5-Air`
(110,5 Md) résolus ; **non couverts 82 → 76** (6 events). Restent `<synthetic>` (70,
exclus du rapport) + `nvidia/nemotron-…:free` et `poolside/laguna-…:free`
(pas de repo HF public évident — laissés non couverts honnêtement).

## Suite 2 — Gérer le couple actif/total MoE dans `agent-carbon models`

**Limite actuelle** : `_cmd_models` (`agent_carbon/__main__.py`) ne demande qu'**un**
chiffre et stocke `{"active": total, "total": total, "arch": "dense"}`. Pour un MoE
(ex. Qwen3 35B-A3B : actif ≈ 3, total ≈ 35 Md), ça surestime l'énergie (active=total).
Aujourd'hui le vrai couple n'est atteignable qu'en éditant `model_params` à la main.

**À faire** : faire demander à `models` l'archi (dense/MoE) et, si MoE, le couple
`(actif, total)` en milliards, et stocker `arch="moe"`. Le moteur sait déjà gérer
active≠total (`compute_llm_impacts` + `ParamsResult`). Penser au tier HF : il
suppose dense (`moe-assumed-dense`) — une déclaration MoE manuelle doit pouvoir
écraser/préciser l'entrée de cache.

## Rappels d'unité (piège)

- Params EcoLogits = **milliards** partout (`ParamsResult.active/total`, `model_params`).
- `safetensors.total` (HF) = compte **brut** → `÷ 1e9`.
- Saisie `models` = milliards (ex. `7` pour 7B).
