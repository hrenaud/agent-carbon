#!/usr/bin/env bash
set -euo pipefail

# install.sh — Installeur one-line pour agent-carbon.
#
#   curl -fsSL https://raw.githubusercontent.com/hrenaud/agent-carbon/main/install.sh | bash
#
# Variables d'environnement (optionnelles) :
#   AGENT_CARBON_DIR        répertoire d'installation        (défaut: ~/.agent-carbon/src)
#   AGENT_CARBON_DB         chemin de la base SQLite          (défaut: ~/.agent-carbon/carbon.db)
#   AGENT_CARBON_REF        branche/tag git à installer       (défaut: main)
#   AGENT_CARBON_NO_CLAUDE  =1 → ne touche pas à settings.json
#   AGENT_CARBON_NO_INGEST  =1 → pas d'ingestion initiale

REPO_URL="${AGENT_CARBON_REPO:-https://github.com/hrenaud/agent-carbon.git}"
INSTALL_DIR="${AGENT_CARBON_DIR:-$HOME/.agent-carbon/src}"
DB_PATH="${AGENT_CARBON_DB:-$HOME/.agent-carbon/carbon.db}"
REF="${AGENT_CARBON_REF:-main}"
BIN_DIR="$HOME/.local/bin"
SETTINGS_FILE="$HOME/.claude/settings.json"

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

printf '\n  agent-carbon installer\n'
printf '  Compteur d'\''impact multi-critères (énergie, GWP, eau, ADPe, PE) via EcoLogits.\n\n'

# 1. Prérequis ---------------------------------------------------------------
command -v git >/dev/null 2>&1 || die "git est requis (brew install git / apt install git)."

# Trouve un Python >= 3.10 (EcoLogits 0.11 l'exige).
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && \
     "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
    PYTHON="$cand"; break
  fi
done
[ -n "$PYTHON" ] || die "Python >= 3.10 introuvable (brew install python@3.13)."
ok "Python: $("$PYTHON" --version 2>&1) · git: présent"

# 2. Clone / mise à jour -----------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
  say "Mise à jour de $INSTALL_DIR ..."
  git -C "$INSTALL_DIR" fetch --quiet origin "$REF"
  git -C "$INSTALL_DIR" checkout --quiet "$REF"
  git -C "$INSTALL_DIR" pull --ff-only --quiet origin "$REF"
else
  say "Clonage dans $INSTALL_DIR ..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --quiet --branch "$REF" "$REPO_URL" "$INSTALL_DIR"
fi
ok "Source: $INSTALL_DIR ($REF)"

# 3. Environnement virtuel + installation (tire EcoLogits depuis le tag git) --
say "Création du venv et installation (EcoLogits peut prendre 1-2 min) ..."
"$PYTHON" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet -e "$INSTALL_DIR"
AC_BIN="$INSTALL_DIR/.venv/bin/agent-carbon"
[ -x "$AC_BIN" ] || die "Installation échouée : $AC_BIN introuvable."
ok "agent-carbon installé dans le venv"

# 3b. Installation du CLI HuggingFace (pour resolve --set via hf models info) --
HF_BIN="$INSTALL_DIR/.venv/bin/hf"
if [ ! -x "$HF_BIN" ]; then
  say "Installation du CLI HuggingFace (hf) ..."
  "$INSTALL_DIR/.venv/bin/python" -m pip install --quiet huggingface_hub[cli]
  [ -x "$HF_BIN" ] || die "Installation du CLI hf échouée."
  ok "CLI hf installé dans le venv"
fi

# 4. Expose la commande sur le PATH ------------------------------------------
mkdir -p "$BIN_DIR"
ln -sf "$AC_BIN" "$BIN_DIR/agent-carbon"
ok "Lien: $BIN_DIR/agent-carbon"
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) warn "$BIN_DIR n'est pas dans votre PATH — ajoutez : export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

# 5. Câblage Claude Code (statusline + hook d'ingestion) ---------------------
if [ "${AGENT_CARBON_NO_CLAUDE:-0}" != "1" ]; then
  mkdir -p "$(dirname "$SETTINGS_FILE")"
  STATUSLINE_CMD="$INSTALL_DIR/scripts/statusline.sh $DB_PATH"
  INGEST_CMD="$AC_BIN ingest --db $DB_PATH"
  "$INSTALL_DIR/.venv/bin/python" - "$SETTINGS_FILE" "$STATUSLINE_CMD" "$INGEST_CMD" <<'PY'
import json, sys
path, statusline_cmd, ingest_cmd = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

# statusLine — n'écrase jamais une statusLine d'un autre outil.
sl = cfg.get("statusLine")
if not sl:
    cfg["statusLine"] = {"type": "command", "command": statusline_cmd}
    print("  statusLine: ajoutée")
elif "agent-carbon" in (sl.get("command") or ""):
    cfg["statusLine"]["command"] = statusline_cmd
    print("  statusLine: déjà configurée (mise à jour)")
else:
    print("  statusLine: ignorée (déjà prise par un autre outil)")
    print("    Pour basculer, mettez dans ~/.claude/settings.json :")
    print("    " + statusline_cmd)

