---
name: agent-carbon-report
description: Affiche le rapport d'impact environnemental multi-critères (énergie, GWP, eau, ADPe, PE) des sessions d'IA, via agent-carbon. À utiliser quand l'utilisateur demande son empreinte / impact / CO2 / consommation / eau de ses sessions Claude Code, ou tape /agent-carbon-report.
---

Lance `agent-carbon` pour produire le rapport d'impact, puis présente la sortie **telle quelle** (ne reformate pas, ne réinvente pas les chiffres — ce sont des fourchettes min–max calculées par EcoLogits).

## Étapes

1. Localiser le binaire et rafraîchir la base (silencieux) :

```bash
AC="$(command -v agent-carbon || echo "$HOME/.agent-carbon/src/.venv/bin/agent-carbon")"
[ -x "$AC" ] || { echo "agent-carbon non installé. Installer : curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/install.sh | bash"; exit 1; }
"$AC" ingest >/dev/null 2>&1 || true
```

2. **Poser les options à l'utilisateur** (voir « Comment poser les questions » ci-dessous), toujours — même s'il a passé des flags : dans ce cas, mets la valeur correspondante en première option « (Recommandé) ». Trois questions :

   - **Période** — header « Période ». Options : `Tout l'historique` (pas de `--since`), `30 derniers jours`, `7 derniers jours`. L'« Other » automatique laisse saisir une date précise (`2026-06-27`, `27/06/2026`, `27/06/26` ou ISO 8601).
   - **Projets** — header « Projets ». Options : `Top 5 + autres` (défaut, pas de flag), `Tous les projets` (`--all-projects`).
   - **Détail** — header « Détail ». Options : `Valeur centrale ~` (défaut, pas de flag), `Fourchettes min–max` (`--detail`).

3. **Construire les flags depuis les réponses**, puis lancer le rapport. Pour une période relative, calculer la date de début :

```bash
# ex. « 7 derniers jours » : SINCE=$(python3 -c "import datetime;print(datetime.date.today()-datetime.timedelta(days=7))")
"$AC" report [FLAGS]
```

`[FLAGS]` = concaténation de : `--since <date>` (si période ≠ tout), `--all-projects` (si « Tous les projets »), `--detail` (si « min–max »). Ne jamais inventer d'autres flags que ces trois.

4. Le rapport a cinq sections : **Impact total** (5 critères, valeur centrale `~` + plage min–max), **Projets les plus impactants** (classés par GWP — top 5 par défaut, `--all-projects` pour la liste complète), **Tokens & impact par modèle** (tokens totaux utilisés sur la plage + impact des 5 critères par modèle), **Modèles non couverts** (tokens générés par les modèles dont l'impact n'est pas estimé, avec invite à lancer `agent-carbon-resolve`) et **Intensité par modèle** (tokens/h et émissions/h par heure de travail effectif — compare l'efficacité des modèles). Avec `--detail`, les tableaux par modèle/projet passent en min–max.

5. Présenter la sortie **sans la déformer** (bloc de code monospace pour garder l'alignement des barres), puis rappeler en une phrase :
   - la valeur centrale est marquée `~` (approximative) ; la plage min–max est à côté (incertitude irréductible sur la région datacenter) ;
   - les projets sont classés du plus au moins impactant (GWP) ; au-delà de la liste affichée, les autres projets sont regroupés (`--all-projects` pour tout voir) ;
   - l'intensité montre qu'à débit comparable, les modèles n'émettent pas autant (ex. Opus ≫ Haiku par heure) ;
   - les modèles **locaux ou tiers non modélisés** apparaissent dans la section « Modèles non couverts » avec leurs tokens générés ; proposer de lancer `agent-carbon-resolve` pour tenter de les résoudre (Hugging Face).

**Important — ne pas mentionner les `<synthetic>` :** une bonne partie des « non couverts » sont des messages internes de Claude Code étiquetés `<synthetic>` (0 token, aucune inférence réelle). Ils sont conservés pour la traçabilité mais **ne représentent aucun impact**. Ne les présente pas à l'utilisateur et ne les inclus pas dans le décompte des « non couverts » que tu commentes : ce serait trompeur. Ne commente que les vrais modèles non modélisés (inférence locale ou fournisseurs tiers).

## Comment poser les questions (indépendant de l'outil)

Cette skill peut tourner sous plusieurs agents (Claude Code, OpenCode, Pi…). Pose les questions avec le mécanisme interactif du runtime **s'il en a un**, sinon en texte :

- **Claude Code** : outil `AskUserQuestion` (intitulé, `header`, options ; « Other » ajouté d'office).
- **OpenCode** : outil `question` (header, intitulé, liste d'options, réponse libre).
- **Pi** (earendil-works) : pas de tool natif (cœur = `read`/`bash`/`edit`/`write`) ; question structurée via extension (`pi-askuserquestion` / `pi-ask-user`), sinon repli texte ci-dessous.
- **Serveur/plateforme MCP** : elicitation MCP (`elicitation/create` avec un JSON schema).
- **Sinon** (runtime sans tool dédié) : présenter chaque question en clair, options **numérotées**, et **attendre** la réponse avant de continuer.

Dans tous les cas : une option = une valeur exploitable, prévoir une saisie libre (« autre »), et ne **construire/lancer la commande qu'après** avoir reçu les réponses. Ne jamais deviner à la place de l'utilisateur ni exécuter avant réponse.

> **Piège JSON (`AskUserQuestion` & tools MCP)** : l'entrée doit être du JSON **pur**. Chaque `question`/`label`/`description` est une chaîne littérale **déjà assemblée** — pas de concaténation (`"a" + "b"`), pas d'expression, pas de backslash non échappé (`\` → `\\` ou `/`). Sinon l'appel échoue avec « Invalid tool parameters / could not be parsed as JSON ».
