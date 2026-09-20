"""Host-display recovery port and the Linux adapter."""

from __future__ import annotations

from typing import Protocol


class DisplayRecovery(Protocol):
    """Recover the host display after the TV wakes."""

    async def available(self) -> bool: ...

    def unavailable_message(self) -> str: ...

    async def connect_all(self) -> None: ...

    async def display_is_online(self) -> bool: ...

    async def sleep_and_nudge(self) -> None: ...

    async def reinitialize(self) -> bool: ...


class LinuxDisplayRecovery:
    """Linux has no portable host-display recovery facility."""

    async def available(self) -> bool:
        return False

    def unavailable_message(self) -> str:
        return "Host display recovery is unavailable on Linux; sent Wake-on-LAN only."

    async def connect_all(self) -> None:
        return None

    async def display_is_online(self) -> bool:
        return False

    async def sleep_and_nudge(self) -> None:
        return None

    async def reinitialize(self) -> bool:
        return False
