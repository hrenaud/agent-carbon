# Changelog

Toutes les évolutions notables du projet. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [Non publié]

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
- **Intensité par modèle** : nouvelle section du rapport (`--by model`) — par **heure de travail effectif** (temps actif estimé depuis les deltas de timestamps, plafonné à 5 min/message), **débit tokens/h** (barre de visualisation) et les **5 émissions/h**. Révèle l'efficacité comparée (ex. une heure d'Opus émet ~80× plus qu'une heure d'Haiku). Nouvelle colonne `events.active_seconds`, rétro-remplie à la ré-ingestion.
- **Évaluation des modèles auto-hébergés** : chaîne registre EcoLogits → cache → Hugging Face → file d'attente.
- **Config persistée** (`~/.agent-carbon/config.json`) : zone du mix (détectée à la 1re utilisation), PUE/WUE en plage.
- Sous-commande `agent-carbon models` pour renseigner les modèles non résolus.
- Skill `agent-carbon-config` pour régler mix et PUE/WUE.
- **Dimension `client`** : l'outil à l'origine de chaque event (`claude-code`, `opencode`…) est désormais stocké. Nouvelle colonne `events.client` (renseignée par le collector, rétro-remplie à la ré-ingestion), exposée dans `rows_for_report`. Prépare la ventilation de l'impact par client agentique.

### Modifié

- **Ordre des indicateurs** uniformisé partout (rapport, intensité, statusline) : **GWP → Eau → ADPe → Énergie → PE**. Unité GWP cohérente (`kgCO2eq`, la statusline affichait `kgCO2e`).
- **Statusline** : ajout de l'**eau** (💧 L) à côté de l'énergie et du GWP.
- **Statusline** : affiche désormais l'impact de la **session en cours** (lit `session_id` / `transcript_path` sur stdin, ingère le transcript courant, filtre par session) ; fallback total global en lancement manuel.
- **Rapport CLI** : recentré sur deux sections utiles — **Impact total** (5 critères, valeur centrale + plage) et **Intensité par modèle**. Le classement absolu par modèle/projet (`--by`) a été **retiré** : il était tautologique (plus on travaille, plus on émet) et n'apportait pas d'insight. **Échelle d'unité automatique** conservée (ex. `4e-05 kgSbeq` → `40 mgSbeq`).
- **Rapport CLI** : **valeur centrale** marquée `~` (ex. `~7.5 kgCO2eq`) plus lisible qu'une plage, avec la **plage min–max affichée dans la même section** (« Impact total ») — pas de rapport ni de flag séparé.

### Notes

- L'incertitude (région datacenter d'Anthropic inconnue) est affichée en fourchette, jamais masquée.
- Hors MVP, posés en coutures : inférence locale, énergie du poste, backfill `carbon.db`, mode live, export fichier, multi-provider.
