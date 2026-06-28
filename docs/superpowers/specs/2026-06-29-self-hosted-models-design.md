# agent-carbon — Design : évaluation des modèles auto-hébergés

> Spec issu du brainstorming du 2026-06-29.
> But : estimer l'impact des **modèles auto-hébergés** (Ollama, vLLM, llama.cpp, serveur on-prem…), pour lesquels EcoLogits n'a ni provider ni paramètres connus, **sans réécrire de modèle d'impact**.

## Principe directeur

On reste **vendor-neutral** et on continue de **déléguer le calcul à EcoLogits**. Le seul verrou pour l'auto-hébergé est qu'EcoLogits, via `llm_impacts()`, exige un modèle **enregistré dans son registre** (`models.find_model`). Or :

- la fonction **bas-niveau** `compute_llm_impacts()` accepte, elle, directement `model_active_parameter_count` / `model_total_parameter_count` + les 4 facteurs de mix + `datacenter_pue/wue` ;
- les données de **mix électrique** (215 zones ISO-3, `gwp/adpe/pe/wue` par kWh) sont déjà embarquées par EcoLogits.

Le problème se réduit donc à **une seule inconnue** : obtenir le couple `(params actifs, params totaux)` pour un modèle inconnu. Tout l'aval (mix → `compute_llm_impacts` → fourchette min/max) est partagé.

La **philosophie d'incertitude** du projet s'applique : ce qu'on ne connaît pas (PUE de l'hébergement, archi MoE) est **affiché en fourchette**, jamais maquillé en chiffre unique.

## Décisions tranchées (brainstorming)

| #   | Décision                  | Choix retenu                                                                                                                          |
| --- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Chaîne de résolution      | **Approche A** : registre EcoLogits → cache config → Hugging Face → file d'attente (question différée)                                |
| 2   | Question utilisateur (T3) | **Jamais en batch/hook**. Modèles non résolus mis en file ; saisie via commande interactive / au 1er `report` interactif              |
| 3   | Mix électrique            | **Détecter + confirmer** : locale/fuseau → pays → ISO-3, proposé puis confirmé. Persisté. Repli : choix dans une liste                |
| 4   | PUE / WUE                 | **Jamais obligatoires**. Plage par défaut « inconnu » **PUE 1.1–1.5**, **WUE 0**. Configurables → la fourchette se resserre si connus |
| 5   | Format du nom de modèle   | **Tolérant** : nom tenté tel quel comme `repo_id` HF ; sinon échec propre → tier 3. Pas de mapping exotique (format runtime non figé) |
| 6   | Persistance config        | Nouveau `~/.agent-carbon/config.json` (JSON = stdlib lecture+écriture, 0 dépendance ; la `Config` recréée à vide à chaque run)        |
| 7   | File d'attente            | **Table SQLite** `pending_models` dans `carbon.db`                                                                                    |
| 8   | Skill de réglage          | **`agent-carbon-config`** (périmètre large : mix + PUE/WUE + réglages futurs)                                                         |

## Chaîne de résolution des paramètres

```
(provider, model)
   │
   ▼  Tier 1 — Registre EcoLogits
models.find_model(provider) ; fallback provider="huggingface_hub"
   │ trouvé → (active, total)
   ▼  Tier 2 — Cache config
config.model_params["<provider>/<model>"]
   │ trouvé → (active, total)
   ▼  Tier 3 — Hugging Face (réseau, puis caché)
huggingface_hub.model_info(model).safetensors.total
   │ trouvé → (active=total [dense] ; MoE → assumé dense + warning)
   ▼  Échec
None → enregistré « non couvert » + ajouté à pending_models
```

Les 3 premiers tiers renvoient un `ParamsResult(active, total, source)`. Le 4e renvoie `None`.

## Composants

### 1. Config persistée — `agent_carbon/config.py` (+ chargement JSON)

`Config` gagne le chargement/sauvegarde depuis `~/.agent-carbon/config.json`. Champs :

| champ                  | défaut          | rôle                                                               |
| ---------------------- | --------------- | ------------------------------------------------------------------ |
| `electricity_mix_zone` | `None`          | sentinelle « non renseigné » → déclenche la détection au 1er usage |
| `datacenter_pue`       | plage `1.1–1.5` | PUE de l'hébergement auto-hébergé (cas « inconnu »)                |
| `datacenter_wue`       | `0.0`           | WUE (eau de refroidissement) — 0 = local                           |
| `model_params`         | `{}`            | cache `{"<provider>/<model>": {active, total, arch, source}}`      |
| `throughput_tok_s`     | `50.0`          | inchangé                                                           |
| `model_aliases`        | `{}`            | inchangé (ModelResolver)                                           |

> Le défaut historique `USA` est abandonné au profit de `None` pour pouvoir distinguer « non renseigné » de « choisi ».

### 2. Détection du mix — `agent_carbon/config_detect.py`

À l'install **ou** au premier `report` si `zone is None` :

