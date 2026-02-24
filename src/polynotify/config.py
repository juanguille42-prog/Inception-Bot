from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.toml"


@dataclass
class GammaConfig:
    base_url: str = "https://gamma-api.polymarket.com"
    tag_id: int = 21
    fetch_limit: int = 100
    include_recurring: bool = False
    min_liquidity: float = 0
    tag_whitelist: list[str] = field(default_factory=list)


@dataclass
class AlertsConfig:
    closing_alert_hours: float = 2.0
    price_threshold: float = 0.15
    price_lookback_minutes: int = 60
    price_cooldown_minutes: int = 30
    volume_spike_multiplier: float = 3.0
    volume_lookback_minutes: int = 60
    volume_cooldown_minutes: int = 60


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class WhatsAppConfig:
    enabled: bool = False
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""
    to_number: str = ""


@dataclass
class Config:
    poll_interval_sec: int = 60
    db_path: str = "data/seen.db"
    log_level: str = "info"
    gamma: GammaConfig = field(default_factory=GammaConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)


def load_config(path: Path | None = None) -> Config:
    path = path or _DEFAULT_CONFIG
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    gamma_raw = raw.get("gamma", {})
    alerts_raw = raw.get("alerts", {})
    tg_raw = raw.get("telegram", {})
    wa_raw = raw.get("whatsapp", {})

    gamma = GammaConfig(**gamma_raw)
    alerts = AlertsConfig(**alerts_raw)

    # Telegram: overlay env vars
    telegram = TelegramConfig(
        enabled=tg_raw.get("enabled", False),
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )

    # WhatsApp: overlay env vars
    whatsapp = WhatsAppConfig(
        enabled=wa_raw.get("enabled", False),
        account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        from_number=os.environ.get("TWILIO_WHATSAPP_FROM", ""),
        to_number=os.environ.get("TWILIO_WHATSAPP_TO", ""),
    )

    return Config(
        poll_interval_sec=general.get("poll_interval_sec", 60),
        db_path=general.get("db_path", "data/seen.db"),
        log_level=general.get("log_level", "info"),
        gamma=gamma,
        alerts=alerts,
        telegram=telegram,
        whatsapp=whatsapp,
    )
