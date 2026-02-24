from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


class Store:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_events (
                event_id TEXT PRIMARY KEY,
                first_seen_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                outcome_prices TEXT,
                volume_24hr REAL,
                recorded_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_event_time
                ON market_snapshots(event_id, recorded_at);

            CREATE TABLE IF NOT EXISTS alerts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                sent_at TEXT DEFAULT (datetime('now')),
                UNIQUE(event_id, alert_type)
            );
        """)

    # ── seen_events ──────────────────────────────────────────────

    def is_seen(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row is not None

    def mark_seen(self, event_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_events (event_id) VALUES (?)", (event_id,)
        )
        self._conn.commit()

    def is_empty(self) -> bool:
        row = self._conn.execute("SELECT COUNT(*) FROM seen_events").fetchone()
        return row[0] == 0

    # ── market_snapshots ─────────────────────────────────────────

    def save_snapshot(
        self, event_id: str, prices: dict | None, volume: float | None
    ) -> None:
        self._conn.execute(
            "INSERT INTO market_snapshots (event_id, outcome_prices, volume_24hr) VALUES (?, ?, ?)",
            (event_id, json.dumps(prices) if prices else None, volume),
        )
        self._conn.commit()

    def get_snapshot(
        self, event_id: str, minutes_ago: int
    ) -> dict | None:
        """Return the oldest snapshot within the lookback window."""
        row = self._conn.execute(
            """
            SELECT outcome_prices, volume_24hr, recorded_at
            FROM market_snapshots
            WHERE event_id = ?
              AND recorded_at <= datetime('now', ?)
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (event_id, f"-{minutes_ago} minutes"),
        ).fetchone()
        if row is None:
            return None
        prices = json.loads(row["outcome_prices"]) if row["outcome_prices"] else None
        return {
            "outcome_prices": prices,
            "volume_24hr": row["volume_24hr"],
            "recorded_at": row["recorded_at"],
        }

    # ── alerts_sent ──────────────────────────────────────────────

    def has_alert(self, event_id: str, alert_type: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alerts_sent WHERE event_id = ? AND alert_type = ?",
            (event_id, alert_type),
        ).fetchone()
        return row is not None

    def record_alert(self, event_id: str, alert_type: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO alerts_sent (event_id, alert_type, sent_at) VALUES (?, ?, datetime('now'))",
            (event_id, alert_type),
        )
        self._conn.commit()

    def last_alert_time(self, event_id: str, alert_type: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT sent_at FROM alerts_sent WHERE event_id = ? AND alert_type = ? ORDER BY sent_at DESC LIMIT 1",
            (event_id, alert_type),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["sent_at"]).replace(tzinfo=timezone.utc)

    # ── maintenance ──────────────────────────────────────────────

    def cleanup_old_snapshots(self, max_age_hours: int = 24) -> int:
        cursor = self._conn.execute(
            "DELETE FROM market_snapshots WHERE recorded_at < datetime('now', ?)",
            (f"-{max_age_hours} hours",),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
