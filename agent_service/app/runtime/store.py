"""Sync SQLite store for session events and checkpoints.

Uses stdlib sqlite3 so FreeCAD-side recovery scripts and unit tests
do not depend on async SQLAlchemy session lifecycle.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


class RuntimeStore:
    """Append-only event log + latest checkpoints keyed by session_id."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL DEFAULT 'running',
                        user_goal TEXT,
                        user_input TEXT,
                        plan_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS session_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        action_id TEXT,
                        phase_id TEXT,
                        step_id TEXT,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, seq),
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_events_session_seq
                        ON session_events(session_id, seq);

                    CREATE TABLE IF NOT EXISTS session_checkpoints (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        checkpoint_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        run_state_json TEXT NOT NULL,
                        event_seq INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, checkpoint_id),
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                        ON session_checkpoints(session_id, id DESC);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def create_session(
        self,
        session_id: str,
        *,
        user_input: str = "",
        user_goal: str = "",
        plan_json: Optional[dict] = None,
        status: str = "running",
    ) -> dict:
        now = _utc_now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                    (session_id, status, user_goal, user_input, plan_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, COALESCE(
                        (SELECT created_at FROM sessions WHERE session_id = ?), ?
                    ), ?)
                    """,
                    (
                        session_id,
                        status,
                        user_goal,
                        user_input,
                        _dumps(plan_json or {}),
                        session_id,
                        now,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_session(session_id) or {}

    def update_session(
        self,
        session_id: str,
        *,
        status: Optional[str] = None,
        user_goal: Optional[str] = None,
        plan_json: Optional[dict] = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if user_goal is not None:
            fields.append("user_goal = ?")
            values.append(user_goal)
        if plan_json is not None:
            fields.append("plan_json = ?")
            values.append(_dumps(plan_json))
        values.append(session_id)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE sessions SET {', '.join(fields)} WHERE session_id = ?",
                    values,
                )
                conn.commit()
            finally:
                conn.close()

    def list_sessions(self, limit: int = 20) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT session_id, status, user_goal, user_input, created_at, updated_at
                    FROM sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            finally:
                conn.close()
        return [
            {
                "session_id": row["session_id"],
                "status": row["status"],
                "user_goal": row["user_goal"],
                "user_input": row["user_input"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def action_ids_with_event(self, session_id: str, event_type: str) -> set[str]:
        """All non-null action_ids that recorded the given event type."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT DISTINCT action_id FROM session_events
                    WHERE session_id = ? AND event_type = ? AND action_id IS NOT NULL
                    """,
                    (session_id, event_type),
                ).fetchall()
            finally:
                conn.close()
        return {row["action_id"] for row in rows}

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "status": row["status"],
            "user_goal": row["user_goal"],
            "user_input": row["user_input"],
            "plan_json": _loads(row["plan_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def append_event(
        self,
        session_id: str,
        event_type: str,
        *,
        payload: Optional[dict] = None,
        action_id: Optional[str] = None,
        phase_id: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> dict:
        if self.get_session(session_id) is None:
            self.create_session(session_id)

        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM session_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                seq = int(row["max_seq"]) + 1
                created_at = _utc_now()
                conn.execute(
                    """
                    INSERT INTO session_events
                    (session_id, seq, event_type, action_id, phase_id, step_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        seq,
                        event_type,
                        action_id,
                        phase_id,
                        step_id,
                        _dumps(payload or {}),
                        created_at,
                    ),
                )
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (created_at, session_id),
                )
                conn.commit()
            finally:
                conn.close()

        return {
            "session_id": session_id,
            "seq": seq,
            "event_type": event_type,
            "action_id": action_id,
            "phase_id": phase_id,
            "step_id": step_id,
            "payload": payload or {},
            "created_at": created_at,
        }

    def list_events(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: Optional[int] = None,
        event_types: Optional[list[str]] = None,
    ) -> list[dict]:
        sql = (
            "SELECT * FROM session_events WHERE session_id = ? AND seq > ?"
        )
        params: list[Any] = [session_id, after_seq]
        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            sql += f" AND event_type IN ({placeholders})"
            params.extend(event_types)
        sql += " ORDER BY seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()

        return [
            {
                "session_id": row["session_id"],
                "seq": row["seq"],
                "event_type": row["event_type"],
                "action_id": row["action_id"],
                "phase_id": row["phase_id"],
                "step_id": row["step_id"],
                "payload": _loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def recent_events(self, session_id: str, limit: int = 12) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM session_events
                    WHERE session_id = ?
                    ORDER BY seq DESC
                    LIMIT ?
                    """,
                    (session_id, int(limit)),
                ).fetchall()
            finally:
                conn.close()
        events = [
            {
                "session_id": row["session_id"],
                "seq": row["seq"],
                "event_type": row["event_type"],
                "action_id": row["action_id"],
                "phase_id": row["phase_id"],
                "step_id": row["step_id"],
                "payload": _loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        events.reverse()
        return events

    def latest_seq(self, session_id: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM session_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
        return int(row["max_seq"])

    def save_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str,
        *,
        status: str,
        run_state: dict,
        event_seq: Optional[int] = None,
    ) -> dict:
        if self.get_session(session_id) is None:
            self.create_session(session_id)

        seq = self.latest_seq(session_id) if event_seq is None else int(event_seq)
        created_at = _utc_now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO session_checkpoints
                    (session_id, checkpoint_id, status, run_state_json, event_seq, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        checkpoint_id,
                        status,
                        _dumps(run_state),
                        seq,
                        created_at,
                    ),
                )
                conn.execute(
                    "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                    (status, created_at, session_id),
                )
                conn.commit()
            finally:
                conn.close()

        return {
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "status": status,
            "run_state": run_state,
            "event_seq": seq,
            "created_at": created_at,
        }

    def latest_checkpoint(self, session_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT * FROM session_checkpoints
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "checkpoint_id": row["checkpoint_id"],
            "status": row["status"],
            "run_state": _loads(row["run_state_json"], {}),
            "event_seq": row["event_seq"],
            "created_at": row["created_at"],
        }
