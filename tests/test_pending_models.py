from agent_carbon.store.db import SQLiteStore


def test_add_and_list_pending(tmp_path):
    s = SQLiteStore(str(tmp_path / "c.db"))
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T10:00:00Z")
    s.add_pending("ollama", "qwen2.5:7b", "2026-06-29T11:00:00Z")
    rows = s.list_pending()
    assert len(rows) == 1
    assert rows[0]["provider"] == "ollama"
    assert rows[0]["occurrences"] == 2
    assert rows[0]["first_seen"] == "2026-06-29T10:00:00Z"


def test_clear_pending(tmp_path):
    s = SQLiteStore(str(tmp_path / "c.db"))
    s.add_pending("ollama", "m", "2026-06-29T10:00:00Z")
    s.clear_pending("ollama", "m")
    assert s.list_pending() == []
