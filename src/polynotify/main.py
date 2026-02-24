from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import httpx
import structlog

from polynotify.config import load_config
from polynotify.monitor import Monitor
from polynotify.notify.base import Notifier
from polynotify.notify.formatter import format_alert
from polynotify.store import Store

log = structlog.get_logger()


async def main() -> None:
    config = load_config()

    # Structlog setup
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            {"debug": 10, "info": 20, "warning": 30, "error": 40}.get(
                config.log_level, 20
            )
        ),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    # Ensure data dir exists
    db_dir = Path(config.db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    store = Store(config.db_path)
    notifiers: list[Notifier] = _build_notifiers(config)

    if not notifiers:
        log.warning("no_notifiers_enabled", hint="Enable telegram or whatsapp in config")

    shutdown = asyncio.Event()

    def _handle_signal() -> None:
        log.info("shutdown_requested")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    transport = httpx.AsyncHTTPTransport(retries=3)
    async with httpx.AsyncClient(transport=transport, timeout=30) as client:
        monitor = Monitor(config, store, client)
        log.info("started", poll_interval=config.poll_interval_sec, notifiers=len(notifiers))

        while not shutdown.is_set():
            try:
                alerts = await monitor.poll()
                log.info("poll_cycle", alerts=len(alerts))

                for alert in alerts:
                    msg = format_alert(alert)
                    sent = False
                    for notifier in notifiers:
                        try:
                            await notifier.send(msg)
                            sent = True
                        except Exception:
                            log.exception(
                                "notifier_failed",
                                notifier=type(notifier).__name__,
                                alert_type=alert.type,
                            )
                    # Record alert after at least one successful send
                    if sent:
                        store.record_alert(alert.event["id"], alert.type)
                        log.info(
                            "alert_sent",
                            type=alert.type,
                            event=alert.event.get("title", ""),
                        )

            except Exception:
                log.exception("poll_error")

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=config.poll_interval_sec)
            except TimeoutError:
                pass

    # Cleanup
    for notifier in notifiers:
        try:
            await notifier.close()
        except Exception:
            pass
    store.close()
    log.info("shutdown_complete")


def _build_notifiers(config) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if config.telegram.enabled:
        from polynotify.notify.telegram import TelegramNotifier

        notifiers.append(TelegramNotifier(config.telegram))
        log.info("telegram_enabled")
    if config.whatsapp.enabled:
        from polynotify.notify.whatsapp import WhatsAppNotifier

        notifiers.append(WhatsAppNotifier(config.whatsapp))
        log.info("whatsapp_enabled")
    return notifiers


def cli() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
