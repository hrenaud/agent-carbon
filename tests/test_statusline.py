import json
import sys
from pathlib import Path

from agent_carbon.__main__ import _read_stdin_json, main
from agent_carbon.statusline.line import render_statusline
from agent_carbon.store.db import SQLiteStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_compact_line_sums_energy_gwp_and_water():
    rows = [
        {"energy_min": 0.1, "energy_max": 0.2, "gwp_min": 1.0, "gwp_max": 2.0,
         "wcf_min": 3.0, "wcf_max": 4.0},
        {"energy_min": 0.05, "energy_max": 0.1, "gwp_min": 0.5, "gwp_max": 1.0,
         "wcf_min": 1.0, "wcf_max": 2.0},
    ]
    line = render_statusline(rows)
    assert "kWh" in line and "kgCO2eq" in line and "L" in line
    assert "0.15" in line  # énergie min sommée
    assert "4" in line and "6" in line  # eau : min 4.0, max 6.0 sommés
    # ordre demandé : GWP (🌍), Eau (💧), Énergie (⚡)
    assert line.index("🌍") < line.index("💧") < line.index("⚡")


def test_empty_when_no_rows():
    assert render_statusline([]) == ""


class _FakeStdin:
    def __init__(self, text: str):
        self._text = text

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        return self._text


def test_read_stdin_json_variants(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin('{"session_id": "x"}'))
    assert _read_stdin_json() == {"session_id": "x"}
    monkeypatch.setattr(sys, "stdin", _FakeStdin("   "))
    assert _read_stdin_json() is None
    monkeypatch.setattr(sys, "stdin", _FakeStdin("pas du json"))
    assert _read_stdin_json() is None


def test_statusline_scopes_to_current_session(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "c.db")
    fixture = str(FIXTURES / "sample.jsonl")  # contient sess-A (opus) et sess-B (sonnet)
    payload = json.dumps({"session_id": "sess-A", "transcript_path": fixture})
    monkeypatch.setattr(sys, "stdin", _FakeStdin(payload))

    rc = main(["statusline", "--db", db])
    assert rc == 0
    session_line = capsys.readouterr().out.strip()
    assert "kWh" in session_line

    # la ligne de session (sess-A seule) doit différer du total global (A + B)
    store = SQLiteStore(db)
    global_line = render_statusline(store.rows_for_report())
    assert session_line != global_line
