#!/usr/bin/env bash
set -euo pipefail

# uninstall.sh — Désinstalleur pour agent-carbon (défait tout ce que install.sh met en place).
#
#   curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/uninstall.sh | bash
#
# Variables d'environnement (optionnelles, mêmes défauts que install.sh) :
#   AGENT_CARBON_DIR        répertoire d'installation        (défaut: ~/.agent-carbon/src)
#   AGENT_CARBON_DB         chemin de la base SQLite          (défaut: ~/.agent-carbon/carbon.db)
#   AGENT_CARBON_PURGE_DB   =1 → supprime aussi la base (l'historique d'impact). Gardée par défaut.

INSTALL_DIR="${AGENT_CARBON_DIR:-$HOME/.agent-carbon/src}"
DB_PATH="${AGENT_CARBON_DB:-$HOME/.agent-carbon/carbon.db}"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/agent-carbon"
SETTINGS_FILE="$HOME/.claude/settings.json"
SKILLS_DST="$HOME/.claude/skills"
OPENCODE_PLUGIN="$HOME/.config/opencode/plugins/agent-carbon-crush.js"
OPENCODE_CFG="$HOME/.config/opencode/opencode.json"
PYTHON="$(command -v python3 || true)"

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*" >&2; }

printf '\n  agent-carbon uninstaller\n\n'

# 1. Binaire (symlink $BIN_DIR/agent-carbon) — seulement s'il pointe vers l'install ---
if [ -L "$BIN_LINK" ] && [ "$(readlink "$BIN_LINK")" = "$INSTALL_DIR/.venv/bin/agent-carbon" ]; then
  rm "$BIN_LINK"
  ok "Lien supprimé: $BIN_LINK"
else
  say "Lien $BIN_LINK absent ou non lié à agent-carbon — ignoré."
fi

# 2. Skills (symlinks ~/.claude/skills pointant vers $INSTALL_DIR/skills) ------------
if [ -d "$SKILLS_DST" ] && [ -d "$INSTALL_DIR/skills" ]; then
  for link in "$SKILLS_DST"/*; do
    [ -L "$link" ] || continue
    case "$(readlink "$link")" in
      "$INSTALL_DIR/skills/"*) rm "$link"; ok "skill retiré: $(basename "$link")" ;;
    esac
  done
fi

# 3. settings.json — statusLine + hook Stop d'agent-carbon ---------------------------
if [ -f "$SETTINGS_FILE" ] && [ -n "$PYTHON" ]; then
  "$PYTHON" - "$SETTINGS_FILE" <<'PY'
import json, sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    cfg = json.load(fh)

sl = cfg.get("statusLine")
if sl and "agent-carbon" in (sl.get("command") or ""):
    del cfg["statusLine"]
    print("  statusLine: retirée")

hooks = cfg.get("hooks", {})
stop = hooks.get("Stop")
if stop:
    kept = []
    removed = 0
    for group in stop:
        group_hooks = [
            h for h in group.get("hooks", [])
            if not ("agent-carbon" in (h.get("command") or "") and "ingest" in (h.get("command") or ""))
        ]
        removed += len(group.get("hooks", [])) - len(group_hooks)
        if group_hooks:
            group["hooks"] = group_hooks
            kept.append(group)
    if removed:
        if kept:
            hooks["Stop"] = kept
        else:
            del hooks["Stop"]
        print(f"  hook Stop (ingest): retiré ({removed})")

with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
  ok "settings.json nettoyé ($SETTINGS_FILE)"
else
  say "settings.json absent — ignoré."
fi

# 4. Opencode/Crush — plugin fichier + entrée opencode.json -------------------------
if [ -f "$OPENCODE_PLUGIN" ]; then
  rm "$OPENCODE_PLUGIN"
  ok "Plugin Opencode supprimé: $OPENCODE_PLUGIN"
fi
if [ -f "$OPENCODE_CFG" ] && [ -n "$PYTHON" ]; then
  "$PYTHON" - "$OPENCODE_CFG" "$OPENCODE_PLUGIN" <<'PY'
import json, sys

cfg_path, plugin_path = sys.argv[1], sys.argv[2]
with open(cfg_path, encoding="utf-8") as fh:
    cfg = json.load(fh)

plugins = cfg.get("plugin")
if plugins and plugin_path in plugins:
    plugins.remove(plugin_path)
    print("  Plugin retiré d'opencode.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
PY
fi

# 5. Source + venv ($INSTALL_DIR) -----------------------------------------------------
if [ -d "$INSTALL_DIR" ]; then
  rm -rf "$INSTALL_DIR"
  ok "Répertoire d'installation supprimé: $INSTALL_DIR"
else
  say "$INSTALL_DIR absent — ignoré."
fi

# 6. Base de données — conservée par défaut ------------------------------------------
if [ "${AGENT_CARBON_PURGE_DB:-0}" = "1" ]; then
  if [ -f "$DB_PATH" ]; then
    rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
    ok "Base supprimée: $DB_PATH"
  fi
  # Supprime le répertoire parent (~/.agent-carbon) s'il est vide.
  parent="$(dirname "$DB_PATH")"
  rmdir "$parent" 2>/dev/null && ok "Répertoire vidé supprimé: $parent" || true
else
  say "Base conservée: $DB_PATH (AGENT_CARBON_PURGE_DB=1 pour la supprimer aussi)."
fi

printf '\n'
ok "Terminé."
