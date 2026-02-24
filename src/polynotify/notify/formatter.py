from __future__ import annotations

from polynotify.monitor import Alert


def format_alert(alert: Alert) -> str:
    formatters = {
        "new_market": _fmt_new_market,
        "closing_soon": _fmt_closing_soon,
        "resolved": _fmt_resolved,
        "price_move": _fmt_price_move,
        "volume_spike": _fmt_volume_spike,
    }
    fn = formatters.get(alert.type)
    if fn is None:
        return f"Unknown alert type: {alert.type}"
    return fn(alert)


def _fmt_new_market(alert: Alert) -> str:
    e = alert.event
    title = e.get("title", "Unknown")
    markets = e.get("markets") or []
    liquidity = _fmt_dollars(e.get("liquidity"))
    volume = _fmt_dollars(e.get("volume") or e.get("volume24hr"))
    tags = _fmt_tags(e)
    link = _event_link(e)

    return (
        f"\U0001f195 NEW CRYPTO MARKET\n"
        f"\n"
        f"Title: {title}\n"
        f"Markets: {len(markets)} outcome(s)\n"
        f"Liquidity: {liquidity}\n"
        f"Volume (24h): {volume}\n"
        f"Tags: {tags}\n"
        f"\n"
        f"\U0001f517 {link}"
    )


def _fmt_closing_soon(alert: Alert) -> str:
    e = alert.event
    d = alert.details
    title = e.get("title", "Unknown")
    hours = d.get("hours_left", 0)
    minutes = d.get("minutes_left", 0)
    yes_price, no_price = _get_yes_no_cents(e)
    link = _event_link(e)

    return (
        f"\u23f0 MARKET CLOSING SOON\n"
        f"\n"
        f"Title: {title}\n"
        f"Closes in: {hours}h {minutes}m\n"
        f"Current odds: YES {yes_price}\u00a2 / NO {no_price}\u00a2\n"
        f"\n"
        f"\U0001f517 {link}"
    )


def _fmt_resolved(alert: Alert) -> str:
    e = alert.event
    d = alert.details
    title = e.get("title", "Unknown")
    outcome = d.get("outcome", "Unknown")
    price = d.get("final_price")
    price_str = f"{price * 100:.0f}" if price is not None else "N/A"
    link = _event_link(e)

    return (
        f"\u2705 MARKET RESOLVED\n"
        f"\n"
        f"Title: {title}\n"
        f"Outcome: {outcome}\n"
        f"Final price: {price_str}\u00a2\n"
        f"\n"
        f"\U0001f517 {link}"
    )


def _fmt_price_move(alert: Alert) -> str:
    e = alert.event
    d = alert.details
    title = e.get("title", "Unknown")
    old_c = _to_cents(d.get("old_price"))
    new_c = _to_cents(d.get("new_price"))
    change = d.get("change", 0)
    change_c = f"{change * 100:+.0f}"
    lookback = d.get("lookback_minutes", 60)
    link = _event_link(e)

    return (
        f"\U0001f4c8 SIGNIFICANT ODDS SHIFT\n"
        f"\n"
        f"Title: {title}\n"
        f"Move: {old_c}\u00a2 \u2192 {new_c}\u00a2 ({change_c}\u00a2)\n"
        f"Timeframe: last {lookback} min\n"
        f"\n"
        f"\U0001f517 {link}"
    )


def _fmt_volume_spike(alert: Alert) -> str:
    e = alert.event
    d = alert.details
    title = e.get("title", "Unknown")
    old_vol = _fmt_dollars(d.get("old_volume"))
    new_vol = _fmt_dollars(d.get("new_volume"))
    mult = d.get("multiplier", 0)
    lookback = d.get("lookback_minutes", 60)
    link = _event_link(e)

    return (
        f"\U0001f525 VOLUME SPIKE\n"
        f"\n"
        f"Title: {title}\n"
        f"Volume (24h): {old_vol} \u2192 {new_vol} ({mult}x)\n"
        f"Timeframe: last {lookback} min\n"
        f"\n"
        f"\U0001f517 {link}"
    )


# ── Helpers ──────────────────────────────────────────────────────

def _event_link(event: dict) -> str:
    slug = event.get("slug", "")
    if slug:
        return f"https://polymarket.com/event/{slug}"
    eid = event.get("id", "")
    return f"https://polymarket.com/event/{eid}"


def _fmt_dollars(value: float | str | None) -> str:
    if value is None:
        return "$0"
    try:
        v = float(value)
        if v >= 1_000_000:
            return f"${v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"${v / 1_000:.1f}K"
        return f"${v:,.0f}"
    except (ValueError, TypeError):
        return "$0"


def _to_cents(price: float | None) -> str:
    if price is None:
        return "?"
    return f"{price * 100:.0f}"


def _get_yes_no_cents(event: dict) -> tuple[str, str]:
    markets = event.get("markets") or []
    if not markets:
        return "?", "?"
    m = markets[0]
    price_str = m.get("outcomePrices")
    if price_str:
        import json
        try:
            parsed = price_str if isinstance(price_str, list) else json.loads(price_str)
            yes = float(parsed[0]) if len(parsed) > 0 else 0
            no = float(parsed[1]) if len(parsed) > 1 else 1 - yes
            return f"{yes * 100:.0f}", f"{no * 100:.0f}"
        except (ValueError, TypeError, IndexError):
            pass
    return "?", "?"


def _fmt_tags(event: dict) -> str:
    tags = event.get("tags") or []
    labels = []
    for t in tags:
        if isinstance(t, dict):
            labels.append(t.get("label", ""))
        else:
            labels.append(str(t))
    return ", ".join(labels) if labels else "None"
