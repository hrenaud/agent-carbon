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

2. Par défaut, le rapport est **groupé par modèle**. Adapter selon la demande de l'utilisateur :
   - par projet → `"$AC" report --by project`
   - total global → `"$AC" report --by total`
   - sur une période → ajouter `--since <ISO8601>` (ex. `--since 2026-06-01T00:00:00Z`)

3. Présenter le tableau sans le déformer, puis rappeler en une phrase :
   - les valeurs sont des **fourchettes min–max** (l'incertitude sur la région datacenter d'Anthropic est irréductible) ;
   - les modèles **locaux ou tiers non modélisés** sont comptés mais sans impact estimé (cf. ligne « non couverts »).
