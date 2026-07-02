# Checklist : intégrer un nouvel outil (client IA)

À suivre à chaque ajout d'une source d'événements (Claude Code, Opencode/Crush,
un futur client type Codex, etc.). Référence technique complète : voir
[CONTRIBUTING.md](../CONTRIBUTING.md) (architecture, schéma DB, conventions).

## 1. Collecteur (`agent_carbon/collectors/`)

- [ ] Implémenter une classe héritant de l'ABC `Collector` (`base.py`) :
      attributs `provider` / `client`, méthode `collect() -> Iterator[InferenceEvent]`.
- [ ] Choisir le modèle de référence le plus proche selon la source de données : - transcript fichier (JSONL…) → s'inspirer de `claude_code.py`. - export JSON + backfill SQLite → s'inspirer de `crush.py` (IDs
      synthétiques déterministes via SHA1 pour éviter les collisions de clé
      primaire).
- [ ] Dériver le `project` depuis le `cwd` si disponible ; estimer
      `active_seconds` ; ignorer les events sans usage tokens.
- [ ] Ne jamais extraire de contenu de prompt/réponse — uniquement les
      métadonnées nécessaires au calcul d'impact.

## 2. Tests (TDD — avant l'implémentation)

- [ ] Tests unitaires du collecteur (fixtures représentatives du format
      source, cas limites : event sans usage, cwd absent, doublons/idempotence).
- [ ] Test d'ingestion bout-en-bout (`SQLiteStore.ingest`) si le format
      d'entrée diffère significativement des collecteurs existants.
- [ ] `.venv/bin/python -m pytest -q` vert avant de continuer.

## 3. Câblage CLI (`agent_carbon/__main__.py`)

- [ ] Enregistrer le nouveau collecteur (option `--source-<outil>` si
      pertinent, cf. `--source-crush`).

## 4. `install.sh`

- [ ] Détecter l'outil (`command -v <outil>`).
- [ ] Backfill initial si une base/export local existe déjà.
- [ ] Câblage spécifique à l'outil (hook, plugin, config) si l'outil expose un
      mécanisme d'extension — cf. section Opencode/Crush (plugin `.js` +
      enregistrement dans `opencode.json`) pour un exemple.
- [ ] Ne jamais écraser une config/statusline déjà prise par un autre outil
      (cf. logique existante pour `statusLine` dans le câblage Claude Code).

## 5. Skill (`skills/`)

- [ ] Si l'outil a une UX conversationnelle propre, ajouter
      `skills/agent-carbon-<outil>/SKILL.md` (frontmatter `name`/`description`).
      L'installeur le déploie automatiquement par symlink.

## 6. Documentation

- [ ] `README.md` : mentionner le nouvel outil s'il change l'usage utilisateur
      (installation, détection automatique).
- [ ] `CONTRIBUTING.md` : mettre à jour le schéma d'architecture / la table
      des modules si le nouveau collecteur introduit un pattern différent.
- [ ] `docs/comparaison-donnees-outils.md` : ajouter l'outil au comparatif des
      formats/données disponibles.
- [ ] `docs/METHODOLOGY.md` : uniquement si l'outil introduit une nuance de
      calcul d'impact (ex. modèles auto-hébergés, tokenisation différente).

## 7. Vérification finale

- [ ] Suite de tests complète verte.
- [ ] Test manuel d'un `install.sh` de bout en bout (idéalement via
      `AGENT_CARBON_REF=<branche>` sur un répertoire de test, cf.
      CONTRIBUTING § Tester `install.sh` sur une branche) confirmant que la
      détection, le backfill et le câblage fonctionnent sans toucher aux
      configs d'un autre outil.
- [ ] Release (`agent-carbon release bump <patch|minor>`) une fois mergé sur
      `main`, puis relancer le script d'install (cf. § Deux codebases, une
      base dans AGENTS.md).
