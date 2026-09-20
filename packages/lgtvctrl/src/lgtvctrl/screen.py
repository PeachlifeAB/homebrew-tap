"""Screen power control for LG TV."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


async def turn_on(client: WebOsClient) -> None:
    """Turn screen on using the TV's native screen power endpoint.

    Uses the com.webos.service.tvpower/power/turnOnScreen endpoint
    which properly restores the screen and updates power state.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Turning screen on via turnOnScreen endpoint")
    await client.turn_screen_on()
    logger.info("Screen turned on")


async def turn_off(client: WebOsClient) -> None:
    """Turn screen off using the TV's native screen power endpoint.

    Uses the com.webos.service.tvpower/power/turnOffScreen endpoint
    which properly blanks the screen and updates power state to 'Screen Off'.
    The TV remains connected and responsive to commands.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Turning screen off via turnOffScreen endpoint")
    await client.turn_screen_off()
    logger.info("Screen turned off")


async def get_state(client: WebOsClient) -> dict:
    """Get current screen state from power state endpoint.

    Returns the power state which includes screen state information.
    When screen is off, state will be 'Screen Off'.
    When screen is on, state will be 'Active'.

    Args:
        client: WebOsClient instance

    Returns:
        dict with 'state' key (e.g., 'Active', 'Screen Off')
        and 'screen_on' boolean for convenience

    Raises:
        Exception: If query fails
    """
    logger.debug("Getting screen state via getPowerState endpoint")
    power_state = await client.get_power_state()
    state = power_state.get("state", "Unknown")
    screen_on = state not in ("Screen Off", "Screen Saver")

    return {
        "state": state,
        "screen_on": screen_on,
        "raw": power_state,
    }
