from __future__ import annotations

import structlog
from aiogram import Bot

from polynotify.config import TelegramConfig

log = structlog.get_logger()


class TelegramNotifier:
    def __init__(self, config: TelegramConfig) -> None:
        self._bot = Bot(token=config.bot_token)
        self._chat_id = config.chat_id

    async def send(self, message: str) -> None:
        await self._bot.send_message(
            chat_id=self._chat_id,
            text=message,
            disable_web_page_preview=True,
        )
        log.debug("telegram_sent", chat_id=self._chat_id)

    async def close(self) -> None:
        await self._bot.session.close()
