from __future__ import annotations

from polynotify.monitor import Alert
from polynotify.notify.formatter import format_alert


def _make_event(**overrides: object) -> dict:
    base = {
        "id": "evt-1",
        "title": "Will BTC be above $100K?",
        "slug": "btc-above-100k",
        "markets": [
            {
                "groupItemTitle": "Yes",
                "outcomePrices": '[0.65, 0.35]',
            }
        ],
        "liquidity": 50000,
        "volume": 120000,
        "tags": [{"label": "Crypto"}],
    }
    base.update(overrides)
    return base


def test_new_market_format() -> None:
    alert = Alert(type="new_market", event=_make_event())
    msg = format_alert(alert)
    assert "NEW CRYPTO MARKET" in msg
    assert "BTC" in msg
    assert "1 outcome(s)" in msg
    assert "$50.0K" in msg
    assert "polymarket.com" in msg


def test_closing_soon_format() -> None:
    alert = Alert(
        type="closing_soon",
        event=_make_event(),
        details={"hours_left": 1, "minutes_left": 30},
    )
    msg = format_alert(alert)
    assert "CLOSING SOON" in msg
    assert "1h 30m" in msg
    assert "YES 65" in msg
    assert "NO 35" in msg


def test_resolved_format() -> None:
    alert = Alert(
        type="resolved",
        event=_make_event(),
        details={"outcome": "Yes", "final_price": 0.95},
    )
    msg = format_alert(alert)
    assert "RESOLVED" in msg
    assert "Yes" in msg
    assert "95" in msg


def test_price_move_format() -> None:
    alert = Alert(
        type="price_move",
        event=_make_event(),
        details={
            "old_price": 0.50,
            "new_price": 0.70,
            "change": 0.20,
            "lookback_minutes": 60,
        },
    )
    msg = format_alert(alert)
    assert "ODDS SHIFT" in msg
    assert "50" in msg
    assert "70" in msg
    assert "+20" in msg


def test_volume_spike_format() -> None:
    alert = Alert(
        type="volume_spike",
        event=_make_event(),
        details={
            "old_volume": 10000,
            "new_volume": 50000,
            "multiplier": 5.0,
            "lookback_minutes": 60,
        },
    )
    msg = format_alert(alert)
    assert "VOLUME SPIKE" in msg
    assert "$10.0K" in msg
    assert "$50.0K" in msg
    assert "5.0x" in msg
