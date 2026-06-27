def render_statusline(rows: list[dict]) -> str:
    if not rows:
        return ""
    e_min = sum(r["energy_min"] for r in rows)
    e_max = sum(r["energy_max"] for r in rows)
    g_min = sum(r["gwp_min"] for r in rows)
    g_max = sum(r["gwp_max"] for r in rows)
    return f"⚡ {e_min:.3g}–{e_max:.3g} kWh · 🌍 {g_min:.3g}–{g_max:.3g} kgCO2e"
