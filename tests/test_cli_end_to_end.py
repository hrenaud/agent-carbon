from pathlib import Path
from agent_carbon.__main__ import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_then_report(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    rc = main(["ingest", "--source", str(FIXTURES), "--db", db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 events" in out  # sample.jsonl (2) + active.jsonl (1)

    rc = main(["report", "--db", db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "opus-4-8" in out  # présent dans la section Intensité
    assert "GWP" in out


def test_report_detail_flag_shows_minmax(tmp_path, capsys):
    db = str(tmp_path / "carbon.db")
    main(["ingest", "--source", str(FIXTURES), "--db", db])
    capsys.readouterr()
    # vue compacte par défaut : titres « (~ central) »
    main(["report", "--db", db])
    assert "(~ central)" in capsys.readouterr().out
    # --detail et son alias --detailed basculent les tableaux par modèle en min–max
    for flag in ("--detail", "--detailed"):
        rc = main(["report", "--db", db, flag])
        assert rc == 0
        out = capsys.readouterr().out
        assert "(min–max)" in out
        assert "(~ central)" not in out


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
