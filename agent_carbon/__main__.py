import argparse
import json
import os
import sys

from agent_carbon.collectors.claude_code import ClaudeCodeCollector
from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.report.cli import render_report
from agent_carbon.statusline.line import render_statusline
from agent_carbon.store.db import SQLiteStore

_DEFAULT_SOURCE = os.path.expanduser("~/.claude/projects")
_DEFAULT_DB = os.path.expanduser("~/.agent-carbon/carbon.db")


def _store(db_path: str) -> SQLiteStore:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    return SQLiteStore(db_path)


def _engine(config: Config) -> EcoLogitsEngine:
    return EcoLogitsEngine(ModelResolver(config.model_aliases))


def _read_stdin_json() -> dict | None:
    """Claude Code passe un JSON de session sur stdin (session_id,
    transcript_path…). Renvoie None en lancement manuel (terminal)."""
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _ingest_summary(new_count: int, cov: dict) -> str:
    line = f"{new_count} events ingérés · {cov['measured']}/{cov['total']} mesurés"
    if cov["uncovered"]:
        line += (
            f" · {cov['uncovered']} non couverts "
            "(inférence locale ou fournisseurs tiers non modélisés — conservés, impact non estimé)"
        )
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-carbon")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="parser les transcripts et calculer l'impact")
    p_ing.add_argument("--source", default=_DEFAULT_SOURCE)
    p_ing.add_argument("--db", default=_DEFAULT_DB)

    p_rep = sub.add_parser("report", help="afficher le rapport multi-critères")
    p_rep.add_argument("--db", default=_DEFAULT_DB)
    p_rep.add_argument("--by", choices=["model", "project", "total"], default="model")
    p_rep.add_argument("--since", default=None)
    p_rep.add_argument("--detail", action="store_true",
                       help="affiche les fourchettes min–max au lieu de la valeur centrale")

    p_st = sub.add_parser("statusline", help="ligne compacte pour la statusline")
    p_st.add_argument("--db", default=_DEFAULT_DB)

    args = parser.parse_args(argv)
    config = Config()

    if args.cmd == "ingest":
        store = _store(args.db)
        events = ClaudeCodeCollector(args.source).collect()
        n = store.ingest(events, _engine(config), config)
        print(_ingest_summary(n, store.coverage()))
        return 0

    if args.cmd == "report":
        store = _store(args.db)
        print(render_report(store.rows_for_report(args.since), group_by=args.by, detail=args.detail))
        return 0

    if args.cmd == "statusline":
        store = _store(args.db)
        # Claude Code fournit la session courante sur stdin.
        data = _read_stdin_json()
        session_id = data.get("session_id") if data else None
        transcript = data.get("transcript_path") if data else None
        # Ingestion à la volée du transcript courant (idempotent) → impact à
        # jour même en cours de session, sans attendre le hook Stop.
        if transcript and os.path.exists(transcript):
            store.ingest(ClaudeCodeCollector(transcript).collect(), _engine(config), config)
        print(render_statusline(store.rows_for_report(session_id=session_id)))
        return 0

    return 1
