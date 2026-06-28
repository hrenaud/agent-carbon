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
_SUMMARY_ORDER = ("energy", "gwp", "wcf", "adpe", "pe")
_GROUP_NOUN = {"model": "modèle", "project": "projet"}

_BAR_WIDTH = 20
_TOP_N = 8


def _key(row: dict, group_by: str) -> str:
    if group_by == "total":
        return "TOTAL"
    return row.get(group_by, "?")


def _short_model(name: str) -> str:
    """claude-haiku-4-5-20251001 → haiku-4-5 (largeur du graphe)."""
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
    # valeur centrale, marquée « ~ » (≈, pas de fausse précision)
    return f"~{(lo + hi) / 2 * factor:.3g}"


def _range(lo: float, hi: float, factor: float) -> str:
    if hi * factor < 0.005:
        return "≈0"
    return f"{lo * factor:.3g}–{hi * factor:.3g}"


def _mid(pair: list[float]) -> float:
    return (pair[0] + pair[1]) / 2


def _bar_chart(groups: dict, totals: dict, group_by: str,
               unit: tuple[float, str]) -> list[str]:
    """Graphe à barres trié par GWP (critère phare), valeur centrale + part %."""
    factor, unit_label = unit
    total_mid = _mid(totals["gwp"]) or 1.0
    noun = _GROUP_NOUN.get(group_by, "groupe")

    ranked = sorted(groups.items(), key=lambda kv: _mid(kv[1]["gwp"]), reverse=True)

    # (nom affiché, fourchette gwp) ; longue traîne regroupée en « autres ».
    data: list[tuple[str, list[float]]] = []
    if len(ranked) > _TOP_N + 1:
        for name, vals in ranked[:_TOP_N]:
            data.append((_disp(name, group_by), vals["gwp"]))
        tail = ranked[_TOP_N:]
        tmin = sum(v["gwp"][0] for _, v in tail)
        tmax = sum(v["gwp"][1] for _, v in tail)
        data.append((f"autres ({len(tail)} {noun}s)", [tmin, tmax]))
    else:
        for name, vals in ranked:
            data.append((_disp(name, group_by), vals["gwp"]))

    values = [_central(g[0], g[1], factor) for _, g in data]
    name_w = max((len(n) for n, _ in data), default=len("TOTAL"))
    val_w = max((len(v) for v in values), default=0)

    out = [f"Impact par {noun} — trié par GWP ({unit_label}) · valeur centrale (~)", ""]
    for (name, gwp), val in zip(data, values):
        share = _mid(gwp) / total_mid
        filled = min(_BAR_WIDTH, round(share * _BAR_WIDTH))
        bar = "█" * filled + " " * (_BAR_WIDTH - filled)
        out.append(f"  {name.ljust(name_w)}  {val.rjust(val_w)}  {bar}  {round(share * 100):>3d}%")

    out.append("  " + "─" * (name_w + val_w + _BAR_WIDTH + 10))
    total_val = _central(totals["gwp"][0], totals["gwp"][1], factor)
    out.append(f"  {'TOTAL'.ljust(name_w)}  {total_val.rjust(val_w)}")
    return out


def _disp(name: str, group_by: str) -> str:
    return _short_model(name) if group_by == "model" else name


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

    units = {c: _scale(totals[c][1] or 1.0, c) for c in CRITERIA}

    lines: list[str] = []
    if group_by != "total" and groups:
        lines += _bar_chart(groups, totals, group_by, units["gwp"])
        lines.append("")

    # Section détaillée : les 5 critères du total, valeur centrale + plage min–max.
    label_w = max(len(_NAME[c]) for c in _SUMMARY_ORDER)
    centrals = {c: f"{_central(totals[c][0], totals[c][1], units[c][0])} {units[c][1]}"
                for c in _SUMMARY_ORDER}
    central_w = max(len(v) for v in centrals.values())
    lines.append("Impact total (valeur centrale ~ · détail min–max) :")
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
