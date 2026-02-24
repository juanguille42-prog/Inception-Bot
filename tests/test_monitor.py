from __future__ import annotations

import json

import httpx
import pytest
import respx

from polynotify.config import AlertsConfig, Config, GammaConfig
from polynotify.monitor import Monitor
from polynotify.store import Store

GAMMA_URL = "https://gamma-api.polymarket.com"


def _make_config(**alert_overrides: object) -> Config:
    alerts_kw = {
        "closing_alert_hours": 2.0,
        "price_threshold": 0.15,
        "price_lookback_minutes": 60,
        "price_cooldown_minutes": 30,
        "volume_spike_multiplier": 3.0,
        "volume_lookback_minutes": 60,
        "volume_cooldown_minutes": 60,
    }
    alerts_kw.update(alert_overrides)
    return Config(
        gamma=GammaConfig(base_url=GAMMA_URL, include_recurring=False),
        alerts=AlertsConfig(**alerts_kw),
    )


def _make_event(
    event_id: str = "evt-1",
    title: str = "Will BTC go up?",
    closed: bool = False,
    end_date: str | None = None,
    tags: list | None = None,
    yes_price: float = 0.5,
    volume: float = 10000,
) -> dict:
    return {
        "id": event_id,
        "title": title,
        "slug": "btc-go-up",
        "closed": closed,
        "endDate": end_date,
        "tags": tags or [{"label": "Crypto"}],
        "liquidity": 5000,
        "volume": volume,
        "markets": [
            {
                "groupItemTitle": "Yes",
                "outcomePrices": json.dumps([yes_price, 1 - yes_price]),
            }
        ],
    }


@pytest.mark.asyncio
async def test_new_market_detection() -> None:
    config = _make_config()
    store = Store(":memory:")

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[_make_event()]),     # active
                httpx.Response(200, json=[]),                  # closed
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            # First run: backfill, no alerts
            alerts = await monitor.poll()
            assert len(alerts) == 0
            assert store.is_seen("evt-1")

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[_make_event(), _make_event(event_id="evt-2", title="ETH up?")]),
                httpx.Response(200, json=[]),
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            monitor._cycle = 1  # Not first run
            alerts = await monitor.poll()
            # Only evt-2 is new
            new_alerts = [a for a in alerts if a.type == "new_market"]
            assert len(new_alerts) == 1
            assert new_alerts[0].event["id"] == "evt-2"


@pytest.mark.asyncio
async def test_recurring_filtered() -> None:
    config = _make_config()
    store = Store(":memory:")

    recurring_event = _make_event(
        event_id="evt-rec",
        tags=[{"label": "Crypto"}, {"label": "Recurring"}],
    )

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[recurring_event]),
                httpx.Response(200, json=[]),
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            alerts = await monitor.poll()
            assert len(alerts) == 0
            assert not store.is_seen("evt-rec")


@pytest.mark.asyncio
async def test_resolved_detection() -> None:
    config = _make_config()
    store = Store(":memory:")
    store.mark_seen("evt-1")  # Pre-seed as tracked

    resolved_event = _make_event(closed=True, yes_price=0.95)

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[]),                    # active
                httpx.Response(200, json=[resolved_event]),      # closed
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            monitor._cycle = 1
            alerts = await monitor.poll()
            resolved = [a for a in alerts if a.type == "resolved"]
            assert len(resolved) == 1
            assert resolved[0].details["outcome"] == "Yes"


@pytest.mark.asyncio
async def test_price_move_detection() -> None:
    config = _make_config(price_threshold=0.10, price_lookback_minutes=0)
    store = Store(":memory:")
    store.mark_seen("evt-1")

    # Seed an old snapshot
    store.save_snapshot("evt-1", {"Yes": 0.50}, 10000)

    moved_event = _make_event(yes_price=0.70)

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[moved_event]),
                httpx.Response(200, json=[]),
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            monitor._cycle = 1
            alerts = await monitor.poll()
            price_alerts = [a for a in alerts if a.type == "price_move"]
            assert len(price_alerts) == 1
            assert price_alerts[0].details["old_price"] == 0.50
            assert price_alerts[0].details["new_price"] == 0.70


@pytest.mark.asyncio
async def test_volume_spike_detection() -> None:
    config = _make_config(volume_spike_multiplier=2.0, volume_lookback_minutes=0)
    store = Store(":memory:")
    store.mark_seen("evt-1")

    # Seed an old snapshot with low volume
    store.save_snapshot("evt-1", {"Yes": 0.50}, 1000)

    spiked_event = _make_event(volume=5000)

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[spiked_event]),
                httpx.Response(200, json=[]),
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            monitor._cycle = 1
            alerts = await monitor.poll()
            vol_alerts = [a for a in alerts if a.type == "volume_spike"]
            assert len(vol_alerts) == 1
            assert vol_alerts[0].details["multiplier"] == 5.0


@pytest.mark.asyncio
async def test_cooldown_prevents_duplicate_price_alert() -> None:
    config = _make_config(price_threshold=0.10, price_lookback_minutes=0, price_cooldown_minutes=30)
    store = Store(":memory:")
    store.mark_seen("evt-1")
    store.save_snapshot("evt-1", {"Yes": 0.50}, 10000)

    # Record a recent price alert
    store.record_alert("evt-1", "price_move")

    moved_event = _make_event(yes_price=0.70)

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            side_effect=[
                httpx.Response(200, json=[moved_event]),
                httpx.Response(200, json=[]),
            ]
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            monitor._cycle = 1
            alerts = await monitor.poll()
            price_alerts = [a for a in alerts if a.type == "price_move"]
            assert len(price_alerts) == 0  # Cooldown prevents alert


@pytest.mark.asyncio
async def test_gamma_api_error_handled() -> None:
    config = _make_config()
    store = Store(":memory:")

    with respx.mock:
        respx.get(f"{GAMMA_URL}/events").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        async with httpx.AsyncClient() as client:
            monitor = Monitor(config, store, client)
            alerts = await monitor.poll()
            assert alerts == []
