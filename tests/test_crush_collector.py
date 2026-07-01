import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from agent_carbon.collectors.crush import CrushCollector
from agent_carbon.models import InferenceEvent

FIXTURES = Path(__file__).parent / "fixtures"
CRUSH_EXPORT = FIXTURES / "crush-export.json"


# --- JSON export mode ---

def test_parses_only_assistant_messages():
    """Les messages user ne sont pas produits. Seuls les assistant le sont."""
    events = list(CrushCollector(str(CRUSH_EXPORT)).collect())
    assert len(events) == 2  # 2 messages assistant dans le fixture


def test_event_fields_mapped_from_crush_structure():
    """Les champs InferenceEvent sont correctement mappés depuis la structure JSON."""
    events = {e.msg_id: e for e in CrushCollector(str(CRUSH_EXPORT)).collect()}
    e = events["msg-1"]
    assert isinstance(e, InferenceEvent)
    assert e.provider == "anthropic"
    assert e.model == "claude-sonnet"
    assert e.input_tokens == 8427
    assert e.output_tokens == 287
    assert e.cache_creation_tokens == 7052
    assert e.cache_read_tokens == 8020
    assert e.project == "projA"  # basename de directory
    assert e.session_id == "sess-GH123"
    assert e.client == "opencode"


def test_active_seconds_calculated_from_delta():
    """Le temps actif est le delta entre created et completed, tronqué à 300s."""
    events = list(CrushCollector(str(CRUSH_EXPORT)).collect())
    e = events[0]  # msg-1: delta = (1719741630000 - 1719741600000)/1000 = 30s
    assert abs(e.active_seconds - 30.0) < 0.01


def test_timestamp_converted_to_iso8601():
    """Le timestamp millésime est converti en ISO 8601 UTC."""
    events = list(CrushCollector(str(CRUSH_EXPORT)).collect())
    e = events[0]
    # 1719741600000 ms → 2024-06-30T10:00:00+00:00
    assert e.timestamp.startswith("2024-06-30")
    assert "+00:00" in e.timestamp


def test_ignores_user_messages_and_empty_files():
    """Les messages user ne sont PAS produits. Les fichiers vides ne produisent rien."""
    fd, vide = tempfile.mkstemp(suffix=".json")
    os.write(fd, b"")
    os.close(fd)

    events = list(CrushCollector(vide).collect())
    assert events == []  # fichier vide → 0 events
    os.unlink(vide)

    fd, malformé = tempfile.mkstemp(suffix=".json")
    os.write(fd, b"not json {{{")
    os.close(fd)

    events = list(CrushCollector(malformé).collect())
    assert events == []  # JSON invalide → 0 events (ignore silencieusement)
    os.unlink(malformé)


def test_collect_from_directory_recursive():
    """Le collecteur trouve les exports JSON récursivement dans un répertoire."""
    tmp_dir = tempfile.mkdtemp()
    sub = os.path.join(tmp_dir, "sub")
    os.makedirs(sub)

    export1 = os.path.join(tmp_dir, "export1.json")
    export2 = os.path.join(sub, "export2.json")

    _write_json(export1, _make_crush_data(["msg-a"], directory=tmp_dir))
    _write_json(export2, _make_crush_data(["msg-b"], directory=sub))

    events = list(CrushCollector(tmp_dir).collect())
    assert len(events) == 2
    msg_ids = {e.msg_id for e in events}
    assert "msg-a" in msg_ids
    assert "msg-b" in msg_ids

    for p in (export1, export2):
        os.unlink(p)
    os.rmdir(sub)
    os.rmdir(tmp_dir)


def test_active_seconds_capped_at_300():
    """Les deltas > 300s sont tronqués à 0 (pas de hits lents)."""
    fd, f = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    data = {
        "info": {"id": "s1", "time": {"created": 0}},
        "directory": "/tmp/proj",
        "messages": [
            {
                "data": {
                    "id": "m1",
                    "role": "assistant",
                    "model": {"providerID": "anthropic", "modelID": "x"},
                    "tokens": {"input": 100, "output": 50, "cache": {"read": 0, "write": 0}},
                    "time": {"created": 0, "completed": 400_000},  # 400s > 300s
                }
            }
        ],
    }
    with open(f, "w") as fh:
        json.dump(data, fh)

    events = list(CrushCollector(f).collect())
    assert len(events) == 1
    assert events[0].active_seconds == 0.0  # tronqué car > 300s
    os.unlink(f)


