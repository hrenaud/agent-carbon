# TODO / Bug — `report --since` ne filtre pas la section « Intensité par modèle »

État au 2026-06-29.

## Symptôme

`agent-carbon report --since <ISO8601>` filtre bien la plupart des sections
(Impact total, Projets, Tokens & impact par modèle, Modèles non couverts), **mais
pas** « Intensité par modèle — par heure de travail effectif (~ central) » : ce
tableau agrège **tout l'historique**, en contradiction avec la plage demandée.

## Cause

`agent_carbon/__main__.py` (commande `report`) appelle :

```python
intensity = render_intensity(store.intensity_by_model())
```

`SQLiteStore.intensity_by_model()` (`agent_carbon/store/db.py`) **ne prend pas** de
paramètre `since` — son `SELECT … GROUP BY e.model` n'a aucune clause sur
`e.timestamp`. `args.since` n'est donc jamais propagé à cette section.

## Correctif attendu (petit, TDD)

1. Ajouter un paramètre `since: str | None = None` à `intensity_by_model`, et la
   clause `AND e.timestamp >= ?` (sur le modèle de `tokens_by_model` /
   `uncovered_by_model`, qui le font déjà).
2. Dans `__main__.py`, passer `store.intensity_by_model(args.since)`.
3. Test : ingestion sur deux dates, vérifier que `intensity_by_model(since=…)` exclut
   les events hors plage (cf. `test_tokens_by_model_filters_by_since`).

Note de cohérence : toutes les sections du rapport doivent respecter `--since` de la
même façon. Penser à vérifier qu'aucune autre section n'a la même fuite.
