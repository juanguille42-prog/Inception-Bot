from __future__ import annotations

import time

from polynotify.store import Store


def test_seen_events() -> None:
    store = Store(":memory:")
    assert store.is_empty()
    assert not store.is_seen("evt-1")

    store.mark_seen("evt-1")
    assert store.is_seen("evt-1")
    assert not store.is_empty()

    # Idempotent
    store.mark_seen("evt-1")
    assert store.is_seen("evt-1")


def test_snapshots() -> None:
    store = Store(":memory:")
    store.save_snapshot("evt-1", {"Yes": 0.65, "No": 0.35}, 10000.0)

    # No snapshot old enough (lookback=60 means we want data >= 60 min old)
    snap = store.get_snapshot("evt-1", 60)
    assert snap is None

    # Snapshot within 0 minutes lookback should return it
    snap = store.get_snapshot("evt-1", 0)
    assert snap is not None
    assert snap["outcome_prices"]["Yes"] == 0.65
    assert snap["volume_24hr"] == 10000.0


def test_snapshot_none_values() -> None:
    store = Store(":memory:")
    store.save_snapshot("evt-2", None, None)
    snap = store.get_snapshot("evt-2", 0)
    assert snap is not None
    assert snap["outcome_prices"] is None
    assert snap["volume_24hr"] is None


def test_alerts_one_time() -> None:
    store = Store(":memory:")
    assert not store.has_alert("evt-1", "closing_soon")

    store.record_alert("evt-1", "closing_soon")
    assert store.has_alert("evt-1", "closing_soon")

    # Different alert type is not seen
    assert not store.has_alert("evt-1", "resolved")


def test_last_alert_time() -> None:
    store = Store(":memory:")
    assert store.last_alert_time("evt-1", "price_move") is None

    store.record_alert("evt-1", "price_move")
    ts = store.last_alert_time("evt-1", "price_move")
    assert ts is not None


def test_cleanup_old_snapshots() -> None:
    store = Store(":memory:")
    # Insert a snapshot with a backdated timestamp
    store._conn.execute(
        "INSERT INTO market_snapshots (event_id, outcome_prices, volume_24hr, recorded_at) VALUES (?, ?, ?, datetime('now', '-2 hours'))",
        ("evt-1", '{"Yes": 0.5}', 1000.0),
    )
    store._conn.commit()

    deleted = store.cleanup_old_snapshots(max_age_hours=1)
    assert deleted == 1

    # Confirm it's gone
    snap = store.get_snapshot("evt-1", 0)
    assert snap is None
