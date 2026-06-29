# agent-carbon

Compteur d'impact environnemental **multi-critères** et **vendor-neutral** pour les outils d'IA agentique. Il parse les transcripts (Claude Code en MVP), délègue le calcul d'impact à **EcoLogits**, et restitue un rapport CLI + une statusline.

## Pourquoi

Issu de l'audit de `claude-carbon` (mono-critère CO₂, facteurs dérivés du prix). Ici :

- **Multi-critères** : énergie, GWP, eau, ADPe, PE
- **Fourchettes min–max assumées** : l'incertitude sur la région datacenter d'Anthropic est irréductible, on la documente plutôt que de la dissimuler
- **Aucun modèle d'impact réécrit** — on s'appuie sur EcoLogits, moteur reconnu multi-critères/multi-phases

## Installation

### Rapide (one-line)

```bash
curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/install.sh | bash
```

L'installeur détecte Python ≥ 3.10, clone le projet dans `~/.agent-carbon/src`, crée un venv et installe EcoLogits (tag `mlco2/ecologits@0.11.0`), expose la commande `agent-carbon` dans `~/.local/bin`, câble la statusline + un hook d'ingestion dans `~/.claude/settings.json` (merge idempotent, ne touche pas à une statusline déjà prise par un autre outil), puis fait une première ingestion.

Variables optionnelles : `AGENT_CARBON_DIR`, `AGENT_CARBON_DB`, `AGENT_CARBON_REF`, `AGENT_CARBON_NO_CLAUDE=1` (ne pas modifier `settings.json`), `AGENT_CARBON_NO_INGEST=1` (pas d'ingestion initiale).

### Manuelle

- **Prérequis** : Python ≥ 3.10
- **Installation** : `pip install -e .` (installe EcoLogits depuis le tag `mlco2/ecologits@0.11.0`)

## Usage

```bash
# Parser les transcripts et remplir la base de données
agent-carbon ingest [--source ~/.claude/projects] [--db ~/.agent-carbon/carbon.db]

# Afficher le rapport : impact total multi-critères (valeur centrale ~ + plage min–max),
# « Projets les plus impactants » (classés par GWP), « Tokens & impact par modèle »
# (tokens totaux utilisés sur la plage + impact des 5 critères), « Modèles non couverts »
# (tokens générés par les modèles à impact non estimé + invite à agent-carbon-resolve)
# puis « Intensité par modèle » (tokens/h et émissions/h par heure de travail effectif).
agent-carbon report [--db ~/.agent-carbon/carbon.db] [--since DATE] [--all-projects] [--detail]
# --since accepte une date simple : 2026-06-27, 27/06/2026, 27/06/26 (ou un ISO 8601 complet)
# --detail (alias --detailed) : fourchettes min–max par modèle/projet au lieu de la centrale ~

# Afficher une ligne compacte pour la statusline
agent-carbon statusline [--db ~/.agent-carbon/carbon.db]

# Résoudre les modèles non couverts (mapping nom→repo HF + recompute)
agent-carbon resolve --list [--json]
agent-carbon resolve --set "provider/model=org/repo" # params HF + recompute auto
agent-carbon resolve --forget "provider/model" # annule un mapping
```

### Exemples

```bash
# Ingérer les transcripts (d'abord)
agent-carbon ingest

# Rapport (total + intensité par modèle)
agent-carbon report

# Rapport depuis une date (date simple, sans heure ni fuseau)
agent-carbon report --since 2026-06-26

# Lister tous les projets (sinon top 5 + « autres »)
agent-carbon report --all-projects

# Statusline (sortie minimale)
agent-carbon statusline
```

### Couverture (ce que dit la sortie d'`ingest`)

```
80 events ingérés · 33639/33709 mesurés · 70 non couverts (inférence locale ou fournisseurs tiers non modélisés — conservés, impact non estimé)
```

- **mesurés** : impact estimé par EcoLogits.
- **non couverts** : modèle hors périmètre EcoLogits (inférence locale, fournisseurs tiers) — l'event est **conservé** mais son impact n'est **pas** estimé (afficher faux serait pire). Ces lignes sont exclues des totaux du rapport. Beaucoup sont des placeholders internes `<synthetic>` (0 token, aucune inférence). Les vrais modèles tiers/auto-hébergés peuvent être résolus vers un repo Hugging Face via `agent-carbon resolve` (ou le skill `/agent-carbon-resolve`).

Les warnings bruts d'EcoLogits sont volontairement silencés pendant l'ingestion (l'information reste stockée par record) pour ne pas faire croire à un plantage.

## Skills Claude Code

Le projet fournit plusieurs skills (dans `skills/`), déployés par symlink dans `~/.claude/skills/` par l'installeur :

- **`/agent-carbon-report`** — rapport multi-critères (ou demander « mon impact / mon empreinte »).
- **`/agent-carbon-resolve`** — résout les modèles non couverts (mapping nom→repo Hugging Face + recompute).
- **`/agent-carbon-config`** — règle la zone du mix électrique et PUE/WUE.
- **`/agent-carbon-help`** — aide : commandes et options, à partir du `--help` réel de la CLI.

## Statusline dans Claude Code

Dans Claude Code, la statusline affiche l'impact de la **session en cours** : Claude Code transmet la session (`session_id`, `transcript_path`) sur stdin ; la commande ingère le transcript courant (idempotent) et filtre sur cette session. En lancement manuel (sans stdin), elle retombe sur le **total global** (pratique pour prévisualiser).

Le câblage passe par le script versionné **`scripts/statusline.sh [DB]`** (résout le binaire, lit la base, transmet stdin, résilient — ligne vide plutôt qu'une erreur). L'installeur l'inscrit dans `~/.claude/settings.json` :

- s'il n'y a pas de statusline → il ajoute la nôtre ;
- si la statusline est déjà à nous → il met à jour le chemin ;
- si elle appartient à un autre outil → il **n'y touche pas** et affiche la commande à coller pour basculer.

Prévisualiser sans rien changer à sa config :

```bash
~/.agent-carbon/src/scripts/statusline.sh   # ⚡ 18.9–33.5 kWh · 🌍 7.93–13.5 kgCO2e · 💧 61.3–134 L
```

## Sources d'inspiration

- **claude-carbon** — audit d'origine et UX de reporting.
- **EcoLogits** (`mlco2/ecologits`) — moteur d'impact multi-critères/multi-phases, offline.
- **CodeCarbon** — offline tracker + zone électrique par code pays (`country_iso_code`).
- **thirsty-llm** — approche offline-first, fourchettes et logging minimal (on rejette son modèle prix-proxy, justement remplacé par EcoLogits).

## Limites assumées

- **Impact piloté par les tokens de sortie** — seuls les tokens générés contribuent au calcul d'impact (input_tokens et cache ne sont pas pris en compte).
- **Région datacenter d'Anthropic inconnue** — d'où les fourchettes min–max ; par défaut, on considère le mix électrique USA (configurable).
- **Inférence locale et énergie du poste de travail hors MVP** — seule l'inférence cloud est traitée.

## Documentation technique

Voir [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) pour le détail du pipeline, du schéma de la base de données, et des mécanismes d'incertitude/méthodologie.
