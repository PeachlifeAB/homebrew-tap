"""macOS adapter for BetterDisplay and host-display recovery."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import replace

from lgtvctrl import betterdisplay
from lgtvctrl.config import Config

logger = logging.getLogger(__name__)
LG_DISPLAY_MARKER = "LG TV"


class MacOSDisplayRecovery:
    """Recover a Mac-connected LG display after Wake-on-LAN."""

    async def available(self) -> bool:
        return await asyncio.to_thread(betterdisplay.api_ready)

    def unavailable_message(self) -> str:
        return (
            "BetterDisplay HTTP API not reachable — skipping display recovery. "
            "Enable it in BetterDisplay → Settings → Advanced → "
            f"Enable HTTP API (port {betterdisplay.DEFAULT_HTTP_PORT})."
        )

    async def connect_all(self) -> None:
        try:
            await asyncio.to_thread(betterdisplay.perform, "connectAllDisplays")
        except betterdisplay.BetterDisplayError as error:
            logger.debug("connectAllDisplays failed: %s", error)

    async def display_is_online(self) -> bool:
        return await asyncio.to_thread(self._display_is_online)

    async def sleep_and_nudge(self) -> None:
        await asyncio.to_thread(self._sleep_displays)
        await asyncio.to_thread(self._nudge, 1)

    async def reinitialize(self) -> bool:
        if not await self.available():
            await asyncio.to_thread(betterdisplay.try_start_betterdisplay)
            await asyncio.sleep(2)

        uuid = await asyncio.to_thread(self._lg_display_uuid)
        if not uuid:
            logger.debug("No UUID available (not in BetterDisplay API or config)")
            return False

        try:
            await asyncio.to_thread(betterdisplay.perform, f"UUID={uuid}&reinitialize")
        except betterdisplay.BetterDisplayError as error:
            logger.debug("BetterDisplay reinit failed with UUID %s: %s", uuid, error)
            return False
        logger.debug("Display reinitialized via BetterDisplay using UUID: %s", uuid)
        return True

    @staticmethod
    def _nudge(seconds: int) -> None:
        subprocess.run(["caffeinate", "-u", "-d", "-t", str(seconds)], check=False)

    @staticmethod
    def _sleep_displays() -> None:
        subprocess.run(["pmset", "displaysleepnow"], check=False)

    @staticmethod
    def _display_is_online() -> bool:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            check=False,
        )
        detected = LG_DISPLAY_MARKER in result.stdout
        logger.debug(
            "Display reports HDMI signal %s", "online" if detected else "offline"
        )
        return detected

    @staticmethod
    def _remember_uuid(previous: str, uuid: str) -> None:
        logger.info("LG display UUID changed: %s -> %s", previous, uuid)
        replace(Config.get_tv_config(), uuid=uuid).save()
        Config.clear_cache()

    def _lg_display_uuid(self) -> str:
        last_known_uuid = Config.get_tv_config().uuid or ""
        uuid = self._first_lg_display_uuid()
        if uuid:
            if uuid != last_known_uuid:
                self._remember_uuid(last_known_uuid, uuid)
            return uuid
        if last_known_uuid:
            logger.debug("Using last known UUID from config: %s", last_known_uuid)
        return last_known_uuid

    @staticmethod
    def _first_lg_display_uuid() -> str:
        try:
            return MacOSDisplayRecovery._first_matching_lg_uuid(
                betterdisplay.get_all_displays()
            )
        except betterdisplay.BetterDisplayError as error:
            logger.debug("Failed to query BetterDisplay API: %s", error)
            return ""

    @staticmethod
    def _first_matching_lg_uuid(displays: list[dict[str, object]]) -> str:
        for display in displays:
            uuid = str(display.get("UUID", ""))
            if not uuid:
                continue
            if str(display.get("productName", "")).startswith("LG"):
                return uuid
        return ""
