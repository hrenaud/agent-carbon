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


def render_projects(rows: list[dict], show_all: bool = False) -> str:
    """Projets classés du plus au moins impactant (GWP, valeur centrale).
    Par défaut limité au top, le reste regroupé en « autres » ; ``show_all``
    affiche la liste complète."""
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

    values = [_central(v[0], v[1], factor) for _, v in data]
    name_w = max(len(n) for n, _ in data)
    val_w = max(len(v) for v in values)

    out = [f"Projets les plus impactants — trié par GWP ({unit}) · valeur centrale (~)", ""]
    for (name, gwp), val in zip(data, values):
        share = ((gwp[0] + gwp[1]) / 2) / total_mid
        filled = min(_BAR_WIDTH, round(share * _BAR_WIDTH))
        bar = "█" * filled + " " * (_BAR_WIDTH - filled)
        out.append(f"  {name.ljust(name_w)}  {val.rjust(val_w)}  {bar}  {round(share * 100):>3d}%")
    out.append("  " + "─" * (name_w + val_w + _BAR_WIDTH + 10))
    out.append(f"  {'TOTAL'.ljust(name_w)}  {_central(total[0], total[1], factor).rjust(val_w)}")
    return "\n".join(out)


# Colonnes du tableau d'intensité (ordre uniforme GWP → Eau → ADPe → Énergie → PE)
# avec icône + libellé court en en-tête (icônes seulement là, pour ne pas casser
# l'alignement des cellules : un émoji occupe 2 cellules visuelles mais 1 caractère).
_INTENSITY_COLS = ("gwp", "wcf", "adpe", "energy", "pe")
_COL_HEADER = {"gwp": "🌍 GWP/h", "wcf": "💧 Eau/h", "adpe": "⛏ ADPe/h",
               "energy": "⚡ Éner./h", "pe": "🔥 PE/h"}
_NAME_CAP = 18


def _truncate(name: str, cap: int = _NAME_CAP) -> str:
    return name if len(name) <= cap else name[: cap - 1] + "…"


def _intensity_cell(value: float, criterion: str) -> str:
    """Valeur centrale /h d'un critère, échelle d'unité choisie par cellule."""
    factor, unit = _scale(value, criterion)
    if value * factor < 0.005:
        return "≈0"
    return f"~{value * factor:.3g} {unit}"


def render_intensity(rows: list[dict]) -> str:
    """Intensité par modèle, par heure de travail effectif, en tableau aligné :
    une ligne par modèle (débit tokens/h + 5 critères d'émission /h)."""
    if not rows:
        return ""
    data = []
    for r in rows:
        perh = {c: r[c] / r["hours"] for c in CRITERIA}
        data.append({
            "name": _truncate(_short_model(r["model"])),
            "tph": _kilo(r["tokens"] / r["hours"]),
            "sort": r["tokens"] / r["hours"],
            "cells": {c: _intensity_cell(perh[c], c) for c in _INTENSITY_COLS},
        })
    data.sort(key=lambda d: d["sort"], reverse=True)
    name_w = max(len("modèle"), max(len(d["name"]) for d in data))
    tph_w = max(len("tok/h"), max(len(d["tph"]) for d in data))
    col_w = {c: max(len(_COL_HEADER[c]), max(len(d["cells"][c]) for d in data))
             for c in _INTENSITY_COLS}

    def _row(name: str, tph: str, cell) -> str:
        cols = "  ".join(cell(c).ljust(col_w[c]) for c in _INTENSITY_COLS)
        return f"  {name.ljust(name_w)}  {tph.rjust(tph_w)}  {cols}"

    out = ["Intensité par modèle — par heure de travail effectif (~ central)", ""]
    out.append(_row("modèle", "tok/h", lambda c: _COL_HEADER[c]))
    for d in data:
        out.append(_row(d["name"], d["tph"], lambda c, d=d: d["cells"][c]))
    return "\n".join(out)
