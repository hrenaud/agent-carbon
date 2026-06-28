from agent_carbon.report.cli import render_report


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
    out = render_report(ROWS, group_by="total")
    # GWP total 1.5–3.0 → valeur centrale ~2.25 ET la plage 1.5–3 dans la même section
    assert "~2.25" in out
    assert "1.5–3" in out


def test_group_by_model_lists_each_model():
    out = render_report(ROWS, group_by="model")
    assert "opus-4-8" in out
    assert "sonnet-4-6" in out


def test_group_by_project_aggregates():
    out = render_report(ROWS, group_by="project")
    assert "projA" in out
    assert out.count("projA") == 1


def test_rows_sorted_descending_by_gwp():
    out = render_report(ROWS, group_by="model")
    assert out.index("opus-4-8") < out.index("sonnet-4-6")


def test_bar_and_percent_rendered():
    out = render_report(ROWS, group_by="model")
    assert "█" in out and "%" in out


def test_long_tail_collapsed_into_autres():
    rows = [
        {"model": f"claude-m{i:02d}", "project": f"p{i:02d}",
         "gwp_min": 0.1 * (i + 1), "gwp_max": 0.2 * (i + 1),
         "energy_min": 0.1, "energy_max": 0.2, "adpe_min": 1e-6, "adpe_max": 2e-6,
         "pe_min": 0.1, "pe_max": 0.2, "wcf_min": 0.1, "wcf_max": 0.2}
        for i in range(12)
    ]
    out = render_report(rows, group_by="project")
    assert "autres" in out


def test_icon_summary_section_present():
    out = render_report(ROWS, group_by="model")
    for icon in ("⚡", "🌍", "💧", "⛏", "🔥"):
        assert icon in out
    assert "Impact total" in out
    assert "~2.25" in out  # GWP central


def test_model_names_shortened_in_table():
    out = render_report(ROWS, group_by="model")
    table = out.split("Impact total")[0]
    assert "claude-" not in table


def test_tiny_values_scaled_to_readable_units():
    rows = [{"model": "m", "project": "p",
             "energy_min": 19.0, "energy_max": 33.0,
             "gwp_min": 8.0, "gwp_max": 13.0,
             "adpe_min": 4.0e-5, "adpe_max": 4.16e-5,
             "pe_min": 192.0, "pe_max": 335.0,
             "wcf_min": 61.0, "wcf_max": 135.0}]
    out = render_report(rows, group_by="total")
    # la plage ADPe doit être en mg, pas en 4e-05
    assert "mgSbeq" in out
    assert "4e-05" not in out
    assert "40" in out and "41.6" in out


def test_negligible_collapses_to_approx_zero():
    rows = [
        {"model": "claude-opus-4-8", "project": "p",
         "gwp_min": 8.0, "gwp_max": 13.0, "energy_min": 19.0, "energy_max": 33.0,
         "adpe_min": 4e-5, "adpe_max": 4.1e-5, "pe_min": 192.0, "pe_max": 335.0,
         "wcf_min": 61.0, "wcf_max": 135.0},
        {"model": "claude-opus-4-6", "project": "p",
         "gwp_min": 2.8e-5, "gwp_max": 5e-5, "energy_min": 6e-5, "energy_max": 1e-4,
         "adpe_min": 1.5e-10, "adpe_max": 1.6e-10, "pe_min": 6e-4, "pe_max": 1e-3,
         "wcf_min": 2e-4, "wcf_max": 5e-4},
    ]
    out = render_report(rows, group_by="model")
    assert "≈0" in out
