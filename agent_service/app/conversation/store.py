"""对话记录的持久化。

与 `RuntimeStore` 共用同一个 sqlite 文件，但表和生命周期独立：对话可以被单独
压缩或清空，而不影响事件日志与检查点。用 stdlib sqlite3，理由同 RuntimeStore
（不引入 async session 生命周期）。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.conversation.transcript import Transcript

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "runtime.db"


def default_db_path() -> Path:
    override = os.getenv("RUNTIME_DB_PATH", "").strip()
    return Path(override) if override else _DEFAULT_DB


class ConversationStore:
    """按 session_id 存取消息流，append-only。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, seq)
                    );

                    CREATE INDEX IF NOT EXISTS idx_conversation_session_seq
                        ON conversation_messages(session_id, seq);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def load(self, session_id: str) -> Transcript:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT role, content FROM conversation_messages "
                    "WHERE session_id = ? ORDER BY seq ASC",
                    (session_id,),
                ).fetchall()
            finally:
                conn.close()
        return Transcript(
            messages=[{"role": r["role"], "content": r["content"]} for r in rows]
        )

    def append(self, session_id: str, messages: list[dict]) -> None:
        """追加新消息；调用方给的是本次新增的部分，不是全量。"""
        if not messages:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq "
                    "FROM conversation_messages WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                seq = int(row["max_seq"])
                conn.executemany(
                    "INSERT INTO conversation_messages "
                    "(session_id, seq, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    [
                        (session_id, seq + i + 1, m["role"], m["content"], now)
                        for i, m in enumerate(messages)
                    ],
                )
                conn.commit()
            finally:
                conn.close()

    def message_count(self, session_id: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM conversation_messages WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            finally:
                conn.close()
        return int(row["n"])

    def clear(self, session_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM conversation_messages WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
            finally:
                conn.close()
