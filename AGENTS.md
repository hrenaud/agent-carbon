# agent-carbon — instructions projet

Compteur d'impact environnemental multi-critères pour les sessions d'IA, via

**EcoLogits** (aucune modélisation réécrite). Voir le README pour le produit.

## Documentation (à tenir à jour)


| Fichier                                                                  | Public / rôle                                                     |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| [README.md](README.md)                                                   | utilisateurs (non développeurs)                                   |
| [CONTRIBUTING.md](CONTRIBUTING.md)                                       | développeurs : architecture, schéma DB, dev, tests                |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md)                               | comprendre comment les impacts sont calculés (échanges EcoLogits) |
| [CHANGELOG.md](CHANGELOG.md)                                             | journal des évolutions                                            |
| [docs/TODO-self-hosted-models.md](docs/TODO-self-hosted-models.md)       | backlog technique                                                 |
| [docs/comparaison-donnees-outils.md](docs/comparaison-donnees-outils.md) | comparatifs des informations des outils                           |


> **À chaque tâche terminée : mettre à jour la doc concernée ET le CHANGELOG.**

## Rappels projet

- **Tests** : `.venv/bin/python -m pytest` (TDD ; voir CONTRIBUTING).
- **Deux codebases, une base** : le repo dev **et** le clone installé

  `~/.agent-carbon/src` (qui fournit le binaire `agent-carbon` et les skills)

  partagent la base `~/.agent-carbon/carbon.db`. Après un changement de code ou de

  skill mergé sur `main`, **resynchroniser le clone**

  (`git -C ~/.agent-carbon/src pull --ff-only`) pour que le binaire et les skills

  installés soient à jour.
- **Paramètres EcoLogits en milliards** partout (piège récurrent — cf. METHODOLOGY).