1. lire la locale / le fuseau système → code pays alpha-2 ;
2. mapper alpha-2 → ISO-3 (table des pays courants ; sinon repli liste) ;
3. proposer la valeur, l'utilisateur confirme ou corrige ;
4. persister dans `config.json`.

### 3. Résolution des params — `agent_carbon/impact/params.py`

`ModelParamsResolver(config)` expose `resolve(provider, model) -> ParamsResult | None`, enchaînant les tiers 1→3 décrits plus haut. Le tier HF :

- tente `model_info(model)` sur le Hub ; toute erreur réseau/404 → renvoie `None` (jamais d'exception qui casse le batch) ;
- `safetensors.total` → params totaux ; **dense → `active = total`** ;
- **MoE** : safetensors ne donne pas l'actif → **assumé dense** (conservateur) + warning `moe-assumed-dense` ; affinable plus tard par déclaration manuelle ;
- résultat **écrit dans `config.model_params`** → un seul appel réseau par modèle, offline ensuite.

### 4. Moteur — `agent_carbon/impact/engine.py`

`compute()` :

- **Tier 1** inchangé : `llm_impacts(provider, model, …)`.
- Si `ModelNotRegisteredError` → `ModelParamsResolver.resolve()`. Si params trouvés → appel **direct** à `compute_llm_impacts()` avec :
  - `model_active_parameter_count` / `model_total_parameter_count` du resolver,
  - `if_electricity_mix_*` depuis `electricity_mixes.find_electricity_mix(zone)`,
  - `datacenter_pue` / `datacenter_wue` de la config (plages → propagées en min/max).
- Si `None` → `ImpactRecord` « non couvert » (comme aujourd'hui) **et** insertion dans `pending_models`.

### 5. File d'attente + saisie — table `pending_models` + commande

Table `pending_models(provider, model, first_seen, occurrences)` dans `carbon.db`.

- Nouvelle sous-commande `agent-carbon models` (interactive) : liste les modèles en attente, demande `params actifs/totaux` (+ archi dense/MoE), écrit dans `config.model_params`, purge la ligne.
- Au premier `report` **interactif** (TTY), si `pending_models` non vide → message + proposition de les renseigner.
- En contexte non-interactif (hook statusline, batch) → **aucune question**, on accumule seulement.

### 6. Skill `agent-carbon-config`

Skill dédié pour voir/changer `electricity_mix_zone`, `datacenter_pue`, `datacenter_wue` (et, plus tard, autres réglages). Réutilise `config_detect` pour la (re)détection du mix. Le prompt de détection à l'install passe aussi par là.

## Flux de données

```
ingest / report / statusline
   ↓ Config.load(~/.agent-carbon/config.json)   ── zone None ? → (report interactif) détection mix
InferenceEvent[]
   ↓ EcoLogitsEngine.compute()
       Tier 1 registre ─┐ trouvé → llm_impacts()
       ModelNotRegistered ─→ ModelParamsResolver (cache → HF) ─┐ trouvé → compute_llm_impacts()
                                                                └ None → non couvert + pending_models
ImpactRecord[]  (min/max, plage PUE incluse)
```

## Gestion d'erreurs & contraintes

- **Offline-first préservé** : le réseau n'est sollicité qu'au tier HF, **uniquement** pour un modèle jamais vu, et le résultat est caché. Échec réseau → `None`, jamais d'exception remontée au batch.
- **Hook/batch non bloquants** : aucune question interactive hors TTY explicite.
- **Confidentialité** : on ne stocke toujours que `{provider, model, tokens, ts, project, ids}` ; `model_params` ne contient que des métadonnées publiques de modèle.
- **Méthodologie versionnée** : la `source` des params (`registry` / `cache` / `huggingface` / `user`) est conservée dans le cache, et l'utilisation d'une plage PUE est visible dans le min/max du record.

## Tests (TDD — écrits avant l'implémentation)

| Cible                        | Vérifie                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------- |
| Persistance config           | round-trip load/save JSON ; défauts ; sentinelle `zone = None`                    |
| Détection mix                | mapping alpha-2 → ISO-3 ; repli liste quand détection impossible                  |
| `ModelParamsResolver` tier 1 | modèle connu du registre → params attendus                                        |
| `ModelParamsResolver` tier 2 | modèle dans `config.model_params` → court-circuite HF                             |
| `ModelParamsResolver` tier 3 | HF **mocké/offline** : dense → active=total ; MoE → warning ; 404/réseau → `None` |
| Moteur fallback              | `ModelNotRegisteredError` → `compute_llm_impacts` appelé avec bons params + mix   |
| Plage PUE                    | plage 1.1–1.5 propagée jusqu'au `(min, max)` final                                |
| File d'attente               | non résolu → insertion `pending_models` ; saisie utilisateur → purge + cache      |

## Hors périmètre

- Mapping « intelligent » des noms Ollama/GGUF → repo HF (format runtime non encore figé).
- Récupération automatique des params **actifs** d'un MoE (assumé dense pour l'instant).
- Mesure énergétique **réelle** (nvidia-smi / RAPL / wattmètre) — reste l'option « mesure » écartée au brainstorming.
