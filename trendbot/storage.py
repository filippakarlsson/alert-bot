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
    fetched_mentions: int = 0


@dataclass(frozen=True)
class TopicSummary:
    topic: str
    cluster_key: str
    total_mentions: int
    samples: int
    latest_observed_at: int
    category: str = "default"
    cluster_label: str = ""
    trend_score: float = 0.0
    source_count: int = 0
    example_title: str = ""


@dataclass(frozen=True)
class TopicRollup:
    topic: str
    observed_at: int
    total_mentions: int
    source_count: int
    category: str
    cluster_key: str
    cluster_label: str
    trend_score: float
    example_title: str


@dataclass(frozen=True)
class CategorySummary:
    category: str
    total_mentions: int
    samples: int
    latest_observed_at: int
    top_topic: str
    trend_score: float


@dataclass(frozen=True)
class ClusterSummary:
    cluster_key: str
    cluster_label: str
    category: str
    total_mentions: int
    samples: int
    latest_observed_at: int
    topic_count: int
    trend_score: float
    example_title: str = ""


@dataclass(frozen=True)
class TrendPoint:
    bucket_ts: int
    total_mentions: int
    trend_score: float


@dataclass(frozen=True)
class BacktestSummary:
    lookback_days: int
    simulated_alerts: int
    topics_tested: int
    alert_rate: float
    strongest_topic: str
    strongest_category: str
    strongest_score: float


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
                    new_mentions INTEGER NOT NULL,
                    fetched_mentions INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(observations)").fetchall()
            }
            if "fetched_mentions" not in columns:
                conn.execute(
                    """
                    ALTER TABLE observations
                    ADD COLUMN fetched_mentions INTEGER NOT NULL DEFAULT 0
                    """
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sent_at INTEGER NOT NULL,
                    trend_score REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_rollups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    observed_at INTEGER NOT NULL,
                    total_mentions INTEGER NOT NULL,
                    source_count INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    cluster_key TEXT NOT NULL,
                    cluster_label TEXT NOT NULL,
                    trend_score REAL NOT NULL,
                    example_title TEXT NOT NULL
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
                INSERT INTO observations (topic, source, observed_at, new_mentions, fetched_mentions)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    observation.topic,
                    observation.source,
                    observation.observed_at,
                    observation.new_mentions,
                    observation.fetched_mentions,
                ),
                )

    def add_topic_rollup(self, rollup: TopicRollup) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO topic_rollups (
                    topic, observed_at, total_mentions, source_count,
                    category, cluster_key, cluster_label, trend_score, example_title
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rollup.topic,
                    rollup.observed_at,
                    rollup.total_mentions,
                    rollup.source_count,
                    rollup.category,
                    rollup.cluster_key,
                    rollup.cluster_label,
                    rollup.trend_score,
                    rollup.example_title,
                ),
            )

    def recent_observations(self, topic: str, source: str, limit: int) -> List[Observation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT topic, source, observed_at, new_mentions, fetched_mentions
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
                fetched_mentions=int(row["fetched_mentions"] or 0),
            )
            for row in rows
        ]
        observations.reverse()
        return observations

    def recent_observations_global(self, limit: int) -> List[Observation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT topic, source, observed_at, new_mentions, fetched_mentions
                FROM observations
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            Observation(
                topic=row["topic"],
                source=row["source"],
                observed_at=row["observed_at"],
                new_mentions=row["new_mentions"],
                fetched_mentions=int(row["fetched_mentions"] or 0),
            )
            for row in rows
        ]

    def top_topics_since(self, since_ts: int, limit: int, min_total_mentions: int = 0) -> List[TopicSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    cluster_key,
                    MAX(cluster_label) AS cluster_label,
                    MAX(example_title) AS example_title,
                    MAX(category) AS category,
                    SUM(total_mentions) AS total_mentions,
                    COUNT(*) AS samples,
                    MAX(observed_at) AS latest_observed_at,
                    MAX(source_count) AS source_count,
                    AVG(trend_score) AS avg_trend_score
                FROM topic_rollups
                WHERE observed_at >= ?
                GROUP BY cluster_key
                HAVING SUM(total_mentions) >= ?
                ORDER BY total_mentions DESC, latest_observed_at DESC
                LIMIT ?
                """,
                (since_ts, min_total_mentions, limit),
            ).fetchall()

        return [
            TopicSummary(
                topic=row["cluster_label"] or row["example_title"] or row["cluster_key"] or "trend",
                cluster_key=row["cluster_key"] or "",
                total_mentions=int(row["total_mentions"] or 0),
                samples=int(row["samples"] or 0),
                latest_observed_at=int(row["latest_observed_at"] or 0),
                category=row["category"] or "default",
                cluster_label=row["cluster_label"] or row["example_title"] or row["cluster_key"] or "",
                trend_score=float(row["avg_trend_score"] or 0.0),
                source_count=int(row["source_count"] or 0),
                example_title=row["example_title"] or "",
            )
            for row in rows
        ]

    def top_categories_since(self, since_ts: int, limit: int) -> List[CategorySummary]:
        with self._connect() as conn:
            category_rows = conn.execute(
                """
                SELECT
                    category,
                    SUM(total_mentions) AS total_mentions,
                    COUNT(*) AS samples,
                    MAX(observed_at) AS latest_observed_at
                FROM topic_rollups
                WHERE observed_at >= ?
                GROUP BY category
                ORDER BY total_mentions DESC, latest_observed_at DESC
                LIMIT ?
                """,
                (since_ts, limit),
            ).fetchall()
            top_topics = conn.execute(
                """
                SELECT category, topic, SUM(total_mentions) AS topic_mentions
                FROM topic_rollups
                WHERE observed_at >= ?
                GROUP BY category, topic
                """,
                (since_ts,),
            ).fetchall()

        best_topic_by_category: dict[str, tuple[str, int]] = {}
        for row in top_topics:
            category = row["category"] or "default"
            topic = row["topic"]
            mentions = int(row["topic_mentions"] or 0)
            current = best_topic_by_category.get(category)
            if current is None or mentions > current[1]:
                best_topic_by_category[category] = (topic, mentions)

        return [
            CategorySummary(
                category=row["category"] or "default",
                total_mentions=int(row["total_mentions"] or 0),
                samples=int(row["samples"] or 0),
                latest_observed_at=int(row["latest_observed_at"] or 0),
                top_topic=best_topic_by_category.get(row["category"] or "default", ("", 0))[0],
                trend_score=min(100.0, round((int(row["total_mentions"] or 0) * 3.2) + (int(row["samples"] or 0) * 2.8), 1)),
            )
            for row in category_rows
        ]

    def top_clusters_since(self, since_ts: int, limit: int) -> List[ClusterSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    cluster_key,
                    MAX(cluster_label) AS cluster_label,
                    MAX(example_title) AS example_title,
                    MAX(category) AS category,
                    SUM(total_mentions) AS total_mentions,
                    COUNT(*) AS samples,
                    MAX(observed_at) AS latest_observed_at,
                    COUNT(DISTINCT topic) AS topic_count,
                    AVG(trend_score) AS avg_trend_score
                FROM topic_rollups
                WHERE observed_at >= ? AND cluster_key <> ''
                GROUP BY cluster_key
                ORDER BY total_mentions DESC, latest_observed_at DESC
                LIMIT ?
                """,
                (since_ts, limit),
            ).fetchall()
        return [
            ClusterSummary(
                cluster_key=row["cluster_key"],
                cluster_label=row["cluster_label"],
                example_title=row["example_title"] or "",
                category=row["category"] or "default",
                total_mentions=int(row["total_mentions"] or 0),
                samples=int(row["samples"] or 0),
                latest_observed_at=int(row["latest_observed_at"] or 0),
                topic_count=int(row["topic_count"] or 0),
                trend_score=min(100.0, round(float(row["avg_trend_score"] or 0.0), 1)),
            )
            for row in rows
        ]

    def topic_timeseries(
        self,
        topic: str,
        since_ts: int,
        bucket_seconds: int = 3600,
        until_ts: int | None = None,
    ) -> List[TrendPoint]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ((observed_at / ?) * ?) AS bucket_ts,
                    SUM(total_mentions) AS total_mentions,
                    AVG(trend_score) AS trend_score
                FROM topic_rollups
                WHERE topic = ? AND observed_at >= ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
                """,
                (bucket_seconds, bucket_seconds, topic, since_ts),
            ).fetchall()
        points = [
            TrendPoint(
                bucket_ts=int(row["bucket_ts"] or 0),
                total_mentions=int(row["total_mentions"] or 0),
                trend_score=float(row["trend_score"] or 0.0),
            )
            for row in rows
        ]
        return self._fill_timeseries(points, since_ts, bucket_seconds, until_ts)

    def cluster_timeseries(
        self,
        cluster_key: str,
        since_ts: int,
        bucket_seconds: int = 3600,
        until_ts: int | None = None,
    ) -> List[TrendPoint]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ((observed_at / ?) * ?) AS bucket_ts,
                    SUM(total_mentions) AS total_mentions,
                    AVG(trend_score) AS trend_score
                FROM topic_rollups
                WHERE cluster_key = ? AND observed_at >= ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
                """,
                (bucket_seconds, bucket_seconds, cluster_key, since_ts),
            ).fetchall()
        points = [
            TrendPoint(
                bucket_ts=int(row["bucket_ts"] or 0),
                total_mentions=int(row["total_mentions"] or 0),
                trend_score=float(row["trend_score"] or 0.0),
            )
            for row in rows
        ]
        return self._fill_timeseries(points, since_ts, bucket_seconds, until_ts)

    @staticmethod
    def _fill_timeseries(
        points: List[TrendPoint],
        since_ts: int,
        bucket_seconds: int,
        until_ts: int | None,
    ) -> List[TrendPoint]:
        if not points:
            return []
        point_map = {point.bucket_ts: point for point in points}
        start_ts = min(point.bucket_ts for point in points)
        end_ts = max(point.bucket_ts for point in points)
        if until_ts is not None:
            end_ts = max(end_ts, until_ts - (until_ts % bucket_seconds))
        filled: List[TrendPoint] = []
        bucket = start_ts
        while bucket <= end_ts:
            point = point_map.get(bucket)
            if point is None:
                point = TrendPoint(bucket_ts=bucket, total_mentions=0, trend_score=0.0)
            filled.append(point)
            bucket += bucket_seconds
        if since_ts < start_ts:
            padding_bucket = since_ts - (since_ts % bucket_seconds)
            prefix: List[TrendPoint] = []
            while padding_bucket < start_ts:
                prefix.append(TrendPoint(bucket_ts=padding_bucket, total_mentions=0, trend_score=0.0))
                padding_bucket += bucket_seconds
            filled = prefix + filled
        return filled

    def recent_rollups(self, limit: int) -> List[TopicRollup]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT topic, observed_at, total_mentions, source_count,
                       category, cluster_key, cluster_label, trend_score, example_title
                FROM topic_rollups
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            TopicRollup(
                topic=row["topic"],
                observed_at=row["observed_at"],
                total_mentions=row["total_mentions"],
                source_count=row["source_count"],
                category=row["category"],
                cluster_key=row["cluster_key"],
                cluster_label=row["cluster_label"],
                trend_score=float(row["trend_score"] or 0.0),
                example_title=row["example_title"],
            )
            for row in rows
        ]

    def backtest_summary(self, since_ts: int, window_size: int, category_multipliers: dict[str, tuple[float, int]]) -> BacktestSummary:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT topic, observed_at, total_mentions, category
                FROM topic_rollups
                WHERE observed_at >= ?
                ORDER BY topic ASC, observed_at ASC, id ASC
                """,
                (since_ts,),
            ).fetchall()

        by_topic: dict[str, list[tuple[int, int, str]]] = {}
        for row in rows:
            by_topic.setdefault(row["topic"], []).append(
                (int(row["observed_at"] or 0), int(row["total_mentions"] or 0), row["category"] or "default")
            )

        simulated_alerts = 0
        strongest_topic = ""
        strongest_category = "default"
        strongest_score = 0.0
        for topic, samples in by_topic.items():
            history: list[int] = []
            category = samples[-1][2] if samples else "default"
            multiplier, min_baseline = category_multipliers.get(category, category_multipliers.get("default", (2.5, 2)))
            for _, current, row_category in samples:
                if row_category:
                    category = row_category
                effective_window = min(window_size, len(history))
                if effective_window >= 3:
                    baseline_window = history[-effective_window:]
                    baseline = sum(baseline_window) / len(baseline_window) if baseline_window else 0.0
                    if baseline >= min_baseline and current >= max(min_baseline, int(baseline * multiplier)):
                        simulated_alerts += 1
                        score = current / baseline if baseline > 0 else float(current)
                        if score > strongest_score:
                            strongest_score = score
                            strongest_topic = topic
                            strongest_category = category
                    elif baseline < min_baseline:
                        cold_start_floor = max(2, min_baseline + 1)
                        if current >= cold_start_floor:
                            simulated_alerts += 1
                            score = current / max(1.0, baseline)
                            if score > strongest_score:
                                strongest_score = score
                                strongest_topic = topic
                                strongest_category = category
                history.append(current)

        topics_tested = len(by_topic)
        alert_rate = (simulated_alerts / topics_tested) if topics_tested else 0.0
        return BacktestSummary(
            lookback_days=max(1, int(round((time.time() - since_ts) / 86400))),
            simulated_alerts=simulated_alerts,
            topics_tested=topics_tested,
            alert_rate=round(alert_rate, 3),
            strongest_topic=strongest_topic,
            strongest_category=strongest_category,
            strongest_score=round(strongest_score, 2),
        )

    def get_state(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM state
                WHERE key = ?
                LIMIT 1
                """,
                (key,),
            ).fetchone()
            if row is None:
                return None
            return row["value"]

    def set_state(self, key: str, value: str) -> None:
        updated_at = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, updated_at),
            )

    def add_alert_event(
        self,
        topic: str,
        source: str,
        sent_at: int | None = None,
        trend_score: float = 0.0,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_events (topic, source, sent_at, trend_score)
                VALUES (?, ?, ?, ?)
                """,
                (
                    topic,
                    source,
                    int(sent_at or time.time()),
                    float(trend_score),
                ),
            )

    def count_alert_events_since(self, since_ts: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM alert_events
                WHERE sent_at >= ?
                """,
                (since_ts,),
            ).fetchone()
        return int(row["count"] or 0) if row else 0
