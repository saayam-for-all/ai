"""SQLite proxy database storing session summaries, never raw chat turns."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path

from services.memory_privacy import redact_sensitive
from services.memory_store import VersionConflict
from utils import MAX_SUMMARY_CHARS

REQUIRED_KEYS = frozenset({"memory", "summarized_count", "summarized_hash"})

class SessionDeleted(ValueError):
    """A deleted chat session cannot be reused."""


class SQLiteMemoryStore:
    """Local-only store with atomic optimistic writes and demo expiry.

    Not intended for AWS Lambda's ephemeral filesystem or as an auth layer.
    """

    def __init__(self, path, ttl_seconds=24 * 60 * 60):
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("TTL must be positive seconds")
        self.path = str(path)
        self.ttl_seconds = ttl_seconds
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS session_memory (
                    session_id TEXT PRIMARY KEY,
                    memory TEXT NOT NULL,
                    summarized_count INTEGER NOT NULL,
                    summarized_hash TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS deleted_sessions (
                    session_id TEXT PRIMARY KEY,
                    deleted_at INTEGER NOT NULL
                )"""
            )

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _validate_id(session_id):
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 128:
            raise ValueError("A valid session ID is required")

    @staticmethod
    def _validate_state(state):
        if not isinstance(state, dict) or set(state) != REQUIRED_KEYS:
            raise ValueError("Only summary and cursor metadata may be stored")
        memory = state["memory"]
        count = state["summarized_count"]
        digest = state["summarized_hash"]
        if not isinstance(memory, str) or len(memory) > MAX_SUMMARY_CHARS:
            raise ValueError("Summary must be bounded text")
        if redact_sensitive(memory) != memory:
            raise ValueError("Summary contains a recognized secret")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid summary cursor")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest
        ):
            raise ValueError("Invalid summary fingerprint")
    @staticmethod
    def _ensure_not_deleted(conn, session_id):
        """Reject requests for deleted sessions."""
        row = conn.execute(
            "SELECT 1 FROM deleted_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row is not None:
            raise SessionDeleted(
                "This session was deleted. Start a new session."
            )
    def load(self, session_id):
        """Return current session summary and version; ignore expired state."""
        self._validate_id(session_id)
        with closing(self._connect()) as conn:
            self._ensure_not_deleted(conn, session_id)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM session_memory WHERE session_id = ? AND expires_at > ?",
                (session_id, int(time.time())),
            ).fetchone()
        if row is None:
            return {}, 0
        return {
            "memory": row["memory"],
            "summarized_count": row["summarized_count"],
            "summarized_hash": row["summarized_hash"],
        }, row["version"]

    def save(self, session_id, state, expected_version):
        """Atomically update state only if the stored version matches."""
        self._validate_id(session_id)
        self._validate_state(state)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("Expected version must be nonnegative")
        now = int(time.time())
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_not_deleted(conn, session_id)
            try:
                conn.execute("DELETE FROM session_memory WHERE expires_at <= ?", (now,))
                row = conn.execute(
                    "SELECT version FROM session_memory WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                actual_version = row["version"] if row else 0
                if actual_version != expected_version:
                    raise VersionConflict("Conversation state changed")
                new_version = actual_version + 1
                conn.execute(
                    """INSERT INTO session_memory
                    (session_id, memory, summarized_count, summarized_hash, version, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        memory=excluded.memory,
                        summarized_count=excluded.summarized_count,
                        summarized_hash=excluded.summarized_hash,
                        version=excluded.version,
                        expires_at=excluded.expires_at""",
                    (
                        session_id, state["memory"], state["summarized_count"],
                        state["summarized_hash"], new_version,
                        now + self.ttl_seconds,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return new_version

    
    def delete(self, session_id):
        """Delete memory and permanently invalidate the session locally."""
        self._validate_id(session_id)

        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")

            try:
                conn.execute(
                    "DELETE FROM session_memory WHERE session_id = ?",
                    (session_id,),
                )

                conn.execute(
                    """INSERT OR IGNORE INTO deleted_sessions
                    (session_id, deleted_at)
                    VALUES (?, ?)""",
                    (session_id, int(time.time())),
                )

                conn.execute("COMMIT")

            except BaseException:
                conn.execute("ROLLBACK")
                raise


    def purge_expired(self):
        """Physically remove expired records (run periodically in a real service)."""
        with closing(self._connect()) as conn:
            return conn.execute(
                "DELETE FROM session_memory WHERE expires_at <= ?", (int(time.time()),)
            ).rowcount
