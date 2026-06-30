import argparse
import json
import os
import sys

from agent_carbon.collectors.claude_code import ClaudeCodeCollector
from agent_carbon.config import Config, DEFAULT_CONFIG_PATH
from agent_carbon.config_detect import detect_zone, system_locale
from agent_carbon.dates import parse_since
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.params import (
    ModelParamsResolver,
    fetch_hf_params,
    fetch_moe_params_from_hf,
)
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.report.cli import (
    render_intensity,
    render_projects,
    render_report,
    render_tokens_by_model,
    render_uncovered,
)
from agent_carbon.release import ReleaseError, run as run_release
from agent_carbon.resolve.cli import cmd_resolve
from agent_carbon.statusline.line import render_statusline
from agent_carbon.store.db import SQLiteStore

_DEFAULT_SOURCE = os.path.expanduser("~/.claude/projects")
_DEFAULT_DB = os.path.expanduser("~/.agent-carbon/carbon.db")

# Rappel affiché en pied de chaque rapport : options et aide.
_REPORT_FOOTER = (
    "ℹ️  Options : `agent-carbon report --help` "
    "(--since <date> · --detail · --all-projects) · aide complète : skill `/agent-carbon-help`"
)


def _store(db_path: str) -> SQLiteStore:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    return SQLiteStore(db_path)


def _engine(config: Config) -> EcoLogitsEngine:
    return EcoLogitsEngine(ModelResolver(config.model_aliases))


def _maybe_detect_mix(config: Config) -> None:
    if config.electricity_mix_zone is not None or not sys.stdin.isatty():
        return
    guess = detect_zone(system_locale())
    prompt = f"Zone du mix électrique [{guess or 'ex. FRA'}] : "
    answer = input(prompt).strip().upper() or (guess or "")
    if answer:
        config.electricity_mix_zone = answer
        config.save()
        print(f"Zone enregistrée : {answer}")


