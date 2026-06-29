import json

from agent_carbon.config import Config
from agent_carbon.impact.engine import EcoLogitsEngine
from agent_carbon.impact.params import fetch_hf_params
from agent_carbon.impact.resolver import ModelResolver
from agent_carbon.store.db import SQLiteStore


def parse_mapping(spec: str) -> tuple[str, str]:
    """ 'provider/model=hf_repo' → ('provider/model', 'hf_repo'). Coupe au 1er '='."""
    key, _, repo = spec.partition("=")
    return key.strip(), repo.strip()


def set_mappings(config, specs: list[str]) -> list[dict]:
    """Pour chaque mapping, récupère les params sur HF et les persiste sous la clé
    provider/model avec provenance. Échec géré par item, sans interrompre les autres."""
    results = []
    for spec in specs:
        key, repo = parse_mapping(spec)
        if not key or not repo:
            results.append({"key": key, "repo": repo, "ok": False, "error": "format"})
            continue
        params = fetch_hf_params(repo)
        if params is None:
            results.append({"key": key, "repo": repo, "ok": False,
                            "error": "hf-unresolved"})
            continue
        config.model_params[key] = {
            "active": params.active, "total": params.total, "arch": params.arch,
            "source": "resolve", "hf_repo": repo}
        results.append({"key": key, "repo": repo, "ok": True, "params": params.total})
    return results


def forget(config, keys: list[str]) -> list[dict]:
    """Retire chaque clé de model_params (revert d'un mapping)."""
    return [{"key": k, "removed": config.model_params.pop(k, None) is not None}
            for k in keys]


def _print_set(results: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(results, ensure_ascii=False))
        return
    for r in results:
        if r["ok"]:
            print(f"✓ {r['key']} → {r['repo']} ({r['params']:.1f} Md)")
        else:
            print(f"✗ {r['key']} → {r['repo'] or '?'} : {r['error']}")


def _print_forget(results: list[dict]) -> None:
    for r in results:
        print(f"{'retiré' if r['removed'] else 'absent'} : {r['key']}")


def _print_recompute(delta: dict) -> None:
    print(f"Recompute : {delta['before']} → {delta['after']} non couverts")


def _print_list(rows: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        print("Aucun modèle non couvert.")
        return
    for r in rows:
        print(f"· {r['model']} ({r['tokens']} tokens générés, {r['events']} events)")


def cmd_resolve(args) -> int:
    store = SQLiteStore(args.db)
    config = Config.load()
    changed = False
    forgotten_models = []

    if args.set:
        results = set_mappings(config, args.set)
        changed = any(r["ok"] for r in results) or changed
        _print_set(results, args.json)
    if args.forget:
        results = forget(config, args.forget)
        changed = any(r["removed"] for r in results) or changed
        _print_forget(results)
        # Track which models were forgotten to mark their events as errors
        forgotten_models = [r["key"] for r in results if r["removed"]]
    if changed:
        config.save()
    # Mark events referencing forgotten models as errors, so they'll be recomputed
    for model_key in forgotten_models:
        provider, model = model_key.split("/", 1)
        store.mark_model_events_error(provider, model, "model-params-reset")
    if args.recompute or changed:
        engine = EcoLogitsEngine(ModelResolver(config.model_aliases))
        _print_recompute(store.recompute_errors(engine, config))
    if args.list:
        _print_list(store.uncovered_by_model(args.since), args.json)
    return 0
