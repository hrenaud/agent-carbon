from pathlib import Path
from agent_carbon.__main__ import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_then_report(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    rc = main(["ingest", "--source", str(FIXTURES), "--db", db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 events" in out  # sample.jsonl (2) + active.jsonl (1)

    rc = main(["report", "--db", db, "--by", "model"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "opus-4-8" in out  # nom raccourci dans le tableau
    assert "GWP" in out


def test_ingest_is_idempotent_via_cli(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    capsys.readouterr()
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    assert "0 events" in capsys.readouterr().out


def test_statusline_runs(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    capsys.readouterr()
    rc = main(["statusline", "--db", db])
    assert rc == 0
    assert "kWh" in capsys.readouterr().out
