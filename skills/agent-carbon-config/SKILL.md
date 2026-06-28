---
name: agent-carbon-config
description: Régler la configuration d'agent-carbon — zone du mix électrique, PUE et WUE de l'hébergement auto-hébergé. À utiliser quand l'utilisateur veut changer sa localisation/mix ou les hypothèses d'infrastructure.
---

# agent-carbon-config

Réglages persistés dans `~/.agent-carbon/config.json`.

## Champs

- `electricity_mix_zone` : code ISO-3 (ex. `FRA`, `DEU`, `USA`). `null` = détecté au prochain `report` interactif.
- `datacenter_pue` : plage `{min, max}` (défaut `1.1`–`1.5`). Plus bas = poste local ; plus haut = datacenter on-prem.
- `datacenter_wue` : litres d'eau par kWh (défaut `0`, local sans refroidissement eau).

## Procédure

1. Lire le fichier `~/.agent-carbon/config.json` (créer avec les défauts s'il est absent).
2. Demander à l'utilisateur la/les valeur(s) à changer.
3. Pour le mix, si l'utilisateur ne connaît pas son code, proposer une détection : `agent-carbon report` (interactif) déclenche la détection locale → ISO-3.
4. Écrire le JSON mis à jour (préserver les autres champs, notamment `model_params`).
5. Confirmer les valeurs enregistrées.

Ne jamais toucher `model_params` (cache des modèles auto-hébergés, géré par `agent-carbon models`).
