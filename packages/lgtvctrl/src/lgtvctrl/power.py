from __future__ import annotations

import asyncio
import logging
import socket
from typing import TYPE_CHECKING

from lgtvctrl.config import CONFIG_FILE, Config, read_json
from lgtvctrl.display import DisplayRecovery
from lgtvctrl.status import get_status
from lgtvctrl.webos import get_client

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

MAC_HEX_DIGITS = 12
RECOVERY_ATTEMPTS = 3


def load_config() -> dict:
    return read_json(CONFIG_FILE)


def wol(
    mac: str,
    bcast: str = "255.255.255.255",
    port: int = 9,
    bind_ip: str = "",
) -> None:
    mac_hex = mac.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(mac_hex) != MAC_HEX_DIGITS:
        raise ValueError("MAC must be 12 hex digits (e.g. 00:11:22:33:44:55)")

    packet = b"\xff" * 6 + bytes.fromhex(mac_hex) * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if bind_ip:
            sock.bind((bind_ip, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (bcast, port))


async def set_pc_input() -> bool:
    target_input = Config.get_tv_config().pc_input
    try:
        async with get_client() as client:
            await client.set_input(target_input)
            return True
    except OSError as error:  # ConnectionError and TimeoutError subclass it
        logger.debug("Input switch failed: %s", error)
        return False


async def _has_signal() -> bool:
    status = await get_status()
    return status.signal


async def recovery(display: DisplayRecovery) -> bool:
    await display.connect_all()
    await asyncio.sleep(2)

    if await _has_signal():
        return True

    if not await display.display_is_online():
        await display.sleep_and_nudge()
        await asyncio.sleep(2)

    if await _has_signal():
        return True

    await display.connect_all()

    if await _has_signal():
        return True

    await display.reinitialize()

    return await _has_signal()


async def wakeup(display: DisplayRecovery) -> None:
    cfg = load_config()
    mac = cfg.get("mac") or ""
    wol(mac)

    if not await display.available():
        logger.warning("%s", display.unavailable_message())
        return

    for attempt in range(1, RECOVERY_ATTEMPTS + 1):
        if await recovery(display):
            logger.debug("Display recovered successfully")
            return
        logger.debug("Display recovery failed, retrying... %s", attempt)
        await asyncio.sleep(2)


async def standby(client: WebOsClient) -> None:
    await client.power_off()
