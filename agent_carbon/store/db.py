import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from agent_carbon.config import Config
from agent_carbon.impact.engine import CRITERIA, EcoLogitsEngine
from agent_carbon.models import InferenceEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  session_id TEXT, msg_id TEXT, provider TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  cache_creation_tokens INTEGER, cache_read_tokens INTEGER,
  timestamp TEXT, project TEXT,
  PRIMARY KEY (session_id, msg_id)
);
CREATE TABLE IF NOT EXISTS impacts (
  session_id TEXT, msg_id TEXT, model_resolved TEXT, zone TEXT,
  methodology_version TEXT,
  energy_min REAL, energy_max REAL, gwp_min REAL, gwp_max REAL,
  adpe_min REAL, adpe_max REAL, pe_min REAL, pe_max REAL,
  wcf_min REAL, wcf_max REAL,
  breakdown_json TEXT, warnings TEXT, error TEXT,
  PRIMARY KEY (session_id, msg_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, project TEXT, started_at TEXT, ended_at TEXT
);
"""


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class SQLiteStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def import_legacy(self, carbon_db_path: str):
        raise NotImplementedError("backfill carbon.db pas encore implémenté")

    def ingest(self, events: Iterable[InferenceEvent],
               engine: EcoLogitsEngine, config: Config) -> int:
        new_count = 0
        for e in events:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                (e.session_id, e.msg_id, e.provider, e.model,
                 e.input_tokens, e.output_tokens,
                 e.cache_creation_tokens, e.cache_read_tokens,
                 e.timestamp, e.project),
            )
            if cur.rowcount == 0:
                continue  # déjà ingéré → idempotent
            new_count += 1
            self._store_impact(e, engine.compute(e, config))
            self._touch_session(e)
        self.conn.commit()
        return new_count

    def _store_impact(self, e: InferenceEvent, rec) -> None:
        def mm(crit):
            return rec.totals.get(crit, (None, None))
        self.conn.execute(
            "INSERT OR REPLACE INTO impacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.session_id, e.msg_id, rec.model_resolved, rec.zone,
             rec.methodology_version,
             *mm("energy"), *mm("gwp"), *mm("adpe"), *mm("pe"), *mm("wcf"),
             json.dumps({"usage": rec.usage, "embodied": rec.embodied}),
             json.dumps(rec.warnings), rec.error),
        )

    def _touch_session(self, e: InferenceEvent) -> None:
        row = self.conn.execute(
            "SELECT started_at, ended_at FROM sessions WHERE session_id=?",
            (e.session_id,),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (e.session_id, e.project, e.timestamp, e.timestamp),
            )
            return
        started = min(row["started_at"], e.timestamp)
        ended = max(row["ended_at"], e.timestamp)
        self.conn.execute(
            "UPDATE sessions SET started_at=?, ended_at=? WHERE session_id=?",
            (started, ended, e.session_id),
        )

    def rows_for_report(self, since: str | None) -> list[dict]:
        sql = (
            "SELECT e.model, e.project, e.timestamp, "
            "i.energy_min, i.energy_max, i.gwp_min, i.gwp_max, "
            "i.adpe_min, i.adpe_max, i.pe_min, i.pe_max, i.wcf_min, i.wcf_max "
            "FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NULL"
        )
        params: tuple = ()
        if since:
            sql += " AND e.timestamp >= ?"
            params = (since,)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def coverage(self) -> dict:
        """Couverture de mesure : total, mesurés (impact estimé), non couverts
        (modèle non modélisé par EcoLogits → event conservé, impact non estimé)."""
        total = self.conn.execute("SELECT COUNT(*) FROM impacts").fetchone()[0]
        uncovered = self.conn.execute(
            "SELECT COUNT(*) FROM impacts WHERE error IS NOT NULL"
        ).fetchone()[0]
        return {"total": total, "measured": total - uncovered, "uncovered": uncovered}

    def session_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def total_duration_seconds(self) -> float:
        total = 0.0
        for r in self.conn.execute("SELECT started_at, ended_at FROM sessions"):
            a, b = _parse_ts(r["started_at"]), _parse_ts(r["ended_at"])
            if a and b:
                total += (b - a).total_seconds()
        return total
