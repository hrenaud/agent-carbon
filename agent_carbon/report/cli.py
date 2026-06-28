import re

from tabulate import tabulate

from agent_carbon.impact.engine import CRITERIA

_DATE_SUFFIX = re.compile(r"-\d{8}$")

# Échelle d'unité par critère, du plus grand au plus petit (facteur, unité).
# On choisit l'unité pour que les valeurs tombent dans une plage lisible
# (évite « 4e-05 kgSbeq » → « 40 mgSbeq »).
_UNIT_LADDERS = {
    "energy": [(1, "kWh"), (1e3, "Wh"), (1e6, "mWh")],
    "gwp": [(1, "kgCO2eq"), (1e3, "gCO2eq"), (1e6, "mgCO2eq")],
    "adpe": [(1, "kgSbeq"), (1e3, "gSbeq"), (1e6, "mgSbeq"), (1e9, "µgSbeq")],
    "pe": [(1, "MJ"), (1e3, "kJ"), (1e6, "J")],
    "wcf": [(1, "L"), (1e3, "mL"), (1e6, "µL")],
}
_ICON = {"energy": "⚡", "gwp": "🌍", "wcf": "💧", "adpe": "⛏", "pe": "🔥"}
_NAME = {"energy": "Énergie", "gwp": "GWP", "wcf": "Eau", "adpe": "ADPe", "pe": "PE"}
_SUMMARY_ORDER = ("energy", "gwp", "wcf", "adpe", "pe")


def _key(row: dict, group_by: str) -> str:
    if group_by == "total":
        return "TOTAL"
    return row.get(group_by, "?")


def _scale(hi: float, criterion: str) -> tuple[float, str]:
    """Unité d'affichage : 1re du barème où `hi` (borne haute) atteint 1."""
    chosen = _UNIT_LADDERS[criterion][0]
    for factor, unit in _UNIT_LADDERS[criterion]:
        chosen = (factor, unit)
        if hi * factor >= 1:
            break
    return chosen


def _short_model(name: str) -> str:
    """Raccourcit un nom de modèle pour la largeur du tableau :
    claude-haiku-4-5-20251001 → haiku-4-5."""
    return _DATE_SUFFIX.sub("", name.removeprefix("claude-"))


def _fmt(lo: float, hi: float, factor: float) -> str:
    # Valeur négligeable (modèle quasi inutilisé) : on évite un long « 0.000x »
    # qui élargit toute la colonne, on affiche « ≈0 ».
    if hi * factor < 0.005:
        return "≈0"
    return f"{lo * factor:.3g}–{hi * factor:.3g}"


def render_report(rows: list[dict], group_by: str) -> str:
    groups: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        g = groups.setdefault(_key(row, group_by), {c: [0.0, 0.0] for c in CRITERIA})
        for c in CRITERIA:
            g[c][0] += row[f"{c}_min"]
            g[c][1] += row[f"{c}_max"]

    totals = {c: [0.0, 0.0] for c in CRITERIA}
    for vals in groups.values():
        for c in CRITERIA:
            totals[c][0] += vals[c][0]
            totals[c][1] += vals[c][1]

    # Unité par critère, choisie sur le total → cohérente sur toute la colonne.
    units = {c: _scale(totals[c][1] or 1.0, c) for c in CRITERIA}

    # --- Section 1 : tableau aligné (tabulate, colonnes numériques à droite) ---
    headers = ["groupe"] + [f"{_NAME[c]} ({units[c][1]})" for c in CRITERIA]
    body = [
        [_short_model(name) if group_by == "model" else name]
        + [_fmt(vals[c][0], vals[c][1], units[c][0]) for c in CRITERIA]
        for name, vals in groups.items()
    ]
    if group_by != "total":
        body.append(["TOTAL"] + [_fmt(totals[c][0], totals[c][1], units[c][0]) for c in CRITERIA])

    table = tabulate(
        body, headers=headers, tablefmt="presto",
        colalign=["left"] + ["right"] * len(CRITERIA),
    )

    # --- Section 2 : agrégat des impacts avec icônes ---
    label_w = max(len(_NAME[c]) for c in _SUMMARY_ORDER)
    summary = ["Impact total (tous modèles) :"]
    for c in _SUMMARY_ORDER:
        factor, unit = units[c]
        summary.append(
            f"  {_ICON[c]} {_NAME[c].ljust(label_w)} : "
            f"{_fmt(totals[c][0], totals[c][1], factor)} {unit}"
        )

    footer = (
        "Fourchettes min–max (incertitude irréductible : région datacenter inconnue). "
        "Zone élec configurable (défaut USA). Impact basé sur les tokens de sortie."
    )
    return "\n".join([table, "", *summary, "", footer])
