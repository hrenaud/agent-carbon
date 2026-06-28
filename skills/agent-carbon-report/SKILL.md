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
"$AC" report --by model
```

2. Par défaut, le rapport est **groupé par modèle** et affiche une **valeur centrale** (`~`). Adapter selon la demande :
   - par projet → `"$AC" report --by project`
   - total global → `"$AC" report --by total`
   - sur une période → ajouter `--since <ISO8601>` (ex. `--since 2026-06-01T00:00:00Z`)

3. Avec `--by model`, le rapport inclut une section **« Intensité par modèle »** (tokens/h et émissions/h par heure de travail effectif) qui compare l'efficacité des modèles — la présenter aussi.

4. Présenter le graphe **sans le déformer** (bloc de code monospace pour garder l'alignement), puis rappeler en une phrase :
   - la valeur centrale est marquée `~` (approximative) ; la section « Impact total » donne la **plage min–max** à côté (incertitude irréductible sur la région datacenter) ;
   - les modèles **locaux ou tiers non modélisés** sont comptés mais sans impact estimé (cf. ligne « non couverts »).
