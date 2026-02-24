from __future__ import annotations

import asyncio

import structlog
from twilio.rest import Client

from polynotify.config import WhatsAppConfig

log = structlog.get_logger()


class WhatsAppNotifier:
    def __init__(self, config: WhatsAppConfig) -> None:
        self._client = Client(config.account_sid, config.auth_token)
        self._from = config.from_number
        self._to = config.to_number

    async def send(self, message: str) -> None:
        await asyncio.to_thread(
            self._client.messages.create,
            body=message,
            from_=self._from,
            to=self._to,
        )
        log.debug("whatsapp_sent", to=self._to)

    async def close(self) -> None:
        pass  # Twilio client has no async cleanup
