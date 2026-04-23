from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class Observation:
    topic: str
    source: str
    observed_at: int
    new_mentions: int


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_items (
                    source TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    seen_at INTEGER NOT NULL,
                    PRIMARY KEY (source, topic, item_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_at INTEGER NOT NULL,
                    new_mentions INTEGER NOT NULL
                )
                """
            )

    def has_seen_item(self, source: str, topic: str, item_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM seen_items
                WHERE source = ? AND topic = ? AND item_id = ?
                LIMIT 1
                """,
                (source, topic, item_id),
            ).fetchone()
            return row is not None

    def mark_seen_items(self, source: str, topic: str, item_ids: Iterable[str]) -> int:
        seen_at = int(time.time())
        inserted = 0
        with self._connect() as conn:
            for item_id in item_ids:
                try:
                    conn.execute(
                        """
                        INSERT INTO seen_items (source, topic, item_id, seen_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (source, topic, item_id, seen_at),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    continue
        return inserted

    def add_observation(self, observation: Observation) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO observations (topic, source, observed_at, new_mentions)
                VALUES (?, ?, ?, ?)
                """,
                (
                    observation.topic,
                    observation.source,
                    observation.observed_at,
                    observation.new_mentions,
                ),
            )

    def recent_observations(self, topic: str, source: str, limit: int) -> List[Observation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT topic, source, observed_at, new_mentions
                FROM observations
                WHERE topic = ? AND source = ?
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (topic, source, limit),
            ).fetchall()

        observations = [
            Observation(
                topic=row["topic"],
                source=row["source"],
                observed_at=row["observed_at"],
                new_mentions=row["new_mentions"],
            )
            for row in rows
        ]
        observations.reverse()
        return observations
