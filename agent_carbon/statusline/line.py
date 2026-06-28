def render_statusline(rows: list[dict]) -> str:
    if not rows:
        return ""
    e_min = sum(r["energy_min"] for r in rows)
    e_max = sum(r["energy_max"] for r in rows)
    g_min = sum(r["gwp_min"] for r in rows)
    g_max = sum(r["gwp_max"] for r in rows)
    w_min = sum(r["wcf_min"] for r in rows)
    w_max = sum(r["wcf_max"] for r in rows)
    return (
        f"🌍 {g_min:.3g}–{g_max:.3g} kgCO2eq · "
        f"💧 {w_min:.3g}–{w_max:.3g} L · "
        f"⚡ {e_min:.3g}–{e_max:.3g} kWh"
    )
