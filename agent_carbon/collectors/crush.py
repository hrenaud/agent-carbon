"""Collecteur pour les donnees d'exportation JSON d'Opencode/Crush et backfill SQLite."""

import glob
import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone

from agent_carbon.collectors.base import Collector
from agent_carbon.collectors.claude_code import (
    _project_from_cwd,
    _ACTIVE_CAP_SECONDS,
)
from agent_carbon.models import InferenceEvent


def _parse_ts_utc_ms(ms: int | float | None) -> str | None:
    """Convertit un timestamp Unix en ms en ISO 8601 UTC."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _safe_int(value: int | float | None) -> int:
    """Convertit une valeur en int, avec fallback 0 si None ou absente."""
    if value is None:
        return 0
    return int(value)


def _coalesce(primary, fallback):
    """Retourne `primary` s'il est présent (pas None), sinon `fallback`. Un 0
    explicite côté message est conservé — contrairement à `or`, qui le remplacerait
    par le total de session (sur-comptage)."""
    return primary if primary is not None else fallback


class CrushCollector(Collector):
    """Collecteur des exportations JSON d'Opencode/Crush.

    Supporte 2 modes :
    - Mode export JSON : lit les fichiers `*.json` dans `root` (glob récursif).
    - Mode backfill SQLite : lit les sessions et messages depuis une base SQLite.
    """

    provider: str = ""  # Chaque event porte son propre provider
    client: str = "opencode"

    def __init__(self, root: str | None = None, *, backfill_db_path: str | None = None):
        self.root: str = os.path.expanduser(root) if root else ""
        self.backfill_db_path: str | None = backfill_db_path

    def collect(self) -> Iterator[InferenceEvent]:
        if self.backfill_db_path:
            yield from self._backfill_from_db(self.backfill_db_path)
            return

        if not self.root:
            return

        # `root` peut être un fichier unique (export d'une session) ou un répertoire
        # (tous les exports d'un dossier).
        if os.path.isfile(self.root):
            yield from self._parse_export(self.root)
            return

        pattern = os.path.join(self.root, "**", "*.json")
        for path in glob.glob(pattern, recursive=True):
            yield from self._parse_export(path)

    def _parse_export(self, path: str) -> Iterator[InferenceEvent]:
        """Parse un export JSON d'Opencode/Crush en InferenceEvent.
        Seuls les messages 'assistant' sont produits.
        """
        with open(path, encoding="utf-8") as fh:
            try:
                obj = json.load(fh)
            except (json.JSONDecodeError, OSError):
                return

        messages = obj.get("messages")
        if not isinstance(messages, list):
            return

        for msg in messages:
            info = msg.get("data") or msg.get("info")
            if not isinstance(info, dict):
                continue

            if info.get("role") != "assistant":
                continue

            # Modèle avec provider
            raw_model = info.get("model") or {}
            provider = raw_model.get("providerID") or ""
            model = raw_model.get("modelID") or raw_model.get("id") or ""

            # Tokens
            raw_tokens = info.get("tokens") or {}
            input_tokens = _safe_int(raw_tokens.get("input"))
            output_tokens = _safe_int(raw_tokens.get("output"))
            cache_read_tokens = _safe_int(raw_tokens.get("cache", {}).get("read"))
            cache_creation_tokens = _safe_int(raw_tokens.get("cache", {}).get("write"))

            # Timestamp
            ts_ms = info.get("time", {}).get("created")
            timestamp = _parse_ts_utc_ms(ts_ms)

            # Session
            session_id = info.get("session_id") or info.get("ID") or ""
            if not session_id:
                session_id = obj.get("info", {}).get("id", "")

            # Project (basename du directory)
            directory = info.get("directory") or obj.get("directory") or ""
            project = _project_from_cwd(directory)

            # Msg ID
            msg_id = info.get("id") or ""

            # Active secondes (delta)
            created_ms = info.get("time", {}).get("created")
            completed_ms = info.get("time", {}).get("completed")
            active_seconds = self._calc_active_seconds(created_ms, completed_ms)

            yield InferenceEvent(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                timestamp=timestamp or "",
                project=project,
                session_id=session_id,
                msg_id=msg_id,
                active_seconds=active_seconds,
                client=self.client,
            )

    def _backfill_from_db(self, db_path: str) -> Iterator[InferenceEvent]:
        """Backfill depuis les tables SQLite d'Opencode/Crush.
        Lit les sessions et messages directement depuis la DB locale.
        Seuls les messages 'assistant' compatibles sont produits.
        """
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error:
            return

        # try/finally garantit la fermeture même si l'itération est interrompue
        # (exception en aval ou consommateur qui abandonne le générateur).
        try:
            yield from self._backfill_rows(conn)
        finally:
            conn.close()

    def _backfill_rows(self, conn: sqlite3.Connection) -> Iterator[InferenceEvent]:
        try:
            sessions = conn.execute("SELECT * FROM session").fetchall()
        except sqlite3.Error:
            return

        # Indexer les sessions par id pour lookup rapide
        session_map: dict[str, sqlite3.Row] = {}
        for session in sessions:
            sid = session["id"]
            if sid:
                session_map[sid] = session

        # Lire les messages
        try:
            messages = conn.execute("SELECT * FROM message").fetchall()
        except sqlite3.Error:
            return

        for msg in messages:
            try:
                data = json.loads(msg["data"]) if isinstance(msg["data"], str) else msg["data"]
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

            if not isinstance(data, dict):
                continue

            if data.get("role") != "assistant":
                continue

            sid = msg["session_id"]
            session = session_map.get(sid)
            if not session:
                continue

            # Session-level model (fallback si message-level absent)
            try:
                session_model = json.loads(session["model"]) if isinstance(session["model"], str) else session["model"]
            except (json.JSONDecodeError, TypeError):
                session_model = {}

            # Message-level data
            msg_model = data.get("model") or {}
            provider = msg_model.get("providerID") or session_model.get("providerID", "")
            model = msg_model.get("modelID") or msg_model.get("id") or session_model.get("id", "")

            # Tokens (priorité au message, fallback session)
            raw_tokens = data.get("tokens") or {}
            raw_cache = raw_tokens.get("cache") or {}
            input_tokens = _safe_int(_coalesce(raw_tokens.get("input"), session["tokens_input"]))
            output_tokens = _safe_int(_coalesce(raw_tokens.get("output"), session["tokens_output"]))
            cache_read_tokens = _safe_int(_coalesce(raw_cache.get("read"), session["tokens_cache_read"]))
            cache_creation_tokens = _safe_int(_coalesce(raw_cache.get("write"), session["tokens_cache_write"]))

            # Timestamp
            msg_time = data.get("time") or {}
            created_ms = msg_time.get("created") or session["time_created"]
            completed_ms = msg_time.get("completed") or session["time_updated"]
            timestamp = _parse_ts_utc_ms(created_ms)

            # Session fields
            session_id = sid or msg["session_id"]
            directory = session["directory"] or ""
            project = _project_from_cwd(directory)

            # Msg ID
            msg_id = msg["id"] or ""

            # Active seconds
            active_seconds = self._calc_active_seconds(created_ms, completed_ms)

            yield InferenceEvent(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                timestamp=timestamp or "",
                project=project,
                session_id=session_id,
                msg_id=msg_id,
                active_seconds=active_seconds,
                client=self.client,
            )

    @staticmethod
    def _calc_active_seconds(created_ms: int | float | None, completed_ms: int | float | None) -> float:
        """Calcule le temps actif entre created et completed, tronqué à _ACTIVE_CAP_SECONDS."""
        if created_ms is None or completed_ms is None:
            return 0.0
        delta_s = (completed_ms - created_ms) / 1000.0
        if 0 < delta_s <= _ACTIVE_CAP_SECONDS:
            return delta_s
        return 0.0
