from agent_carbon.report.cli import render_intensity, render_projects, render_report


ROWS = [
    {"model": "claude-opus-4-8", "project": "projA",
     "gwp_min": 1.0, "gwp_max": 2.0, "energy_min": 0.1, "energy_max": 0.2,
     "adpe_min": 1e-9, "adpe_max": 2e-9, "pe_min": 0.3, "pe_max": 0.6,
     "wcf_min": 0.01, "wcf_max": 0.02},
    {"model": "claude-sonnet-4-6", "project": "projA",
     "gwp_min": 0.5, "gwp_max": 1.0, "energy_min": 0.05, "energy_max": 0.1,
     "adpe_min": 1e-9, "adpe_max": 1e-9, "pe_min": 0.1, "pe_max": 0.2,
     "wcf_min": 0.005, "wcf_max": 0.01},
]


def test_report_shows_central_and_range_in_one_section():
    out = render_report(ROWS)
    # GWP total 1.5–3.0 → valeur centrale ~2.25 ET la plage 1.5–3 dans la même section
    assert "~2.25" in out
    assert "1.5–3" in out


def test_report_lists_five_criteria_with_icons():
    out = render_report(ROWS)
    for icon in ("⚡", "🌍", "💧", "⛏", "🔥"):
        assert icon in out
    assert "Impact total" in out


def test_report_criteria_in_requested_order():
    out = render_report(ROWS)
    # ordre demandé : GWP, Eau (wcf), ADPe, Énergie, PE
    order = [out.index(lbl) for lbl in ("GWP", "Eau", "ADPe", "Énergie", "PE")]
    assert order == sorted(order)


def test_tiny_values_scaled_to_readable_units():
    rows = [{"model": "m", "project": "p",
             "energy_min": 19.0, "energy_max": 33.0,
             "gwp_min": 8.0, "gwp_max": 13.0,
             "adpe_min": 4.0e-5, "adpe_max": 4.16e-5,
             "pe_min": 192.0, "pe_max": 335.0,
             "wcf_min": 61.0, "wcf_max": 135.0}]
    out = render_report(rows)
    # la plage ADPe doit être en mg, pas en 4e-05
    assert "mgSbeq" in out
    assert "4e-05" not in out
    assert "40" in out and "41.6" in out


def test_render_intensity_aligned_table_one_line_per_model():
    rows = [
        {"model": "claude-opus-4-8", "hours": 1.0, "tokens": 566000,
         "energy": 5.0, "gwp": 1.07, "adpe": 5e-6, "pe": 50.0, "wcf": 9.0},
        {"model": "claude-haiku-4-5", "hours": 1.0, "tokens": 276000,
         "energy": 1.0, "gwp": 0.014, "adpe": 1e-6, "pe": 10.0, "wcf": 2.0},
    ]
    out = render_intensity(rows)
    assert "tok/h" in out
    assert "modèle" in out                  # ligne d'en-tête du tableau
    for icon in ("🌍", "⚡", "💧", "⛏", "🔥"):
        assert icon in out
    # une seule ligne par modèle : nom + tok/h + GWP sur la même ligne
    opus_line = next(l for l in out.splitlines() if "opus-4-8" in l)
    assert "tok/h" not in opus_line          # « tok/h » n'est que dans l'en-tête
    assert "kgCO2eq" in opus_line and "~566k" in opus_line
    # trié par tok/h décroissant : opus (566k) avant haiku (276k)
    assert out.index("opus-4-8") < out.index("haiku-4-5")


def test_render_intensity_fixed_unit_per_cell_is_readable():
    # GWP opus ~1.07 kg vs haiku ~0.014 kg → unités lisibles par cellule
    rows = [
        {"model": "claude-opus-4-8", "hours": 1.0, "tokens": 566000,
         "energy": 5.0, "gwp": 1.07, "adpe": 5e-6, "pe": 50.0, "wcf": 9.0},
        {"model": "claude-haiku-4-5", "hours": 1.0, "tokens": 276000,
         "energy": 1.0, "gwp": 0.014, "adpe": 1e-6, "pe": 10.0, "wcf": 2.0},
    ]
    out = render_intensity(rows)
    haiku_line = next(l for l in out.splitlines() if "haiku-4-5" in l)
    assert "gCO2eq" in haiku_line            # 0.014 kg → 14 gCO2eq, pas « 0.014 »
    assert "0.014" not in haiku_line


def test_render_intensity_empty():
    assert render_intensity([]) == ""


def _proj_rows(specs):
    """specs: liste de (projet, gwp_min, gwp_max) → rows minimaux pour le rapport."""
    return [{"project": p, "gwp_min": lo, "gwp_max": hi} for p, lo, hi in specs]


def test_render_projects_ranks_most_impactful_first():
    rows = _proj_rows([("projA", 1.0, 2.0), ("projB", 5.0, 7.0), ("projC", 0.1, 0.2)])
    out = render_projects(rows)
    assert "Projets les plus impactants" in out
    assert "█" in out
    # trié par GWP décroissant : projB (6) > projA (1.5) > projC (0.15)
    assert out.index("projB") < out.index("projA") < out.index("projC")


def test_render_projects_top_n_groups_remainder():
    rows = _proj_rows([(f"p{i}", float(i), float(i)) for i in range(1, 9)])  # 8 projets
    out = render_projects(rows)
    # top 5 par défaut, les 3 plus petits regroupés
    assert "autres (3 projets)" in out
    assert "p1" not in out  # les plus petits sont dans « autres »


def test_render_projects_show_all_lists_every_project():
    rows = _proj_rows([(f"p{i}", float(i), float(i)) for i in range(1, 9)])
    out = render_projects(rows, show_all=True)
    assert "autres" not in out
    for i in range(1, 9):
        assert f"p{i}" in out


def test_render_projects_empty():
    assert render_projects([]) == ""
