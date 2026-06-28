#!/usr/bin/env bash
# statusline.sh — ligne compacte agent-carbon pour la statusLine de Claude Code.
#
# Claude Code exécute ce script à chaque rafraîchissement et affiche sa sortie ;
# il envoie du JSON sur stdin, qu'on ignore (on lit la base agent-carbon).
# Résilient : ne renvoie jamais d'erreur dans la barre — au pire, une ligne vide.
#
# Usage (référencé depuis ~/.claude/settings.json) :
#   scripts/statusline.sh [DB_PATH]
set -uo pipefail

DB="${1:-${AGENT_CARBON_DB:-$HOME/.agent-carbon/carbon.db}}"
AC="$(command -v agent-carbon 2>/dev/null || echo "$HOME/.agent-carbon/src/.venv/bin/agent-carbon")"

[ -x "$AC" ] || exit 0
"$AC" statusline --db "$DB" 2>/dev/null || true