# Hook Stop → ingestion idempotente en fin de session.
hooks = cfg.setdefault("hooks", {})
stop = hooks.setdefault("Stop", [])
already = any(
    "agent-carbon" in (h.get("command") or "") and "ingest" in (h.get("command") or "")
    for group in stop for h in group.get("hooks", [])
)
if already:
    print("  hook Stop (ingest): déjà configuré")
else:
    stop.append({"matcher": "", "hooks": [{"type": "command", "command": ingest_cmd}]})
    print("  hook Stop (ingest): ajouté")

with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
  ok "Claude Code câblé ($SETTINGS_FILE)"

  # Skills (slash-skills) → ~/.claude/skills (symlinks, se mettent à jour avec le repo).
  SKILLS_SRC="$INSTALL_DIR/skills"
  SKILLS_DST="$HOME/.claude/skills"
  if [ -d "$SKILLS_SRC" ]; then
    mkdir -p "$SKILLS_DST"
    for d in "$SKILLS_SRC"/*/; do
      [ -d "$d" ] || continue
      name="$(basename "$d")"
      ln -sfn "$d" "$SKILLS_DST/$name"
      ok "skill: /$name"
    done
  fi
else
  say "Câblage Claude Code ignoré (AGENT_CARBON_NO_CLAUDE=1)."
fi

# 6. Ingestion initiale ------------------------------------------------------
if [ "${AGENT_CARBON_NO_INGEST:-0}" != "1" ]; then
  say "Ingestion initiale (peut être longue la première fois) ..."
  "$AC_BIN" ingest --db "$DB_PATH" || warn "Ingestion initiale non aboutie — relancez 'agent-carbon ingest'."
fi

# 7. Câblage Opencode/Crush (plugin + backfill) -------------------------------
if command -v opencode >/dev/null 2>&1 || command -v crush >/dev/null 2>&1; then
  OPENCODE_BIN="$(command -v opencode 2>/dev/null || command -v crush 2>/dev/null)"
  OPENCODE_PLUGIN_DIR="$HOME/.config/opencode/plugins"
  OPENCODE_CFG="$HOME/.config/opencode/opencode.json"
  OPENCODE_DB=""

  # Détecter la BDD Opencode/CRUSH locale.
  if [ -d "$HOME/.local/share/opencode" ]; then
    OPENCODE_DB="$HOME/.local/share/opencode/opencode.db"
  elif [ -d "$HOME/.local/share/crush" ]; then
    OPENCODE_DB="$HOME/.local/share/crush/crush.db"
  fi

  # 7a. Créer le plugin agent-carbon-crush.js.
  mkdir -p "$OPENCODE_PLUGIN_DIR"
  PLUGIN_SRC="$INSTALL_DIR/skills/agent-carbon-crush/agent-carbon-crush.js"
  PLUGIN_DST="$OPENCODE_PLUGIN_DIR/agent-carbon-crush.js"

  if [ -f "$PLUGIN_SRC" ]; then
    cp "$PLUGIN_SRC" "$PLUGIN_DST"
    ok "Plugin Opencode installé ($PLUGIN_DST)"
  else
    warn "Plugin Opencode introuvable dans $PLUGIN_SRC — omission."
  fi

  # 7b. Enregistrer le plugin dans opencode.json (si le fichier existe).
  if [ -f "$OPENCODE_CFG" ]; then
    "$INSTALL_DIR/.venv/bin/python" - "$OPENCODE_CFG" "$PLUGIN_DST" <<'PY'
import json, sys
cfg_path, plugin_path = sys.argv[1], sys.argv[2]
try:
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

plugins = cfg.setdefault("plugin", [])
if plugin_path not in plugins:
    plugins.append(plugin_path)
    print(f"  Plugin enregistré dans opencode.json: {plugin_path}")
else:
    print("  Plugin déjà enregistré dans opencode.json")

with open(cfg_path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
  else
    warn "opencode.json introuvable — le plugin ne sera pas chargé automatiquement."
    warn "  Pour charger manuellement : ajoutez « \"$PLUGIN_DST\" » à « plugin » dans $OPENCODE_CFG."
  fi

  # 7c. Backfill initial si la BDD locale existe.
  if [ -n "$OPENCODE_DB" ] && [ -f "$OPENCODE_DB" ]; then
    say "Backfill Opencode/CRUSH en cours (lecture directe de $OPENCODE_DB) ..."
    "$AC_BIN" ingest --db "$DB_PATH" --source-crush "$OPENCODE_DB" 2>/dev/null \
      && ok "Backfill initial effectué." \
      || warn "Backfill initial non abouti — relancez 'agent-carbon ingest --source-crush $OPENCODE_DB'."
  fi
else
  say "Opencode/CRUSH non détecté — câblage ignoré."
fi

printf '\n'
ok "Terminé."
say "Rapport   : agent-carbon report"
say "Statusline: redémarrez Claude Code pour voir l'impact en bas de l'écran."
printf '\n'