def test_active_seconds_zero_or_negative_ignored():
    """Les deltas <= 0 sont ignorés."""
    fd, f = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    data = {
        "info": {"id": "s1", "time": {"created": 0}},
        "directory": "/tmp/proj",
        "messages": [
            {
                "data": {
                    "id": "m1",
                    "role": "assistant",
                    "model": {"providerID": "anthropic", "modelID": "x"},
                    "tokens": {"input": 100, "output": 50, "cache": {"read": 0, "write": 0}},
                    "time": {"created": 1000, "completed": 500},  # delta négatif
                }
            }
        ],
    }
    with open(f, "w") as fh:
        json.dump(data, fh)

    events = list(CrushCollector(f).collect())
    assert events[0].active_seconds == 0.0
    os.unlink(f)


def test_missing_optional_fields_use_defaults():
    """Les champs optionnels absents utilisent 0 ou ''."""
    fd, f = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    data = {
        "directory": "/tmp/proj",
        "messages": [
            {"data": {"id": "m1", "role": "assistant"}}
        ],
    }
    with open(f, "w") as fh:
        json.dump(data, fh)

    events = list(CrushCollector(f).collect())
    assert len(events) == 1
    e = events[0]
    assert e.provider == ""
    assert e.model == ""
    assert e.input_tokens == 0
    assert e.output_tokens == 0
    assert e.cache_read_tokens == 0
    assert e.cache_creation_tokens == 0
    assert e.session_id == ""
    os.unlink(f)


def test_data_vs_info_keys():
    """Le collecteur accepte les messages avec clés 'data' ou 'info'."""
    fd, f = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    data = {
        "info": {"id": "s1"},
        "directory": "/tmp/proj",
        "messages": [
            {
                "data": {
                    "id": "m1",
                    "role": "assistant",
                    "model": {"providerID": "p", "modelID": "m"},
                    "tokens": {"input": 10, "output": 5, "cache": {"read": 0, "write": 0}},
                }
            },
            {
                "info": {  # clé alternative
                    "id": "m2",
                    "role": "assistant",
                    "model": {"providerID": "p2", "modelID": "m2"},
                    "tokens": {"input": 20, "output": 10, "cache": {"read": 0, "write": 0}},
                }
            },
        ],
    }
    with open(f, "w") as fh:
        json.dump(data, fh)

    events = list(CrushCollector(f).collect())
    assert len(events) == 2
    os.unlink(f)


# --- SQLite backfill mode ---

def test_backfill_from_sqlite():
    """Le mode backfill lit les sessions et messages depuis une DB SQLite."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (
            id TEXT, title TEXT, directory TEXT,
            model TEXT,
            tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER
        );
        CREATE TABLE message (
            id TEXT, session_id TEXT, data TEXT
        );
    """)

    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "sess-GH123", "Fix bug XYZ", "/Users/me/DEV/projA",
            json.dumps({"id": "claude-sonnet", "providerID": "anthropic"}),
            8427, 287, 8020, 7052,
            1719741600000, 1719742000000,
        ),
    )

    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        (
            "msg-1", "sess-GH123",
            json.dumps({
                "role": "assistant",
                "time": {"created": 1719741600000, "completed": 1719741630000},
                "model": {"id": "claude-sonnet", "providerID": "anthropic"},
                "tokens": {"input": 8427, "output": 287, "cache": {"read": 8020, "write": 7052}},
            }),
        ),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, InferenceEvent)
    assert e.provider == "anthropic"
    assert e.model == "claude-sonnet"
    assert e.input_tokens == 8427
    assert e.output_tokens == 287
    assert e.cache_creation_tokens == 7052
    assert e.cache_read_tokens == 8020
    assert e.session_id == "sess-GH123"
    assert e.project == "projA"
    assert e.client == "opencode"

    # Cleanup
    conn.close()
    os.unlink(db_path)
    os.rmdir(tmp_dir)


def test_backfill_ignores_user_messages():
    """Les messages user dans la DB ne sont pas produits."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (id TEXT, title TEXT, directory TEXT,
            model TEXT, tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, data TEXT);
    """)

    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t", "/x/proj",
         json.dumps({"providerID": "a", "id": "m"}),
         100, 50, 0, 0, 1000, 2000),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        ("mu", "s1", json.dumps({"role": "user", "content": "hello"})),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        ("ma", "s1", json.dumps({
            "role": "assistant",
            "model": {"providerID": "a", "id": "m"},
            "tokens": {"input": 100, "output": 50, "cache": {"read": 0, "write": 0}},
            "time": {"created": 1000, "completed": 1500},
        })),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert len(events) == 1
    assert events[0].msg_id == "ma"

    os.unlink(db_path)
    os.rmdir(tmp_dir)


