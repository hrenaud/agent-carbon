import re

from agent_carbon.impact.engine import CRITERIA

_DATE_SUFFIX = re.compile(r"-\d{8}$")

# Échelle d'unité par critère (facteur, unité), du plus grand au plus petit,
# pour que les valeurs tombent dans une plage lisible (« 4e-05 kgSbeq » → « 40 mgSbeq »).
_UNIT_LADDERS = {
    "energy": [(1, "kWh"), (1e3, "Wh"), (1e6, "mWh")],
    "gwp": [(1, "kgCO2eq"), (1e3, "gCO2eq"), (1e6, "mgCO2eq")],
    "adpe": [(1, "kgSbeq"), (1e3, "gSbeq"), (1e6, "mgSbeq"), (1e9, "µgSbeq")],
    "pe": [(1, "MJ"), (1e3, "kJ"), (1e6, "J")],
    "wcf": [(1, "L"), (1e3, "mL"), (1e6, "µL")],
}
_ICON = {"energy": "⚡", "gwp": "🌍", "wcf": "💧", "adpe": "⛏", "pe": "🔥"}
_NAME = {"energy": "Énergie", "gwp": "GWP", "wcf": "Eau", "adpe": "ADPe", "pe": "PE"}
_SUMMARY_ORDER = ("gwp", "wcf", "adpe", "energy", "pe")
_BAR_WIDTH = 20
_TOP_N = 5


def _short_model(name: str) -> str:
    """claude-haiku-4-5-20251001 → haiku-4-5."""
    return _DATE_SUFFIX.sub("", name.removeprefix("claude-"))


def _scale(hi: float, criterion: str) -> tuple[float, str]:
    chosen = _UNIT_LADDERS[criterion][0]
    for factor, unit in _UNIT_LADDERS[criterion]:
        chosen = (factor, unit)
        if hi * factor >= 1:
            break
    return chosen


def _central(lo: float, hi: float, factor: float) -> str:
    if hi * factor < 0.005:  # négligeable
        return "≈0"
    return f"~{(lo + hi) / 2 * factor:.3g}"


def _range(lo: float, hi: float, factor: float) -> str:
    if hi * factor < 0.005:
        return "≈0"
    return f"{lo * factor:.3g}–{hi * factor:.3g}"


def _kilo(n: float) -> str:
    if n >= 1e6:
        return f"~{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"~{n / 1e3:.0f}k"
    return f"~{n:.0f}"


def render_report(rows: list[dict]) -> str:
    """Impact total multi-critères : valeur centrale (~) + plage min–max."""
    totals = {c: [0.0, 0.0] for c in CRITERIA}
    for row in rows:
        for c in CRITERIA:
            totals[c][0] += row[f"{c}_min"]
            totals[c][1] += row[f"{c}_max"]

    units = {c: _scale(totals[c][1] or 1.0, c) for c in CRITERIA}
    label_w = max(len(_NAME[c]) for c in _SUMMARY_ORDER)
    centrals = {c: f"{_central(totals[c][0], totals[c][1], units[c][0])} {units[c][1]}"
                for c in _SUMMARY_ORDER}
    central_w = max(len(v) for v in centrals.values())

    lines = ["Impact total (valeur centrale ~ · détail min–max) :"]
    for c in _SUMMARY_ORDER:
        rng = _range(totals[c][0], totals[c][1], units[c][0])
        lines.append(
            f"  {_ICON[c]} {_NAME[c].ljust(label_w)} : "
            f"{centrals[c].ljust(central_w)}   ({rng})"
        )
    lines.append("")
    lines.append(
        "Valeur centrale (~) et plage min–max. Incertitude irréductible : région "
        "datacenter d'Anthropic inconnue. Zone élec configurable (défaut USA). "
        "Impact basé sur les tokens de sortie."
    )
    return "\n".join(lines)


