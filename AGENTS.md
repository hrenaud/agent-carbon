# agent-carbon — instructions projet

Compteur d'impact environnemental multi-critères pour les sessions d'IA, via

**EcoLogits** (aucune modélisation réécrite). Voir le README pour le produit.

## Documentation (à tenir à jour)

| Fichier                                                                                                                                          | Public / rôle                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| [README.md](README.md)                                                                                                                           | utilisateurs (non développeurs)                                        |
| [CONTRIBUTING.md](CONTRIBUTING.md)                                                                                                               | développeurs : architecture, schéma DB, dev, tests                     |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md)                                                                                                       | comprendre comment les impacts sont calculés (échanges EcoLogits)      |
| [CHANGELOG.md](CHANGELOG.md)                                                                                                                     | journal des évolutions                                                 |
| [docs/comparaison-donnees-outils.md](docs/comparaison-donnees-outils.md)                                                                         | comparatifs des informations des outils                                |
| [docs/superpowers/specs/2026-07-02-qualite-lecture-resolution-design.md](docs/superpowers/specs/2026-07-02-qualite-lecture-resolution-design.md) | backlog technique : audit qualité lecture données & résolution modèles |

> **À chaque tâche terminée : mettre à jour la doc concernée.** Ne pas toucher au
> CHANGELOG à la main : `agent-carbon release bump` le génère automatiquement
> depuis les commits conventionnels au moment de la release (cf. § Réaliser une
> release).

## Rappels projet

- **Tests** : `.venv/bin/python -m pytest` (TDD ; voir CONTRIBUTING).
- **Deux codebases, une base** : le repo dev **et** le clone installé

  `~/.agent-carbon/src` (qui fournit le binaire `agent-carbon` et les skills)

  partagent la base `~/.agent-carbon/carbon.db`. Après un changement de code ou de

  skill mergé sur `main`, **créer un tag de release** (`agent-carbon release bump

  <patch|minor|major>`) puis **relancer le script d'install**

  (`curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/install.sh | bash`)

  pour que le binaire et les skills installés soient à jour.

- **Paramètres EcoLogits en milliards** partout (piège récurrent — cf. METHODOLOGY).

## Réaliser une release

**Toujours passer par l'outil, jamais à la main** (il bump `pyproject.toml` **et**
`agent_carbon/__init__.py`, génère le CHANGELOG depuis les commits conventionnels,
crée le commit `chore(release): X.Y.Z` + tag `vX.Y.Z`, puis push `origin main --tags`) :

```bash
agent-carbon release bump <patch|minor|major>   # --no-push pour ne pas pousser
```

- `patch` : corrections backward-compatibles · `minor` : nouvelles features
  backward-compatibles · `major` : changements incompatibles.
- Prérequis : arbre propre, sur `main`, tag cible inexistant.
- Après le push, **relancer le script d'install** (voir ci-dessus) pour aligner le
  clone installé.
- Détail complet du process : cf. CONTRIBUTING (§ Release).
