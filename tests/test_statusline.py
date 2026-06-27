from agent_carbon.statusline.line import render_statusline


def test_compact_line_sums_energy_and_gwp():
    rows = [
        {"energy_min": 0.1, "energy_max": 0.2, "gwp_min": 1.0, "gwp_max": 2.0},
        {"energy_min": 0.05, "energy_max": 0.1, "gwp_min": 0.5, "gwp_max": 1.0},
    ]
    line = render_statusline(rows)
    assert "kWh" in line and "kgCO2e" in line
    assert "0.15" in line  # énergie min sommée


def test_empty_when_no_rows():
    assert render_statusline([]) == ""