def _cmd_models(args) -> int:
    store = _store(args.db)
    pending = store.list_pending()
    if not pending:
        print("Aucun modèle auto-hébergé en attente.")
        return 0
    for row in pending:
        print(f"· {row['provider']}/{row['model']} "
              f"({row['occurrences']} occurrences)")
    if not sys.stdin.isatty():
        return 0
    config = Config.load()
    accepted = []  # Collect (provider, model) to clear AFTER save
    for row in pending:
        # Étape 1 : type (dense/MoE)
        ans = input(
            f"Type pour {row['model']} (dense/MoE, vide = dense) : "
        ).strip().lower()
        if not ans or ans == "dense":
            # Dense : seul total demandé
            total_str = input(
                f"Params totaux pour {row['model']} "
                "en milliards (ex. 7 pour un modèle 7B, vide = ignorer) : "
            ).strip()
            if not total_str:
                continue
            try:
                total = float(total_str)
            except ValueError:
                print("Format invalide, ignoré.")
                continue
            config.model_params[f"{row['provider']}/{row['model']}"] = {
                "active": total, "total": total, "arch": "dense", "source": "user"}
            accepted.append((row["provider"], row["model"]))
        elif ans == "moe":
            # MoE : actif demandé, total cherché dans cache, registry, HF
            active_str = input(
                f"Params actifs pour {row['model']} "
                "en milliards (ex. 3,5 pour 3,5 Md) : "
            ).strip()
            if not active_str:
                continue
            try:
                active = float(active_str)
            except ValueError:
                print("Format invalide, ignoré.")
                continue
            # 1) Chercher dans cache (peut-être dense)
            key = f"{row['provider']}/{row['model']}"
            cache_entry = config.model_params.get(key)
            cache_total = None
            if cache_entry is not None:
                cache_total = float(cache_entry.get("total", active))
            # 2) Chercher dans registry via ModelParamsResolver
            resolver = ModelParamsResolver(config)
            res = resolver.resolve(row["provider"], row["model"])
            # 3) Tenter fetch MoE depuis HF
            hf_res = fetch_moe_params_from_hf(row["model"], active)
            if hf_res is not None:
                # HF trouvé → stocker comme MoE avec hf_repo
                total = float(hf_res.total)
                config.model_params[key] = {
                    "active": active, "total": total,
                    "arch": "moe", "source": "user",
                    "hf_repo": row["model"]}
            elif cache_total is not None:
                # Cache trouvé → utiliser son total, garder l'archi MoE du user
                total = cache_total
                # Ne pas écraser l'archi du cache si c'est dense
                # Laisser l'entry existante inchangée, juste stocker active si manquant
                if key not in config.model_params:
                    config.model_params[key] = {
                        "active": active, "total": total,
                        "arch": "moe", "source": "user"}
            else:
                # 4) Fallback : ni cache ni HF → total = active, stocker pour résolution future
                total = active
                config.model_params[key] = {
                    "active": active, "total": total,
                    "arch": "moe", "source": "user"}
            accepted.append((row["provider"], row["model"]))
    # Save config durably BEFORE clearing any pending models
    config.save()
    # Now clear the accepted models from pending
    for provider, model in accepted:
        store.clear_pending(provider, model)
    print("Paramètres enregistrés. Relancez `agent-carbon ingest`.")
    return 0


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
    p_rep.add_argument("--since", default=None, type=parse_since,
                       help="date de début (ex. 2026-06-27, 27/06/2026, 27/06/26)")
    p_rep.add_argument("--all-projects", action="store_true",
                       help="lister tous les projets (sinon top 5 + « autres »)")
    p_rep.add_argument("--detail", "--detailed", dest="detail", action="store_true",
                       help="afficher les fourchettes min–max au lieu de la valeur centrale (~)")

    p_st = sub.add_parser("statusline", help="ligne compacte pour la statusline")
    p_st.add_argument("--db", default=_DEFAULT_DB)

    p_mod = sub.add_parser("models", help="lister/renseigner les modèles auto-hébergés non résolus")
    p_mod.add_argument("--db", default=_DEFAULT_DB)

    p_res = sub.add_parser("resolve",
                           help="résoudre les modèles non couverts (params HF) et recalculer")
    p_res.add_argument("--db", default=_DEFAULT_DB)
    p_res.add_argument("--since", default=None, type=parse_since,
                       help="date de début (ex. 2026-06-27, 27/06/2026, 27/06/26)")
    p_res.add_argument("--list", action="store_true")
    p_res.add_argument("--json", action="store_true")
    p_res.add_argument("--set", action="append", default=[], metavar="P/M=REPO")
    p_res.add_argument("--forget", action="append", default=[], metavar="P/M")
    p_res.add_argument("--recompute", action="store_true")

    p_rel = sub.add_parser(
        "release",
        help="bump sémantique, génère le CHANGELOG et créer le tag",
    )
    p_rel_sub = p_rel.add_subparsers(dest="rel_cmd", required=True)
    p_bump = p_rel_sub.add_parser("bump", help="bump la version")
    p_bump.add_argument(
        "part", choices=("patch", "minor", "major"),
        help="partie à bump (patch, minor ou major)",
    )
    p_bump.add_argument("--push", action="store_true",
                        help="pusher main + tags après le release (optionnel)")

    args = parser.parse_args(argv)
    config = Config.load()

    if args.cmd == "ingest":
        store = _store(args.db)
        events = ClaudeCodeCollector(args.source).collect()
        n = store.ingest(events, _engine(config), config)
        print(_ingest_summary(n, store.coverage()))
        return 0

    if args.cmd == "report":
        store = _store(args.db)
        _maybe_detect_mix(config)
        rows = store.rows_for_report(args.since)
        out = render_report(rows)
        projects = render_projects(rows, show_all=args.all_projects, detailed=args.detail)
        if projects:
            out += "\n\n" + projects
        tokens = render_tokens_by_model(store.tokens_by_model(args.since), detailed=args.detail)
        if tokens:
            out += "\n\n" + tokens
        uncovered = render_uncovered(store.uncovered_by_model(args.since))
        if uncovered:
            out += "\n\n" + uncovered
        intensity = render_intensity(store.intensity_by_model(args.since), detailed=args.detail)
        if intensity:
            out += "\n\n" + intensity
        out += "\n\n" + _REPORT_FOOTER
        print(out)
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

    if args.cmd == "models":
        return _cmd_models(args)

    if args.cmd == "resolve":
        return cmd_resolve(args)

    if args.cmd == "release":
        try:
            new = run_release(args.part, push=args.push)
            print(f"Release {new} créé (tag `v{new}`). Push avec --push.")
            return 0
        except ReleaseError as e:
            print(f"Release bloqué : {e}", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
