from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import structlog

from polynotify.config import Config
from polynotify.store import Store

log = structlog.get_logger()


@dataclass
class Alert:
    type: str  # 'new_market', 'closing_soon', 'resolved', 'price_move', 'volume_spike'
    event: dict
    details: dict = field(default_factory=dict)


class Monitor:
    def __init__(self, config: Config, store: Store, client: httpx.AsyncClient) -> None:
        self._cfg = config
        self._store = store
        self._client = client
        self._cycle = 0

    async def poll(self) -> list[Alert]:
        alerts: list[Alert] = []
        self._cycle += 1
        is_first_run = self._store.is_empty()

        # Fetch active events
        active_events = await self._fetch_active_events()
        # Fetch recently closed events
        closed_events = await self._fetch_closed_events()

        all_events = {e["id"]: e for e in active_events}
        for e in closed_events:
            all_events.setdefault(e["id"], e)

        enabled = set(self._cfg.alerts.enabled_alerts)

        for event in all_events.values():
            event_id = event["id"]

            # New market detection
            if "new_market" in enabled:
                alert = self._check_new_market(event, is_first_run)
                if alert:
                    alerts.append(alert)
            else:
                # Still mark seen for other detectors
                if not self._store.is_seen(event_id):
                    self._store.mark_seen(event_id)

            # Closing soon (only active)
            if "closing_soon" in enabled and not _is_closed(event):
                alert = self._check_closing_soon(event)
                if alert:
                    alerts.append(alert)

            # Resolved
            if "resolved" in enabled:
                alert = self._check_resolved(event)
                if alert:
                    alerts.append(alert)

            # Price movement (only active)
            if "price_move" in enabled and not _is_closed(event):
                alert = self._check_price_move(event)
                if alert:
                    alerts.append(alert)

            # Volume spike (only active)
            if "volume_spike" in enabled and not _is_closed(event):
                alert = self._check_volume_spike(event)
                if alert:
                    alerts.append(alert)

            # Save snapshot for active events
            if not _is_closed(event):
                prices = _extract_prices(event)
                volume = _extract_volume(event)
                self._store.save_snapshot(event_id, prices, volume)

        # Periodic cleanup
        if self._cycle % 60 == 0:
            deleted = self._store.cleanup_old_snapshots(max_age_hours=24)
            if deleted:
                log.info("cleaned_old_snapshots", count=deleted)

        if is_first_run:
            log.info("first_run_backfill", seeded=len(all_events))

        return alerts

    # ── Fetchers ─────────────────────────────────────────────────

    async def _fetch_active_events(self) -> list[dict]:
        cfg = self._cfg.gamma
        params: dict = {
            "tag_id": cfg.tag_id,
            "active": "true",
            "closed": "false",
            "limit": cfg.fetch_limit,
        }
        return await self._fetch_events(params)

    async def _fetch_closed_events(self) -> list[dict]:
        cfg = self._cfg.gamma
        params: dict = {
            "tag_id": cfg.tag_id,
            "closed": "true",
            "limit": 20,
            "order": "updatedAt",
            "ascending": "false",
        }
        return await self._fetch_events(params)

    async def _fetch_events(self, params: dict) -> list[dict]:
        cfg = self._cfg.gamma
        try:
            resp = await self._client.get(f"{cfg.base_url}/events", params=params)
            resp.raise_for_status()
            events = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.error("gamma_fetch_failed", error=str(exc))
            return []

        if not cfg.include_recurring:
            events = [e for e in events if not _is_recurring(e)]

        if cfg.tag_whitelist:
            events = [e for e in events if _has_tags(e, cfg.tag_whitelist)]

        if cfg.min_liquidity > 0:
            events = [e for e in events if _get_liquidity(e) >= cfg.min_liquidity]

        if cfg.title_keywords:
            events = [e for e in events if _title_matches(e, cfg.title_keywords)]

        return events

    # ── Detectors ────────────────────────────────────────────────

    def _check_new_market(self, event: dict, is_first_run: bool) -> Alert | None:
        event_id = event["id"]
        if self._store.is_seen(event_id):
            return None
        self._store.mark_seen(event_id)
        if is_first_run:
            return None  # Backfill — don't notify
        # Skip markets created more than max_age_hours ago
        max_age = self._cfg.alerts.new_market_max_age_hours
        created_at_str = event.get("createdAt")
        if created_at_str and max_age > 0:
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                if age_hours > max_age:
                    log.debug("new_market_too_old", event_id=event_id, age_hours=round(age_hours, 1))
                    return None
            except (ValueError, TypeError):
                pass
        return Alert(type="new_market", event=event)

    def _check_closing_soon(self, event: dict) -> Alert | None:
        event_id = event["id"]
        end_date_str = event.get("endDate") or event.get("end_date_iso")
        if not end_date_str:
            return None

        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

        now = datetime.now(timezone.utc)
        remaining = end_date - now
        hours_left = remaining.total_seconds() / 3600

        if hours_left <= 0 or hours_left > self._cfg.alerts.closing_alert_hours:
            return None

        if self._store.has_alert(event_id, "closing_soon"):
            return None

        minutes_left = int(remaining.total_seconds() / 60) % 60
        return Alert(
            type="closing_soon",
            event=event,
            details={
                "hours_left": int(hours_left),
                "minutes_left": minutes_left,
            },
        )

    def _check_resolved(self, event: dict) -> Alert | None:
        event_id = event["id"]
        if not _is_closed(event):
            return None
        if not self._store.is_seen(event_id):
            return None  # We never tracked this market
        if self._store.has_alert(event_id, "resolved"):
            return None

        outcome, price = _extract_resolution(event)
        return Alert(
            type="resolved",
            event=event,
            details={"outcome": outcome, "final_price": price},
        )

    def _check_price_move(self, event: dict) -> Alert | None:
        event_id = event["id"]
        cfg = self._cfg.alerts
        prices = _extract_prices(event)
        if not prices:
            return None

        snapshot = self._store.get_snapshot(event_id, cfg.price_lookback_minutes)
        if not snapshot or not snapshot["outcome_prices"]:
            return None

        old_prices = snapshot["outcome_prices"]
        # Compare first outcome (YES) price
        try:
            new_price = float(list(prices.values())[0])
            old_price = float(list(old_prices.values())[0])
        except (IndexError, ValueError, TypeError):
            return None

        change = abs(new_price - old_price)
        if change < cfg.price_threshold:
            return None

        # Cooldown check
        last = self._store.last_alert_time(event_id, "price_move")
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if elapsed < cfg.price_cooldown_minutes:
                return None

        return Alert(
            type="price_move",
            event=event,
            details={
                "old_price": old_price,
                "new_price": new_price,
                "change": new_price - old_price,
                "lookback_minutes": cfg.price_lookback_minutes,
            },
        )

    def _check_volume_spike(self, event: dict) -> Alert | None:
        event_id = event["id"]
        cfg = self._cfg.alerts
        volume = _extract_volume(event)
        if not volume or volume <= 0:
            return None

        snapshot = self._store.get_snapshot(event_id, cfg.volume_lookback_minutes)
        if not snapshot or not snapshot["volume_24hr"] or snapshot["volume_24hr"] <= 0:
            return None

        old_volume = snapshot["volume_24hr"]
        multiplier = volume / old_volume
        if multiplier < cfg.volume_spike_multiplier:
            return None

        # Cooldown check
        last = self._store.last_alert_time(event_id, "volume_spike")
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if elapsed < cfg.volume_cooldown_minutes:
                return None

        return Alert(
            type="volume_spike",
            event=event,
            details={
                "old_volume": old_volume,
                "new_volume": volume,
                "multiplier": round(multiplier, 1),
                "lookback_minutes": cfg.volume_lookback_minutes,
            },
        )