def render_projects(rows: list[dict], show_all: bool = False,
                    detailed: bool = False) -> str:
    """Projets classés du plus au moins impactant (GWP). Par défaut valeur
    centrale (~) ; ``detailed`` affiche la fourchette min–max. Limité au top,
    le reste regroupé en « autres » ; ``show_all`` affiche la liste complète."""
    if not rows:
        return ""
    groups: dict[str, list[float]] = {}
    for row in rows:
        g = groups.setdefault(row.get("project") or "?", [0.0, 0.0])
        g[0] += row["gwp_min"]
        g[1] += row["gwp_max"]

    total = [sum(v[0] for v in groups.values()), sum(v[1] for v in groups.values())]
    factor, unit = _scale(total[1] or 1.0, "gwp")
    total_mid = (total[0] + total[1]) / 2 or 1.0

    ranked = sorted(groups.items(), key=lambda kv: kv[1][0] + kv[1][1], reverse=True)

    # (nom affiché, fourchette gwp) ; longue traîne regroupée en « autres ».
    data: list[tuple[str, list[float]]] = []
    if not show_all and len(ranked) > _TOP_N + 1:
        data = [(name, v) for name, v in ranked[:_TOP_N]]
        tail = ranked[_TOP_N:]
        data.append((f"autres ({len(tail)} projets)",
                     [sum(v[0] for _, v in tail), sum(v[1] for _, v in tail)]))
    else:
        data = list(ranked)

    fmt = _range if detailed else _central
    values = [fmt(v[0], v[1], factor) for _, v in data]
    name_w = max(len(n) for n, _ in data)
    val_w = max(len(v) for v in values)

    legend = "fourchette min–max" if detailed else "valeur centrale (~)"
    out = [f"Projets les plus impactants — trié par GWP ({unit}) · {legend}", ""]
    for (name, gwp), val in zip(data, values):
        share = ((gwp[0] + gwp[1]) / 2) / total_mid
        filled = min(_BAR_WIDTH, round(share * _BAR_WIDTH))
        bar = "█" * filled + " " * (_BAR_WIDTH - filled)
        out.append(f"  {name.ljust(name_w)}  {val.rjust(val_w)}  {bar}  {round(share * 100):>3d}%")
    out.append("  " + "─" * (name_w + val_w + _BAR_WIDTH + 10))
    out.append(f"  {'TOTAL'.ljust(name_w)}  {fmt(total[0], total[1], factor).rjust(val_w)}")
    return "\n".join(out)


# Colonnes des tableaux par modèle (ordre uniforme GWP → Eau → ADPe → Énergie → PE)
# avec icône + libellé court en en-tête (icônes seulement là, pour ne pas casser
# l'alignement des cellules : un émoji occupe 2 cellules visuelles mais 1 caractère).
_INTENSITY_COLS = ("gwp", "wcf", "adpe", "energy", "pe")
_COL_HEADER = {"gwp": "🌍 GWP/h", "wcf": "💧 Eau/h", "adpe": "⛏ ADPe/h",
               "energy": "⚡ Éner./h", "pe": "🔥 PE/h"}
_TOTAL_HEADER = {"gwp": "🌍 GWP", "wcf": "💧 Eau", "adpe": "⛏ ADPe",
                 "energy": "⚡ Éner.", "pe": "🔥 PE"}
_NAME_CAP = 18


def _truncate(name: str, cap: int = _NAME_CAP) -> str:
    return name if len(name) <= cap else name[: cap - 1] + "…"


def _intensity_cell(value: float, criterion: str) -> str:
    """Valeur centrale d'un critère, échelle d'unité choisie par cellule."""
    factor, unit = _scale(value, criterion)
    if value * factor < 0.005:
        return "≈0"
    return f"~{value * factor:.3g} {unit}"


def _cell_detailed(lo: float, hi: float, criterion: str) -> str:
    """Cellule détaillée d'un critère : fourchette min–max (échelle par la borne haute)."""
    factor, unit = _scale(hi or 1.0, criterion)
    if hi * factor < 0.005:
        return "≈0"
    return f"{lo * factor:.3g}–{hi * factor:.3g} {unit}"


def _model_table(title: str, sec_header: str, headers: dict[str, str],
                 rows: list[dict], name_header: str = "modèle") -> str:
    """Tableau aligné « une ligne par modèle » (ou par outil) : colonne nom,
    une seconde colonne libre (tok/h, tokens…) et les 5 critères. ``rows`` :
    ``{name, second, sort, cells:{crit:str}}``, trié par ``sort`` décroissant."""
    if not rows:
        return ""
    rows = sorted(rows, key=lambda d: d["sort"], reverse=True)
    name_w = max(len(name_header), max(len(d["name"]) for d in rows))
    sec_w = max(len(sec_header), max(len(d["second"]) for d in rows))
    col_w = {c: max(len(headers[c]), max(len(d["cells"][c]) for d in rows))
             for c in _INTENSITY_COLS}

    def _line(name: str, sec: str, cell) -> str:
        cols = "  ".join(cell(c).ljust(col_w[c]) for c in _INTENSITY_COLS)
        # rstrip : ne pas padder la dernière colonne (espaces de fin inutiles qui
        # allongent la ligne et la font wrapper en terminal étroit).
        return f"  {name.ljust(name_w)}  {sec.rjust(sec_w)}  {cols}".rstrip()

    out = [title, "", _line(name_header, sec_header, lambda c: headers[c])]
    for d in rows:
        out.append(_line(d["name"], d["second"], lambda c, d=d: d["cells"][c]))
    return "\n".join(out)


