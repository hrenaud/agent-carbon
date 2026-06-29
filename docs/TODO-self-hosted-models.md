# TODO — modèles auto-hébergés (suites restantes)

> Backlog des suites **non encore implémentées**. Le socle est livré (chaîne de
> résolution registre → cache → Hugging Face → file ; fallback moteur pour modèles
> inconnus ; recompute via `agent-carbon resolve --recompute` ; résolution des
> modèles tiers via `resolve` / `/agent-carbon-resolve`, dont le **couple MoE** par
> `--set "P/M=repo:<actifs>"`).
> Spec/plan d'origine : `docs/superpowers/specs|plans/2026-06-29-self-hosted-models*`.

## Suite 2 — Gérer le couple actif/total MoE dans `agent-carbon models`

**Livrée**. La sous-commande `models` interroge maintenant l'archi (dense/MoE) :
si MoE, demande l'actif, résout le total via cache → registre → HF. Stocke
`arch="moe"` avec le couple `(actif, total)`.

## Suite 4 — Étape « recherche web » dans la cascade de résolution (à vérifier)

## Suite 4 — Étape « recherche web » dans la cascade de résolution (à vérifier)

**Idée** : la cascade actuelle de `ModelParamsResolver.resolve` est
**1) registre EcoLogits → 2) cache config → 3) Hugging Face → file d'attente**. Or
pour les modèles routés sous un nom non-HF (catalogues NVIDIA NIM `build.nvidia.com`,
ids `:free` exotiques), le repo HF réel n'est pas déductible mécaniquement. Une
**recherche web** le retrouve (fait à la main pour nemotron/laguna : web → repo HF +
archi MoE + couple actif/total).

**Cascade cible (à valider)** : 1) EcoLogits → 2) Hugging Face → 3) **WebSearch**
(trouver le repo HF canonique + l'archi/params depuis la fiche modèle) → 4) **input
utilisateur**. Cette étape 3 relève du skill `/agent-carbon-resolve` (le LLM fait la
recherche et propose le repo + couple MoE), pas du code CLI pur — la CLI reste le
vérificateur déterministe (HF) et le persisteur. À cadrer : où vit l'étape web
(skill vs helper), comment restituer l'archi MoE (réutiliser `--set repo:<actifs>`), garde-fou « ne pas
inventer » conservé (params toujours issus de HF, jamais du texte web).

## Rappels d'unité (piège)

- Params EcoLogits = **milliards** partout (`ParamsResult.active/total`, `model_params`).
- `safetensors.total` (HF) = compte **brut** → `÷ 1e9`.
- Saisie `models` = milliards (ex. `7` pour 7B).
