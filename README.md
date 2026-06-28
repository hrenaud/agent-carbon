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

# Afficher le rapport multi-critères
agent-carbon report [--db ~/.agent-carbon/carbon.db] [--by model|project|total] [--since ISO8601]

# Afficher une ligne compacte pour la statusline
agent-carbon statusline [--db ~/.agent-carbon/carbon.db]
```

### Exemples

```bash
# Ingérer les transcripts (d'abord)
agent-carbon ingest

# Rapport agrégé par modèle (défaut)
agent-carbon report

# Rapport par projet depuis hier
agent-carbon report --by project --since 2026-06-26T00:00:00Z

# Rapport total
agent-carbon report --by total

# Statusline (sortie minimale)
agent-carbon statusline
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
