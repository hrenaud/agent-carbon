---
name: agent-carbon-report
description: Affiche le rapport d'impact environnemental multi-critères (énergie, GWP, eau, ADPe, PE) des sessions d'IA, via agent-carbon. À utiliser quand l'utilisateur demande son empreinte / impact / CO2 / consommation / eau de ses sessions Claude Code, ou tape /agent-carbon-report.
---

Lance `agent-carbon` pour produire le rapport d'impact, puis présente la sortie **telle quelle** (ne reformate pas, ne réinvente pas les chiffres — ce sont des fourchettes min–max calculées par EcoLogits).

## Étapes

1. Localiser le binaire (installé via le one-line installer dans `~/.local/bin`, sinon dans le venv) et rafraîchir la base puis afficher le rapport :

```bash
AC="$(command -v agent-carbon || echo "$HOME/.agent-carbon/src/.venv/bin/agent-carbon")"
[ -x "$AC" ] || { echo "agent-carbon non installé. Installer : curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/install.sh | bash"; exit 1; }

# Rafraîchit la DB (silencieux), puis affiche le rapport.
"$AC" ingest >/dev/null 2>&1 || true
"$AC" report
```

2. Le rapport a cinq sections : **Impact total** (5 critères, valeur centrale `~` + plage min–max), **Projets les plus impactants** (classés par GWP — top 5 par défaut, `--all-projects` pour la liste complète), **Tokens & impact par modèle** (tokens totaux utilisés sur la plage + impact des 5 critères par modèle), **Modèles non couverts** (tokens générés par les modèles dont l'impact n'est pas estimé, avec invite à lancer `agent-carbon-resolve`) et **Intensité par modèle** (tokens/h et émissions/h par heure de travail effectif — compare l'efficacité des modèles). Filtre période possible : `--since <ISO8601>` (ex. `--since 2026-06-01T00:00:00Z`).

3. Présenter la sortie **sans la déformer** (bloc de code monospace pour garder l'alignement des barres), puis rappeler en une phrase :
   - la valeur centrale est marquée `~` (approximative) ; la plage min–max est à côté (incertitude irréductible sur la région datacenter) ;
   - les projets sont classés du plus au moins impactant (GWP) ; au-delà de la liste affichée, les autres projets sont regroupés (`--all-projects` pour tout voir) ;
   - l'intensité montre qu'à débit comparable, les modèles n'émettent pas autant (ex. Opus ≫ Haiku par heure) ;
   - les modèles **locaux ou tiers non modélisés** apparaissent dans la section « Modèles non couverts » avec leurs tokens générés ; proposer de lancer `agent-carbon-resolve` pour tenter de les résoudre (Hugging Face).

**Important — ne pas mentionner les `<synthetic>` :** une bonne partie des « non couverts » sont des messages internes de Claude Code étiquetés `<synthetic>` (0 token, aucune inférence réelle). Ils sont conservés pour la traçabilité mais **ne représentent aucun impact**. Ne les présente pas à l'utilisateur et ne les inclus pas dans le décompte des « non couverts » que tu commentes : ce serait trompeur. Ne commente que les vrais modèles non modélisés (inférence locale ou fournisseurs tiers).
