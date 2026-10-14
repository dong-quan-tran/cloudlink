"""Small local store for completed CloudLink tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def add(self, result: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO tests
                   (created_at, source_id, destination_id, summary, result_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    result["timestamp"],
                    result["source_id"],
                    result["destination_id"],
                    result["summary"],
                    json.dumps(result),
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, result_json FROM tests ORDER BY id DESC LIMIT ?",
                (min(max(limit, 1), 100),),
            ).fetchall()
        return [{"id": row_id, **json.loads(payload)} for row_id, payload in rows]