def test_backfill_zero_message_tokens_not_overwritten_by_session():
    """Un token message explicitement à 0 doit être conservé, pas remplacé par
    le total de session (sinon sur-comptage)."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (id TEXT, title TEXT, directory TEXT,
            model TEXT, tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, data TEXT);
    """)
    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t", "/x/proj", json.dumps({"providerID": "a", "id": "m"}),
         999, 999, 999, 999, 1000, 2000),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        ("ma", "s1", json.dumps({
            "role": "assistant",
            "model": {"providerID": "a", "id": "m"},
            "tokens": {"input": 0, "output": 0, "cache": {"read": 0, "write": 0}},
            "time": {"created": 1000, "completed": 1500},
        })),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert len(events) == 1
    e = events[0]
    assert e.input_tokens == 0
    assert e.output_tokens == 0
    assert e.cache_read_tokens == 0
    assert e.cache_creation_tokens == 0

    os.unlink(db_path)
    os.rmdir(tmp_dir)


def test_backfill_missing_db_returns_empty():
    """Si la DB n'existe pas, le collecteur retourne []."""
    events = list(CrushCollector(backfill_db_path="/non/existent/path.db").collect())
    assert events == []


def test_backfill_no_messages_returns_empty():
    """Une session sans messages ne produit rien."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (id TEXT, title TEXT, directory TEXT,
            model TEXT, tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, data TEXT);
    """)
    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t", "/x/proj", json.dumps({}), 0, 0, 0, 0, 0, 0),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert events == []

    os.unlink(db_path)
    os.rmdir(tmp_dir)


def test_backfill_json_data_column_parsed():
    """La colonne data est un STRING JSON → json.loads est appelée."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (id TEXT, title TEXT, directory TEXT,
            model TEXT, tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, data TEXT);
    """)

    # data est stocké comme string JSON dans SQLite
    data_str = json.dumps({
        "role": "assistant",
        "model": {"providerID": "openai", "id": "gpt-4"},
        "tokens": {"input": 500, "output": 200, "cache": {"read": 100, "write": 50}},
        "time": {"created": 1000, "completed": 1200},
    })
    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t", "/x/proj",
         json.dumps({"providerID": "openai", "id": "gpt-4"}),
         500, 200, 100, 50, 1000, 1200),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        ("m1", "s1", data_str),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert len(events) == 1
    assert events[0].provider == "openai"
    assert events[0].model == "gpt-4"

    os.unlink(db_path)
    os.rmdir(tmp_dir)


def test_backfill_project_from_session_directory():
    """Le project est le basename du directory de la session."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (id TEXT, title TEXT, directory TEXT,
            model TEXT, tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, data TEXT);
    """)

    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t", "/Users/me/Projects/myProject",
         json.dumps({"providerID": "p", "id": "m"}),
         100, 50, 0, 0, 1000, 2000),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        ("m1", "s1", json.dumps({
            "role": "assistant",
            "model": {"providerID": "p", "id": "m"},
            "tokens": {"input": 100, "output": 50, "cache": {"read": 0, "write": 0}},
            "time": {"created": 1000, "completed": 1100},
        })),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert len(events) == 1
    assert events[0].project == "myProject"

    os.unlink(db_path)
    os.rmdir(tmp_dir)


def test_backfill_active_seconds_capped():
    """Les deltas > 300s sont tronqués à 0 dans le mode backfill."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = str(tmp_dir / "opencode.db")

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE session (id TEXT, title TEXT, directory TEXT,
            model TEXT, tokens_input INTEGER, tokens_output INTEGER,
            tokens_cache_read INTEGER, tokens_cache_write INTEGER,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, data TEXT);
    """)

    conn.execute(
        "INSERT INTO session (id, title, directory, model, "
        "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, "
        "time_created, time_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "t", "/x/proj", json.dumps({}), 0, 0, 0, 0, 0, 0),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
        ("m1", "s1", json.dumps({
            "role": "assistant",
            "model": {"providerID": "p", "id": "m"},
            "tokens": {"input": 100, "output": 50, "cache": {"read": 0, "write": 0}},
            "time": {"created": 0, "completed": 500_000},  # 500s > 300s
        })),
    )
    conn.commit()
    conn.close()

    events = list(CrushCollector(backfill_db_path=db_path).collect())
    assert events[0].active_seconds == 0.0  # tronqué

    os.unlink(db_path)
    os.rmdir(tmp_dir)


# --- Helpers ---

def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_crush_data(msg_ids: list[str], *, directory: str = "/tmp/proj", role: str = "assistant") -> dict:
    messages = []
    for mid in msg_ids:
        messages.append({
            "data": {
                "id": mid,
                "role": role,
                "model": {"providerID": "anthropic", "modelID": "claude-sonnet"},
                "tokens": {"input": 100, "output": 50, "cache": {"read": 0, "write": 0}},
                "time": {"created": 1000, "completed": 1100},
            }
        })
    return {
        "info": {"id": "sess1"},
        "directory": directory,
        "messages": messages,
    }
