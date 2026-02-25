from __future__ import annotations

import httpx
import structlog

from polynotify.config import TelegramConfig

log = structlog.get_logger()

_API = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, config: TelegramConfig) -> None:
        self._token = config.bot_token
        self._chat_id = config.chat_id
        self._client = httpx.AsyncClient(timeout=15)

    async def send(self, message: str) -> None:
        resp = await self._client.post(
            f"{_API}/bot{self._token}/sendMessage",
            json={
                "chat_id": self._chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
        )
        resp.raise_for_status()
        log.debug("telegram_sent", chat_id=self._chat_id)

    async def close(self) -> None:
        await self._client.aclose()
