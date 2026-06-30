# Changelog

## [0.2.0] — 2026-06-30

### Features

- système de release semver (commande CLI + 31 tests)
- (models) — soutenir les modèles MoE dans `agent-carbon models`
- (resolve) — déclarer un MoE dans --set via repo:actif
- pied de rapport rappelant --help + skill /agent-carbon-help
- --since accepte une date simple (2026-06-27 ou 27/06/26), sans heure ni TZ
- skill /agent-carbon-resolve + CTA rapport vers le skill
- sous-commande agent-carbon resolve (list/set/recompute/forget)
- resolve set_mappings/forget (mapping nom→repo HF + provenance)
- store.recompute_errors (recalcule les impacts en erreur)
- section « Modèles non couverts » + exclusion des <synthetic>
- section tokens & impact par modèle dans le rapport
- refonte tableau aligné de l'intensité par modèle
- dimension client (outil à l'origine de chaque event)
- CLI — config persistée chargée, sous-commande models, détection mix au report
- file d'attente pending_models (modèles non résolus, hors batch)
- moteur — fallback auto-hébergé via compute_llm_impacts (params resolver + mix + PUE)
- tier Hugging Face (params via safetensors, offline-safe, caché)
- ModelParamsResolver (tiers registre + cache config)
- détection zone mix depuis la locale système (alpha-2 → ISO-3)
- config persistée JSON (mix None, PUE/WUE en plage, cache model_params)
- ordre des indicateurs uniformisé (GWP, Eau, ADPe, Énergie, PE) + unité kgCO2eq cohérente
- section « Projets les plus impactants » (tri GWP, top 5 + --all-projects)
- retire le classement absolu par modèle/projet (sans insight) ; rapport = total + intensité
- section Intensité par modèle (tokens/h + 5 émissions/h, barre, temps actif)
- rapport — valeur centrale + plage min–max dans une seule section (retrait du flag --detail)
- rapport — valeur centrale (~) par défaut, plages min–max via --detail
- rapport repensé en graphe à barres trié par part de GWP (lisibilité) + retrait tabulate
- statusline scopée à la session en cours (stdin session_id + ingest transcript courant)
- rapport — tabulate (colonnes alignées) + échelle d'unité auto (lisibilité des petites valeurs)
- rapport — tableau aligné + section agrégée avec icônes (5 critères)
- ajoute l'eau (💧) à la statusline
- script scripts/statusline.sh pour la statusLine (settings.json pointe le script, pas une commande inline)
- skill /agent-carbon-report + déploiement des skills par l'installeur
- ingest non anxiogène — muselle les warnings EcoLogits, résumé de couverture clair
- installeur one-line (curl | bash) — venv, EcoLogits pin, câblage Claude Code idempotent
- CLI agent-carbon (ingest/report/statusline) + test end-to-end
- statusline compacte (énergie + GWP) lisant la DB
- rapport CLI multi-critères avec fourchettes (par modèle/projet/total)
- SQLiteStore (events/impacts/sessions, ingestion idempotente, durée)
- EcoLogitsEngine offline + ImpactRecord (5 critères, alias, gestion erreurs)
- ModelResolver (table d'alias, filet de sécurité)
- Collector ABC, ClaudeCodeCollector (parse JSONL réel) + stubs
- modèle InferenceEvent et Config
- scaffolding + test de non-régression EcoLogits offline (5 critères)

### Bug Fixes

- restaurer report --detail (min–max par modèle/projet) — régression du retrait du flag
- report --since filtre aussi la section « Intensité par modèle »
- revert d'un mapping oublié via méthode store appariée (session,msg)
- params auto-hébergés en milliards (HF safetensors ÷1e9, saisie en Md)
- models — parse robuste, sauvegarde avant purge, tests préservation config
- garde safetensors=None + tests cache-hit et total<=0 (tier HF)
- message final de l'installeur (retrait du flag --by obsolète)
- rapport tient en largeur — noms de modèles raccourcis + valeurs négligeables en ≈0

### Documentation

- TODO self-hosted — retirer la Suite 3 (livrée), intégrer le MoE resolve au socle
- CLAUDE.md projet — index doc (liens corrigés) + rappels (tests, sync clone, milliards)
- réorg — README orienté utilisateurs, METHODOLOGY (EcoLogits/impacts), CONTRIBUTING (tech, fusionne ARCHITECTURE)
- TODO self-hosted — ne garder que le backlog (Suites 2/3/4), retirer le fait
- TODO self-hosted — laguna résolu (MoE), non couverts 82→70, compteur de tests
- maj README (couverture, skills), CHANGELOG (footer/help), ARCHITECTURE (refonte à l'état actuel)
- (skill) — agent-carbon-report transmet --detail tel quel (ne pas remapper en --all-projects)
- noter le bug report --since non filtré sur la section Intensité
- TODO — MoE dans resolve --set (Suite 3) + étape websearch dans la cascade (Suite 4)
- commentaires conversion milliards + MoE différé (revue finale)
- TODO — resolve remplace le script jetable de recompute (validation terrain 82→76)
- spec agent-carbon-resolve (résolution des modèles non couverts)
- TODO suites modèles auto-hébergés (recompute base + MoE dans models)
- docstrings tiers cache/HF + commentaire timeout (revue finale)
- skill agent-carbon-config + entrée CHANGELOG (modèles auto-hébergés)
- plan d'implémentation modèles auto-hébergés + spec en JSON
- spec évaluation des modèles auto-hébergés (chaîne registre→HF→question)
- documente skill, statusline (script/bascule/preview), couverture d'ingest + CHANGELOG
- corrige zone défaut (USA) et eau fournie par EcoLogits 0.11.0 (litres)
- README (présentation + sources d'inspiration) et doc technique
- plan d'implémentation MVP agent-carbon (10 tâches TDD, du scaffolding aux docs)
- livrables documentaires MVP (README + doc technique avec sources d'inspiration)
- section Maintenance post-MVP — suivi version EcoLogits via GHA (détection auto, adoption gardée)
- pin EcoLogits sur tag stable mlco2/ecologits@0.11.0 (repo canonique), registre models.json
- spike EcoLogits — offline via git main (5 critères dont eau + modèles actuels), Python>=3.10
- durée de session captée (MVP) + énergie poste en placeholder séparé hors total
- principes confidentialité/versioning/config dans le spec (inspirés CodeCarbon + thirsty-llm)
- spec MVP agent-carbon (collecte Claude Code, EcoLogits offline, DB+rapport CLI+statusline)
- kickoff — audit claude-carbon, choix EcoLogits, archi collecte/impact/reporting

### Chores

- retirer KICKOFF.md (brief de démarrage obsolète, MVP livré)

### Refactoring

- extraire fetch_hf_params (repo→params réutilisable)

### Tests

- couvre le chemin RangeValue du resolver + commente le choix de moyenne
- assert input_tokens mapping (revue finale)

### Autres

- Merge feat/agent-carbon-resolve: résolution des modèles non couverts (resolve + skill)
- Merge feat/tokens-by-model: section tokens & impact par modèle
- Merge feat/intensity-table: tableau aligné de l'intensité
- Merge feat/client-dimension: dimension client par event
- Merge fix/selfhosted-params-billions: params auto-hébergés en milliards (corrige bug d'unité ×1e9)
- Merge feat/self-hosted-models: évaluation des modèles auto-hébergés (registre→HF→file)
- Merge feat/criteria-order: ordre indicateurs + libellés cohérents
- Merge feat/report-projects-ranking: classement projets par GWP
- Merge feat/drop-absolute-barchart: rapport recentré total + intensité
- Merge feat/intensity: intensité par modèle (efficacité)
- Merge feat/report-inline-detail: détail inline (central + plage)
- Merge feat/report-mean-detail: valeur centrale + vue détaillée
- Merge feat/report-barchart: rapport en graphe à barres lisible
- Merge feat/statusline-session: statusline = session courante
- Merge feat/report-tabulate: tableau tabulate + unités lisibles
- Merge feat/report-format: tableau aligné + section icônes
- Merge feat/statusline-water: eau dans la statusline
- Merge feat/docs: doc skill/statusline/couverture + CHANGELOG
- Merge feat/statusline-script: statusLine via script versionné
- Merge feat/skills: skill /agent-carbon-report + déploiement via installeur
- Merge feat/ingest-ux: sortie d'ingest claire et rassurante (couverture)
- Merge feat/installer: installeur one-line (curl | bash)
- Merge feat/mvp-implementation: MVP agent-carbon (collecte Claude Code, EcoLogits offline, DB+rapport+statusline)
Toutes les évolutions notables du projet. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

> Ce changelog est généré automatiquement par `agent-carbon release` entre deux tags.
> Les entrées manuelles ci-dessous restent valables avant le premier tag `v*`.

## Pré-versioning (entries manuelles)

### Système de release

- **Nouvelle sous-commande `agent-carbon release bump <patch|minor|major> [--push]`** : bump sémantique, génération automatique du CHANGELOG depuis les commits conventionnels entre le dernier tag et HEAD, mise à jour de `pyproject.toml` + `agent_carbon/__init__.py`, commit `chore(release): X.Y.Z` et tag `vX.Y.Z`. Le push n'est effectué qu'avec `--push`. Validation blocante : arbre propre, branche `main`, pas de tag existant.

## [Non publié]

### Modifié

- **`--since` accepte une date simple** : `report`/`resolve` acceptent désormais `--since 2026-06-27`, `--since 27/06/2026` ou `--since 27/06/26` (sans heure ni fuseau), normalisées en `YYYY-MM-DD` ; l'ISO 8601 complet reste accepté. Format invalide → erreur claire.

### Corrigé

- **Restauration du flag `report --detail`** (régressé lors de la fusion centrale+min–max dans la seule section « Impact total ») : `--detail` (alias `--detailed`) affiche de nouveau les **fourchettes min–max** dans les tableaux par modèle/projet (« Projets », « Tokens & impact par modèle », « Intensité ») au lieu de la valeur centrale `~`. Le store expose désormais les bornes min/max par critère ; vue compacte (`~`) par défaut.
- **`report --since` ne filtrait pas la section « Intensité par modèle »** : `intensity_by_model()` agrégeait tout l'historique quelle que soit la plage demandée. La méthode accepte désormais `since` et la commande `report` le propage — toutes les sections respectent `--since` de façon cohérente.

### Ajouté

- **MoE dans `agent-carbon models`** (Suite 2) : la sous-commande `models` interroge
  maintenant l'architecture (dense/MoE) ; si MoE, demande l'actif (en milliards),
  résout le total par cascade (cache → registre EcoLogits → Hugging Face), et
  stocke `arch="moe"` avec le couple `(actif, total)`. Le totalvient de HF (seul
  le total est nécessaire, l'actif est déclaré par l'utilisateur). Fallback
  `total = active` si ni cache ni HF ne trouvent le modèle.
- **MoE dans `resolve --set`** (Suite 3) : `--set "provider/model=repo:<actifs>"` déclare un Mixture-of-Experts — le **total** vient de Hugging Face (safetensors), l'**actif** (en milliards) est saisi, `arch="moe"`. Évite la **surestimation ~10×** des modèles routés (EcoLogits calcule sur les params actifs), constatée sur `nemotron-3-super-120b-a12b` et `laguna-m.1` qu'il fallait jusqu'ici éditer à la main. Le `:` est sans ambiguïté (un repo HF n'en contient pas) ; garde-fous actif `> 0` et `≤ total`. Le skill `/agent-carbon-resolve` propose l'actif (souvent lisible dans le nom, ex. `-a12b`). La syntaxe dense `--set "P/M=repo"` est inchangée.
- **Skill `/agent-carbon-help` + rappel `--help` en pied de rapport** : chaque rapport se termine par un rappel des options (`--since`, `--detail`, `--all-projects`) renvoyant vers `agent-carbon report --help` et le skill `/agent-carbon-help`, qui restitue l'aide réelle de la CLI (toutes commandes) sans rien inventer.
- **MVP** : compteur d'impact multi-critères (énergie, GWP, eau, ADPe, PE) avec fourchettes min–max, pour les sessions Claude Code.
  - Collecte des transcripts JSONL (`ClaudeCodeCollector`), confidentialité par conception (aucun contenu stocké).
  - Calcul d'impact **offline** délégué à EcoLogits (`mlco2/ecologits@0.11.0`), piloté par les tokens de sortie.
  - Stockage SQLite (`events` / `impacts` / `sessions`), ingestion idempotente, `methodology_version` par record.
  - Rapport CLI multi-critères (`--since`) et statusline compacte.
- **Installeur one-line** (`install.sh`, `curl … | bash`) : détection Python ≥ 3.10, venv, install EcoLogits, commande dans `~/.local/bin`, câblage Claude Code idempotent (statusline + hook `Stop` d'ingestion), première ingestion.
- **Skill `/agent-carbon-report`** (`skills/`) déployé par l'installeur dans `~/.claude/skills/`.
- **Script `scripts/statusline.sh`** : statusLine via script versionné (résilient) plutôt qu'une commande inline.
- **Sortie d'ingestion** : résumé de couverture clair (`mesurés` / `non couverts`) ; les warnings bruts d'EcoLogits sont silencés (information conservée par record) pour ne pas faire craindre un plantage.
- **Projets les plus impactants** : nouvelle section du rapport classant les projets du plus au moins émetteur (tri par **GWP**, valeur centrale + barre + part %). Top 5 par défaut (le reste regroupé en « autres »), `--all-projects` pour la liste complète. Respecte `--since`.
- **Tokens & impact par modèle** : nouvelle section du rapport — **tokens totaux utilisés** (entrée + sortie + cache) par modèle sur la plage (`--since`) et l'**impact central des 5 critères**, en tableau aligné trié par tokens décroissant. Répond à « combien de tokens et d'impact par modèle sur la période ».
- **Modèles non couverts** : nouvelle section du rapport listant les modèles à **impact non estimé** (paramètres inconnus d'EcoLogits) avec leurs **tokens générés** sur la plage, et une invite à lancer `agent-carbon-resolve`. Les placeholders internes `<synthetic>` (0 token, aucune inférence) sont exclus pour ne pas fausser le décompte.
- **Intensité par modèle** : nouvelle section du rapport (`--by model`) — par **heure de travail effectif** (temps actif estimé depuis les deltas de timestamps, plafonné à 5 min/message), **débit tokens/h** (barre de visualisation) et les **5 émissions/h**. Révèle l'efficacité comparée (ex. une heure d'Opus émet ~80× plus qu'une heure d'Haiku). Nouvelle colonne `events.active_seconds`, rétro-remplie à la ré-ingestion.
- **Évaluation des modèles auto-hébergés** : chaîne registre EcoLogits → cache → Hugging Face → file d'attente.
- **Config persistée** (`~/.agent-carbon/config.json`) : zone du mix (détectée à la 1re utilisation), PUE/WUE en plage.
- Sous-commande `agent-carbon models` pour renseigner les modèles non résolus.
- Skill `agent-carbon-config` pour régler mix et PUE/WUE.
- **Dimension `client`** : l'outil à l'origine de chaque event (`claude-code`, `opencode`…) est désormais stocké. Nouvelle colonne `events.client` (renseignée par le collector, rétro-remplie à la ré-ingestion), exposée dans `rows_for_report`. Prépare la ventilation de l'impact par client agentique.
- **`agent-carbon resolve` + skill `/agent-carbon-resolve`** : résolution des modèles non couverts. La CLI mappe un nom de modèle vers un repo Hugging Face (`--set "provider/model=repo"`), en récupère les paramètres (safetensors), recalcule les impacts en base (`--recompute`, automatique après un set) et sait annuler un mapping (`--forget`). Le skill orchestre : le LLM propose le repo HF, la CLI vérifie et recalcule, puis affiche un récap corrigeable. Provenance (`source: "resolve"`, `hf_repo`) persistée dans `config.model_params`.

### Modifié

- **Ordre des indicateurs** uniformisé partout (rapport, intensité, statusline) : **GWP → Eau → ADPe → Énergie → PE**. Unité GWP cohérente (`kgCO2eq`, la statusline affichait `kgCO2e`).
- **Statusline** : ajout de l'**eau** (💧 L) à côté de l'énergie et du GWP.
- **Statusline** : affiche désormais l'impact de la **session en cours** (lit `session_id` / `transcript_path` sur stdin, ingère le transcript courant, filtre par session) ; fallback total global en lancement manuel.
- **Rapport CLI** : recentré sur deux sections utiles — **Impact total** (5 critères, valeur centrale + plage) et **Intensité par modèle**. Le classement absolu par modèle/projet (`--by`) a été **retiré** : il était tautologique (plus on travaille, plus on émet) et n'apportait pas d'insight. **Échelle d'unité automatique** conservée (ex. `4e-05 kgSbeq` → `40 mgSbeq`).
- **Rapport CLI** : **valeur centrale** marquée `~` (ex. `~7.5 kgCO2eq`) plus lisible qu'une plage, avec la **plage min–max affichée dans la même section** (« Impact total ») — pas de rapport ni de flag séparé.
- **Intensité par modèle** : refonte en **tableau aligné** (une ligne par modèle, colonnes alignées, icônes en en-tête, noms longs tronqués). Remplace l'ancien rendu sur deux lignes aux unités auto-échelonnées par cellule et colonnes flottantes, peu lisible. La barre de débit tokens/h cède la place à la valeur tok/h ; unité d'émission lisible choisie par cellule.

### Notes

- L'incertitude (région datacenter d'Anthropic inconnue) est affichée en fourchette, jamais masquée.
- Hors MVP, posés en coutures : inférence locale, énergie du poste, backfill `carbon.db`, mode live, export fichier, multi-provider.
