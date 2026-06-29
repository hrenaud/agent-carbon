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
  active_seconds REAL DEFAULT 0,
  client TEXT DEFAULT '',
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
CREATE TABLE IF NOT EXISTS pending_models (
  provider TEXT, model TEXT, first_seen TEXT, occurrences INTEGER DEFAULT 0,
  PRIMARY KEY (provider, model)
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
        # Migrations : colonnes ajoutées après coup sur une DB pré-existante.
        for ddl in (
            "ALTER TABLE events ADD COLUMN active_seconds REAL DEFAULT 0",
            "ALTER TABLE events ADD COLUMN client TEXT DEFAULT ''",
        ):
            try:
                self.conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente
        self.conn.commit()

    def import_legacy(self, carbon_db_path: str):
        raise NotImplementedError("backfill carbon.db pas encore implémenté")

    def ingest(self, events: Iterable[InferenceEvent],
               engine: EcoLogitsEngine, config: Config) -> int:
        new_count = 0
        for e in events:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (e.session_id, e.msg_id, e.provider, e.model,
                 e.input_tokens, e.output_tokens,
                 e.cache_creation_tokens, e.cache_read_tokens,
                 e.timestamp, e.project, e.active_seconds, e.client),
            )
            if cur.rowcount == 0:
                # déjà ingéré → idempotent ; on backfille juste les colonnes
                # ajoutées après coup (active_seconds, client) sans recalculer l'impact.
                self.conn.execute(
                    "UPDATE events SET active_seconds=? "
                    "WHERE session_id=? AND msg_id=? AND active_seconds=0",
                    (e.active_seconds, e.session_id, e.msg_id),
                )
                self.conn.execute(
                    "UPDATE events SET client=? "
                    "WHERE session_id=? AND msg_id=? AND client=''",
                    (e.client, e.session_id, e.msg_id),
                )
                continue
            new_count += 1
            rec = engine.compute(e, config)
            self._store_impact(e, rec)
            if rec.error == "model-params-unresolved":
                self.add_pending(e.provider, e.model, e.timestamp)
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

    def add_pending(self, provider: str, model: str, ts: str) -> None:
        self.conn.execute(
            "INSERT INTO pending_models (provider, model, first_seen, occurrences) "
            "VALUES (?,?,?,1) "
            "ON CONFLICT(provider, model) DO UPDATE SET occurrences = occurrences + 1",
            (provider, model, ts),
        )
        self.conn.commit()

    def list_pending(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT provider, model, first_seen, occurrences "
            "FROM pending_models ORDER BY occurrences DESC").fetchall()]

    def clear_pending(self, provider: str, model: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_models WHERE provider=? AND model=?",
            (provider, model))
        self.conn.commit()

    def rows_for_report(self, since: str | None = None,
                        session_id: str | None = None) -> list[dict]:
        sql = (
            "SELECT e.model, e.project, e.timestamp, e.client, "
            "i.energy_min, i.energy_max, i.gwp_min, i.gwp_max, "
            "i.adpe_min, i.adpe_max, i.pe_min, i.pe_max, i.wcf_min, i.wcf_max "
            "FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NULL"
        )
        params: list = []
        if since:
            sql += " AND e.timestamp >= ?"
            params.append(since)
        if session_id:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def intensity_by_model(self) -> list[dict]:
        """Par modèle, sur les seuls messages à temps actif mesuré (>0) et
        impact estimé : heures actives, tokens de sortie, et valeur centrale
        des 5 critères. Permet de calculer tok/h et impact/h."""
        sql = (
            "SELECT e.model AS model, SUM(e.active_seconds) AS sec, "
            "SUM(e.output_tokens) AS toks, "
            "SUM(i.energy_min) AS emin, SUM(i.energy_max) AS emax, "
            "SUM(i.gwp_min) AS gmin, SUM(i.gwp_max) AS gmax, "
            "SUM(i.adpe_min) AS amin, SUM(i.adpe_max) AS amax, "
            "SUM(i.pe_min) AS pmin, SUM(i.pe_max) AS pmax, "
            "SUM(i.wcf_min) AS wmin, SUM(i.wcf_max) AS wmax "
            "FROM events e JOIN impacts i "
            "ON e.session_id=i.session_id AND e.msg_id=i.msg_id "
            "WHERE i.error IS NULL AND e.active_seconds > 0 "
            "GROUP BY e.model"
        )
        out = []
        for r in self.conn.execute(sql):
            hours = (r["sec"] or 0) / 3600.0
            if hours <= 0:
                continue
            out.append({
                "model": r["model"], "hours": hours, "tokens": r["toks"],
                "energy": (r["emin"] + r["emax"]) / 2,
                "gwp": (r["gmin"] + r["gmax"]) / 2,
                "adpe": (r["amin"] + r["amax"]) / 2,
                "pe": (r["pmin"] + r["pmax"]) / 2,
                "wcf": (r["wmin"] + r["wmax"]) / 2,
            })
        return out

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
