from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    async def send(self, message: str) -> None: ...

    async def close(self) -> None: ...
