from agent_carbon.impact.params import fetch_hf_params


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