# ── Helpers ──────────────────────────────────────────────────────

def _is_closed(event: dict) -> bool:
    return event.get("closed") is True or str(event.get("closed")).lower() == "true"


def _is_recurring(event: dict) -> bool:
    tags = event.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            label = tag.get("label", "") if isinstance(tag, dict) else str(tag)
            if "recurring" in label.lower():
                return True
    return False


def _has_tags(event: dict, whitelist: list[str]) -> bool:
    tags = event.get("tags") or []
    labels = set()
    for tag in tags:
        if isinstance(tag, dict):
            labels.add(tag.get("label", "").lower())
        else:
            labels.add(str(tag).lower())
    return any(w.lower() in labels for w in whitelist)


def _title_matches(event: dict, keywords: list[str]) -> bool:
    title = (event.get("title") or "").lower()
    return any(kw.lower() in title for kw in keywords)


def _get_liquidity(event: dict) -> float:
    try:
        return float(event.get("liquidity", 0) or 0)
    except (ValueError, TypeError):
        return 0


def _extract_prices(event: dict) -> dict | None:
    markets = event.get("markets") or []
    if not markets:
        return None
    prices = {}
    for m in markets:
        outcome = m.get("groupItemTitle") or m.get("outcome", "Unknown")
        price = m.get("outcomePrices")
        if price:
            try:
                parsed = price if isinstance(price, list) else __import__("json").loads(price)
                prices[outcome] = float(parsed[0]) if parsed else None
            except (ValueError, TypeError, IndexError):
                pass
        elif m.get("lastTradePrice") is not None:
            prices[outcome] = float(m["lastTradePrice"])
    return prices or None


def _extract_volume(event: dict) -> float | None:
    try:
        vol = event.get("volume", 0) or event.get("volume24hr", 0) or 0
        return float(vol)
    except (ValueError, TypeError):
        return None


def _extract_resolution(event: dict) -> tuple[str, float | None]:
    markets = event.get("markets") or []
    for m in markets:
        outcome = m.get("groupItemTitle") or m.get("outcome", "Unknown")
        price_str = m.get("outcomePrices")
        if price_str:
            try:
                parsed = price_str if isinstance(price_str, list) else __import__("json").loads(price_str)
                price = float(parsed[0]) if parsed else None
            except (ValueError, TypeError, IndexError):
                price = None
            if price is not None and price > 0.9:
                return outcome, price
    return "Unknown", None
