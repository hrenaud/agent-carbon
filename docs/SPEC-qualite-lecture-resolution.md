# Spec — qualité de la lecture des données & de la résolution des modèles

> Issue d'un audit du 2026-07-02 (v0.3.2) sur : collecteurs, stockage, moteur
> d'impact et cascade de reconnaissance des modèles (EcoLogits → HF → Internet).
> Chaque point liste le constat, le fichier concerné et le correctif attendu.
> Les tests existants (163) passent ; les correctifs se font en TDD.

## Architecture auditée

```
Transcripts JSONL (Claude Code) ─┐
Exports JSON / SQLite (Opencode) ─┤→ InferenceEvent → SQLiteStore.ingest (idempotent, PK session+msg)
                                  │        │
                                  │        ▼ EcoLogitsEngine.compute
                                  │   1. ModelResolver (alias explicites, table vide)
                                  │   2. llm_impacts EcoLogits (registre officiel)
                                  │   3. si model-not-registered → ModelParamsResolver :
                                  │        registre EcoLogits → cache config → Hugging Face
                                  │        (HF : metadata safetensors → CLI hf info → index.json+HEAD)
                                  └─→ échec total → error="model-params-unresolved" (non couverts, conservés)
```

## Points forts (à préserver)

- Cascade offline-safe : aucun niveau ne lève d'exception, jamais de plantage
  d'ingest à cause du réseau (`impact/params.py`).
- Provenance tracée en DB : `source` (registry/user/huggingface) et `warnings`
  (`params-estimated-4bit`, `alias:x->y`…).
- Idempotence : `INSERT OR IGNORE` + backfill ciblé des colonnes ajoutées
  (`store/db.py`).
- Incertitude honnête : min–max persistés, valeur centrale calculée à
  l'affichage seulement ; `RangeValue` du registre géré.
- Non couverts conservés (pas jetés) ; `<synthetic>` exclus des compteurs.

## 🔴 Majeur

### M1 — Pas de cache négatif dans la cascade HF

- **Constat** : un échec de résolution HF n'est pas mémorisé
  (`impact/engine.py:109`, `impact/params.py:214-224`). Chaque nouvel event
  d'un modèle irrésolvable relance toute la cascade (model_info timeout 10 s +
  CLI `hf` timeout 30 s + index.json + N HEAD). Un backfill de 186 events d'un
  même modèle inconnu = 186 cascades réseau ; le hook Stop en subit une à
  chaque nouveau message d'un modèle non couvert.
- **Correctif attendu** : mémoriser l'échec — a minima en mémoire par run
  d'ingest (dict dans `ModelParamsResolver`), idéalement persisté en config
  avec TTL pour retenter périodiquement.

### M2 — Hypothèse « 4-bit » universelle (méthodes 2 et 3)

- **Constat** : `_bytes_to_params_estimated` (`impact/params.py:49-54`) divise
  les octets par 0.5 (4-bit). Pour un repo FP16/BF16 (2 octets/param) le
  résultat vaut **4× les params réels**. La méthode 2 (`used_storage` du CLI)
  compte en plus **tout le repo** (quantisations multiples, fichiers annexes)
  → surestimation possiblement massive, invisible dans le rapport (seul un
  warning de provenance est stocké).
- **Correctif attendu** : détecter le dtype (metadata safetensors, extension
  GGUF, nom du repo `-4bit`/`-fp16`…) et adapter les octets/param ; à défaut,
  produire une fourchette (0.5–2 octets/param) plutôt qu'une valeur unique, et
  faire remonter le warning dans le rapport.

### M3 — Warning `moe-assumed-dense` ajouté inconditionnellement

- **Constat** : `fetch_hf_params` (`impact/params.py:155`) ajoute
  `moe-assumed-dense` même pour un modèle réellement dense → pollue la
  provenance, dilue les vrais cas MoE.
- **Correctif attendu** : ne l'ajouter que si l'architecture est inconnue ou
  suspectée MoE (ex. nom contenant `AxB`).

## 🟠 Moyen

### N1 — Collision silencieuse d'events sans identifiants

- **Constat** : PK `(session_id, msg_id)` + `INSERT OR IGNORE`
  (`store/db.py:18,77`). Côté Crush, `session_id`/`msg_id` peuvent être vides
  (`collectors/crush.py:104-113`) : tous les events `("","")` s'écrasent en un
  seul — perte de données invisible.
- **Correctif attendu** : skipper (avec compteur) ou générer un id synthétique
  déterministe (hash timestamp+model+tokens).

### N2 — Timestamps comparés en chaînes, formats mixtes

- **Constat** : `_touch_session` (`store/db.py:129-130`) et les filtres
  `since` comparent lexicalement des ISO hétérogènes (`...Z` chez Claude Code,
  `...+00:00` chez Crush). OK tant que tout est UTC ; casse avec un offset
  non-UTC.
- **Correctif attendu** : normaliser le timestamp en ISO UTC canonique à
  l'ingestion (un seul format en DB).

### N3 — `--recompute` seul ne tente jamais de nouvelle résolution

- **Constat** : `recompute_errors` (`store/db.py:287-290`) filtre sur les
  modèles déjà mappés en config ; sans mapping, rien n'est recalculé. Documenté
  en docstring mais contre-intuitif côté CLI.
- **Correctif attendu** : l'expliciter dans l'aide CLI (`resolve --recompute`),
  et/ou offrir un `--retry-hf` qui retente la cascade HF sur les non couverts.

### N4 — Méthode 3 non bornée (HEAD séquentiels)

- **Constat** : `_fetch_safetensors_index_bytes` (`impact/params.py:34-42`)
  fait un HEAD par shard sans plafond : 50 shards = jusqu'à 50 requêtes × 10 s
  de timeout.
- **Correctif attendu** : plafonner (nombre de fichiers et budget temps
  global), abandonner proprement au-delà.

## 🟡 Mineur

- `collectors/crush.py:104` : `info.get("session_id") or info.get("ID")` —
  casse de clé incohérente (`ID` vs `id`), l'une des deux branches est
  probablement morte. Vérifier contre un export réel et nettoyer.
- `add_pending` commit à chaque event (`store/db.py:143`) au milieu d'un
  ingest qui commit déjà globalement — micro-perf, regrouper.
- Recherche du binaire `hf` par heuristique cwd/`~/.agent-carbon/src`
  (`impact/params.py:83-89`) — fragile mais fail-safe. Documenter ou
  configurer le chemin.
- Nom de modèle interpolé tel quel dans l'URL HF (`impact/params.py:22`) —
  risque faible (404), mais valider le format `org/name` avant requête.

## Priorisation proposée

1. **M1** (perf du hook Stop et des backfills) — TDD, sans dépendance.
2. **M2** (justesse des impacts auto-hébergés — seul endroit où le système
   peut produire des chiffres significativement faux sans le signaler).
3. M3, N1, N2 (intégrité / provenance).
4. N3, N4, mineurs (UX / robustesse).
