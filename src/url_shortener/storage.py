"""SQLite-backed repository layer (assumption A5: SQLite, isolated behind this interface
so swapping the storage engine later is a contained change)."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code TEXT PRIMARY KEY,
    target_url TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL,
    deleted_at REAL
);
CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    ts REAL NOT NULL,
    referrer TEXT,
    user_agent TEXT,
    FOREIGN KEY (code) REFERENCES links(code)
);
CREATE INDEX IF NOT EXISTS idx_clicks_code ON clicks(code);
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    code TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (key, owner_id)
);
"""


@dataclass
class Link:
    code: str
    target_url: str
    owner_id: str
    created_at: float
    expires_at: float | None
    deleted_at: float | None


class LinkRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Unlike `with sqlite3.connect(...) as conn`, which only manages the transaction
        and leaks the underlying file handle, this always closes the connection -- required
        for correctness (Windows won't let a temp dir holding an open db file be removed)."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.executescript(SCHEMA)

    @staticmethod
    def _row_to_link(row: sqlite3.Row) -> Link:
        return Link(
            code=row["code"],
            target_url=row["target_url"],
            owner_id=row["owner_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            deleted_at=row["deleted_at"],
        )

    def code_exists(self, code: str) -> bool:
        with self._session() as conn:
            row = conn.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone()
            return row is not None

    def create_link(self, code: str, target_url: str, owner_id: str, expires_at: float | None = None) -> Link:
        now = time.time()
        with self._session() as conn:
            conn.execute(
                "INSERT INTO links (code, target_url, owner_id, created_at, expires_at, deleted_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (code, target_url, owner_id, now, expires_at),
            )
        return Link(code, target_url, owner_id, now, expires_at, None)

    def get_link(self, code: str) -> Link | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        return self._row_to_link(row) if row else None

    def list_links(self, owner_id: str) -> list[Link]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM links WHERE owner_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                (owner_id,),
            ).fetchall()
        return [self._row_to_link(r) for r in rows]

    def soft_delete(self, code: str, owner_id: str) -> bool:
        with self._session() as conn:
            cur = conn.execute(
                "UPDATE links SET deleted_at = ? WHERE code = ? AND owner_id = ? AND deleted_at IS NULL",
                (time.time(), code, owner_id),
            )
        return cur.rowcount > 0

    def record_click(self, code: str, referrer: str | None, user_agent: str | None) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO clicks (code, ts, referrer, user_agent) VALUES (?, ?, ?, ?)",
                (code, time.time(), referrer, user_agent),
            )

    def analytics(self, code: str) -> dict:
        with self._session() as conn:
            rows = conn.execute("SELECT ts, referrer FROM clicks WHERE code = ? ORDER BY ts", (code,)).fetchall()
        referrers: dict[str, int] = {}
        for r in rows:
            key = r["referrer"] or "unknown"
            referrers[key] = referrers.get(key, 0) + 1
        return {
            "click_count": len(rows),
            "first_click_at": rows[0]["ts"] if rows else None,
            "last_click_at": rows[-1]["ts"] if rows else None,
            "referrers": referrers,
        }

    def find_idempotent_code(self, key: str, owner_id: str) -> str | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT code FROM idempotency_keys WHERE key = ? AND owner_id = ?", (key, owner_id)
            ).fetchone()
        return row["code"] if row else None

    def save_idempotency_key(self, key: str, owner_id: str, code: str) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys (key, owner_id, code, created_at) VALUES (?, ?, ?, ?)",
                (key, owner_id, code, time.time()),
            )
