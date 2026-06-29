# Changelog

Toutes les évolutions notables du projet. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [Non publié]

### Modifié

- **`--since` accepte une date simple** : `report`/`resolve` acceptent désormais `--since 2026-06-27`, `--since 27/06/2026` ou `--since 27/06/26` (sans heure ni fuseau), normalisées en `YYYY-MM-DD` ; l'ISO 8601 complet reste accepté. Format invalide → erreur claire.

### Corrigé

- **Restauration du flag `report --detail`** (régressé lors de la fusion centrale+min–max dans la seule section « Impact total ») : `--detail` (alias `--detailed`) affiche de nouveau les **fourchettes min–max** dans les tableaux par modèle/projet (« Projets », « Tokens & impact par modèle », « Intensité ») au lieu de la valeur centrale `~`. Le store expose désormais les bornes min/max par critère ; vue compacte (`~`) par défaut.
- **`report --since` ne filtrait pas la section « Intensité par modèle »** : `intensity_by_model()` agrégeait tout l'historique quelle que soit la plage demandée. La méthode accepte désormais `since` et la commande `report` le propage — toutes les sections respectent `--since` de façon cohérente.

### Ajouté

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
