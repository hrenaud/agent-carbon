# Changelog

Toutes les évolutions notables du projet. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [Non publié]

### Ajouté

- **MVP** : compteur d'impact multi-critères (énergie, GWP, eau, ADPe, PE) avec fourchettes min–max, pour les sessions Claude Code.
  - Collecte des transcripts JSONL (`ClaudeCodeCollector`), confidentialité par conception (aucun contenu stocké).
  - Calcul d'impact **offline** délégué à EcoLogits (`mlco2/ecologits@0.11.0`), piloté par les tokens de sortie.
  - Stockage SQLite (`events` / `impacts` / `sessions`), ingestion idempotente, `methodology_version` par record.
  - Rapport CLI multi-critères (`--by model|project|total`, `--since`) et statusline compacte.
- **Installeur one-line** (`install.sh`, `curl … | bash`) : détection Python ≥ 3.10, venv, install EcoLogits, commande dans `~/.local/bin`, câblage Claude Code idempotent (statusline + hook `Stop` d'ingestion), première ingestion.
- **Skill `/agent-carbon-report`** (`skills/`) déployé par l'installeur dans `~/.claude/skills/`.
- **Script `scripts/statusline.sh`** : statusLine via script versionné (résilient) plutôt qu'une commande inline.
- **Sortie d'ingestion** : résumé de couverture clair (`mesurés` / `non couverts`) ; les warnings bruts d'EcoLogits sont silencés (information conservée par record) pour ne pas faire craindre un plantage.

### Modifié

- **Statusline** : ajout de l'**eau** (💧 L) à côté de l'énergie et du GWP.
- **Statusline** : affiche désormais l'impact de la **session en cours** (lit `session_id` / `transcript_path` sur stdin, ingère le transcript courant, filtre par session) ; fallback total global en lancement manuel.
- **Rapport CLI** : refonte en **graphe à barres** trié par GWP (critère phare) avec part en % — on saisit les proportions d'un coup ; longue traîne regroupée en « autres (N) » ; noms de modèles raccourcis ; **échelle d'unité automatique** (ex. `4e-05 kgSbeq` → `40 mgSbeq`) ; résumé multi-critères (5 icônes) sous le graphe. Sans dépendance (rendu fait main, largeurs fixes).
- **Rapport CLI** : **valeur centrale** marquée `~` (ex. `~7.5 kgCO2eq`) plus lisible qu'une plage, avec la **plage min–max affichée dans la même section** (« Impact total ») — pas de rapport ni de flag séparé.

### Notes

- L'incertitude (région datacenter d'Anthropic inconnue) est affichée en fourchette, jamais masquée.
- Hors MVP, posés en coutures : inférence locale, énergie du poste, backfill `carbon.db`, mode live, export fichier, multi-provider.
