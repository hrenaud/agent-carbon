# agent-carbon

**Connaître l'empreinte environnementale de tes sessions d'IA.** agent-carbon lit les
transcripts de Claude Code, Opencode/CRUSH et Pi, estime l'impact de chaque réponse
générée, et te le restitue sous forme de rapport et de statusline — directement dans
Claude Code.

Le calcul n'est pas réinventé : il est délégué à **[EcoLogits](https://github.com/mlco2/ecologits)**,
un moteur reconnu, **offline** et **multi-critères**.

## Ce qu'on mesure

Pas seulement le CO₂. Cinq critères, chacun donné en **fourchette** (pas un faux
chiffre précis — voir « Pourquoi des fourchettes ») :

|     | Critère     | Ce que ça représente                       |
| --- | ----------- | ------------------------------------------ |
| 🌍  | **GWP**     | gaz à effet de serre (kg CO₂eq)            |
| 💧  | **Eau**     | eau consommée (L)                          |
| ⛏   | **ADPe**    | épuisement des métaux/ressources (kg Sbeq) |
| ⚡  | **Énergie** | électricité (kWh)                          |
| 🔥  | **PE**      | énergie primaire (MJ)                      |

> **Pourquoi des fourchettes ?** La région exacte des datacenters d'Anthropic (donc
> leur mix électrique) est inconnue, et le rendement d'un datacenter (PUE) varie. Cette
> incertitude est **irréductible** : on l'affiche (min–max + valeur centrale `~`)
> plutôt que de la cacher. Détails : [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## Installation

### Rapide (une ligne)

```bash
curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/install.sh | bash
```

L'installeur détecte Python ≥ 3.10, installe agent-carbon + EcoLogits, expose la
commande `agent-carbon`, déploie les skills, et câble la statusline + un hook
d'ingestion dans `~/.claude/settings.json` (sans toucher à une statusline déjà prise
par un autre outil). Il détecte aussi Opencode/CRUSH (plugin) et Pi (extension) s'ils
sont installés, et fait un backfill initial de leurs sessions locales. **Redémarre
Claude Code** ensuite pour activer les skills.

Variables optionnelles : `AGENT_CARBON_DIR`, `AGENT_CARBON_DB`,
`AGENT_CARBON_NO_CLAUDE=1` (ne pas modifier `settings.json`), `AGENT_CARBON_NO_INGEST=1`.
(Contributeurs : voir `AGENT_CARBON_REF` dans [CONTRIBUTING.md](CONTRIBUTING.md) pour
tester une branche.)

### Manuelle

Python ≥ 3.10, puis `pip install -e .`.

### Désinstallation

```bash
curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/uninstall.sh | bash
```

Retire le binaire, les skills, le câblage `~/.claude/settings.json` (statusline + hook
d'ingestion), le plugin Opencode/CRUSH, l'extension Pi et le répertoire source. **La
base `carbon.db` (historique d'impact) est conservée par défaut** — ajoute
`AGENT_CARBON_PURGE_DB=1` avant la commande pour la supprimer aussi.

## Utilisation — via les skills (recommandé)

Dans Claude Code, tape la commande, ou demande en langage naturel :

| Skill                       | À quoi ça sert                                                                                | Exemple                                             |
| --------------------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **`/agent-carbon-report`**  | Ton rapport d'impact complet.                                                                 | « mon impact », « mon empreinte CO₂ »               |
| **`/agent-carbon-resolve`** | Estimer l'impact de modèles tiers/locaux non reconnus (les associe à un modèle Hugging Face). | quand le rapport liste des « modèles non couverts » |
| **`/agent-carbon-config`**  | Régler ta zone électrique (ex. France) et les paramètres datacenter.                          | « configure ma zone élec »                          |
| **`/agent-carbon-help`**    | Aide : toutes les commandes et options.                                                       | « comment utiliser agent-carbon »                   |

Le rapport a cinq sections : **impact total**, **projets les plus impactants**,
**tokens & impact par modèle**, **modèles non couverts**, et **intensité par modèle**
(impact par heure de travail — révèle qu'à débit égal, Opus émet bien plus que Haiku).
Une sixième section, **intensité par outil**, apparaît automatiquement dès que tes
données couvrent plusieurs outils (Claude Code, Opencode/CRUSH, Pi…) — elle révèle
quel outil consomme le plus de tokens et a les impacts les plus forts, à débit égal.

Options utiles du rapport : `--since 2026-06-27` (ou `27/06/26`) pour une période,
`--detail` pour les fourchettes min–max par modèle/projet, `--all-projects` pour la
liste complète. `/agent-carbon-help` (ou `agent-carbon report --help`) les liste toutes.

## Statusline dans Claude Code

La statusline affiche l'impact de la **session en cours** (Claude Code transmet la
session ; agent-carbon ingère le transcript courant et filtre dessus). En lancement
manuel, elle retombe sur le **total global**.

```bash
~/.agent-carbon/src/scripts/statusline.sh   # ⚡ 18.9–33.5 kWh · 🌍 7.93–13.5 kgCO2e · 💧 61.3–134 L
```

L'installeur la câble dans `~/.claude/settings.json` (et ne remplace pas une
statusline appartenant à un autre outil — il affiche alors la commande pour basculer).

## En ligne de commande (sous le capot)

Les skills appellent simplement la CLI ; tu peux l'utiliser directement :

```bash
agent-carbon ingest      # parse les transcripts → base SQLite (~/.agent-carbon/carbon.db)
agent-carbon report      # rapport multi-critères (--since, --detail, --all-projects)
agent-carbon statusline   # ligne compacte
agent-carbon resolve --list   # modèles non couverts à résoudre
```

`ingest` résume la couverture, p. ex. :

```
80 events ingérés · 33639/33709 mesurés · 70 non couverts (conservés, impact non estimé)
```

Les « non couverts » sont des modèles hors périmètre EcoLogits — l'event est conservé
mais exclu des totaux (afficher un faux chiffre serait pire). Beaucoup sont des
placeholders internes `<synthetic>` (0 token) ; les vrais modèles tiers se résolvent
avec `/agent-carbon-resolve`. Voir [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## Pour aller plus loin

- **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)** — comment l'impact est évalué : les
  échanges avec EcoLogits, les choix de méthodologie et leurs limites.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — côté technique : architecture, schéma de
  données, mise en place dev et comment étendre le projet.

## Sources d'inspiration

- **EcoLogits** (`mlco2/ecologits`) — le moteur d'impact (offline, multi-critères/phases).
- **claude-carbon** — audit d'origine et UX de reporting.
- **CodeCarbon** — tracker offline, zone électrique par code pays.
- **thirsty-llm** — approche offline-first et fourchettes (on en rejette le modèle
  prix-proxy, remplacé par EcoLogits).