def render_intensity(rows: list[dict], detailed: bool = False) -> str:
    """Intensité par modèle, par heure de travail effectif, en tableau aligné :
    une ligne par modèle (débit tokens/h + 5 critères d'émission /h). Par défaut
    valeur centrale (~) ; ``detailed`` affiche la fourchette min–max /h."""
    def _cells(r):
        h = r["hours"]
        if detailed:
            return {c: _cell_detailed(r[f"{c}_min"] / h, r[f"{c}_max"] / h, c)
                    for c in _INTENSITY_COLS}
        return {c: _intensity_cell(r[c] / h, c) for c in _INTENSITY_COLS}
    table = [{
        "name": _truncate(_short_model(r["model"])),
        "second": _kilo(r["tokens"] / r["hours"]),
        "sort": r["tokens"] / r["hours"],
        "cells": _cells(r),
    } for r in rows]
    suffix = "(min–max)" if detailed else "(~ central)"
    return _model_table(
        f"Intensité par modèle — par heure de travail effectif {suffix}",
        "tok/h", _COL_HEADER, table)


def render_intensity_by_client(rows: list[dict], detailed: bool = False) -> str:
    """Intensité par outil client (claude-code, opencode, pi…), par heure de
    travail effectif : même format que ``render_intensity`` (par modèle) mais
    agrégé par outil, pour comparer à débit égal quel outil consomme le plus
    de tokens et a les impacts les plus forts."""
    def _cells(r):
        h = r["hours"]
        if detailed:
            return {c: _cell_detailed(r[f"{c}_min"] / h, r[f"{c}_max"] / h, c)
                    for c in _INTENSITY_COLS}
        return {c: _intensity_cell(r[c] / h, c) for c in _INTENSITY_COLS}
    table = [{
        "name": r["client"],
        "second": _kilo(r["tokens"] / r["hours"]),
        "sort": r["tokens"] / r["hours"],
        "cells": _cells(r),
    } for r in rows]
    suffix = "(min–max)" if detailed else "(~ central)"
    return _model_table(
        f"Intensité par outil — par heure de travail effectif {suffix}",
        "tok/h", _COL_HEADER, table, name_header="outil")


def render_tokens_by_model(rows: list[dict], detailed: bool = False) -> str:
    """Tokens totaux utilisés par modèle sur la plage + impact des 5 critères,
    en tableau aligné (une ligne par modèle), trié par tokens. Par défaut valeur
    centrale (~) ; ``detailed`` affiche la fourchette min–max."""
    def _cells(r):
        if detailed:
            return {c: _cell_detailed(r[f"{c}_min"], r[f"{c}_max"], c)
                    for c in _INTENSITY_COLS}
        return {c: _intensity_cell(r[c], c) for c in _INTENSITY_COLS}
    table = [{
        "name": _truncate(_short_model(r["model"])),
        "second": _kilo(r["tokens"]),
        "sort": r["tokens"],
        "cells": _cells(r),
    } for r in rows]
    suffix = "(min–max)" if detailed else "(~ central)"
    out = _model_table(
        f"Tokens & impact par modèle — total sur la plage {suffix}",
        "tokens", _TOTAL_HEADER, table)
    if not out:
        return ""
    return out + (
        "\n\n  « tokens » = total utilisé (entrée + sortie + cache) ; "
        "l'impact reste calculé sur les seuls tokens de sortie."
    )


def render_uncovered(rows: list[dict]) -> str:
    """Modèles à impact non estimé (hors `<synthetic>`) : tokens générés sur la
    plage, triés décroissant, + invite à lancer la résolution. Vide si tout est
    couvert. ``rows`` : ``{model, tokens, events}``."""
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: r["tokens"], reverse=True)
    toks = [_kilo(r["tokens"]) for r in rows]
    name_w = max(len(r["model"]) for r in rows)
    tok_w = max(len(t) for t in toks)

    out = ["Modèles non couverts — tokens générés sur la plage (impact non estimé)", ""]
    for r, t in zip(rows, toks):
        out.append(f"  {r['model'].ljust(name_w)}  {t.rjust(tok_w)}")
    out.append("")
    out.append("  Paramètres inconnus d'EcoLogits → impact non estimable en l'état.")
    out.append("  → lance le skill `/agent-carbon-resolve` pour tenter de les résoudre via Hugging Face.")
    return "\n".join(out)


def render_estimated_note(models: list[str]) -> str:
    """Note d'avertissement : params estimés depuis la taille des fichiers
    (dtype supposé, précision limitée). Chaîne vide si aucun modèle concerné."""
    if not models:
        return ""
    return ("⚠️  Params estimés depuis la taille des fichiers (précision limitée) : "
            + ", ".join(models))
