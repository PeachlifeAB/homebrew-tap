"""Brightness control for LG TV.

Implements 3-tier brightness control:
- Tier 1 (levels 1-33): Adjusts brightness parameter (40-55 hardware range)
- Tier 2 (levels 34-67): Adjusts contrast parameter (0-90 hardware range)
- Tier 3 (levels 68-100): Adjusts panel-light parameter (0-100 hardware range)

Level 0 is reserved and treated as 1.

Tier boundaries are inclusive on the lower end:
- 1 ≤ level ≤ 33 → Tier 1
- 34 ≤ level ≤ 67 → Tier 2
- 68 ≤ level ≤ 100 → Tier 3
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


# Hardware ranges for brightness parameters
BRIGHTNESS_RANGES = {
    "brightness": {"min": 1, "max": 55},
    "contrast": {"min": 0, "max": 90},
    "backlight": {"min": 0, "max": 100},
    "color": {"min": 42, "max": 55},
}

# The panel-light setting is named per panel type: LCD models expose
# "backlight", OLED models "oledLight", and reject the other name.
PANEL_LIGHT_LCD = "backlight"
PANEL_LIGHT_OLED = "oledLight"

# Each tier drives one hardware parameter across its full range while the
# others sit at an end stop, so the three together span level 1..100.
BRIGHTNESS_TIER_1_MAX = 33
BRIGHTNESS_TIER_2_MAX = 67

# darkMode dims below what the picture settings alone can reach. The two
# dimming modes were tuned separately and do not share thresholds.
DARK_MODE_DYNAMIC_LEVEL2_MAX = 40
DARK_MODE_DYNAMIC_LEVEL1_MAX = 70
DARK_MODE_SIMPLE_LEVEL2_BELOW = 30
DARK_MODE_SIMPLE_LEVEL1_BELOW = 70

# The midpoint of the color range: dynamic mode sets it explicitly so a
# previous manual adjustment does not tint the result.
NEUTRAL_COLOR = 50

APPLY_VERIFY_RETRIES = 5
APPLY_VERIFY_DELAY_SECONDS = 0.2


async def get_picture_settings_and_panel_key(
    client: WebOsClient,
) -> tuple[Mapping[str, object], str]:
    """Fetch picture settings and return the correct panel-light key.

    Some TVs reject unknown/unsupported keys (e.g. LCD models reject "oledLight").
    We probe using the SSAP getSystemSettings keys list and fall back if needed.
    """

    try:
        settings_raw = await client.get_picture_settings(
            keys=["contrast", "backlight", "brightness", "color"]
        )
        if isinstance(settings_raw, Mapping) and PANEL_LIGHT_LCD in settings_raw:
            return settings_raw, PANEL_LIGHT_LCD
    except TypeError:
        settings_raw = await client.get_picture_settings()
        if isinstance(settings_raw, Mapping):
            if PANEL_LIGHT_OLED in settings_raw:
                return settings_raw, PANEL_LIGHT_OLED
            return settings_raw, PANEL_LIGHT_LCD
    except (OSError, KeyError, ValueError):
        # TypeError is handled above. Older models reject the call or answer in
        # another shape; the explicit-key request below is the fallback.
        pass

    settings_raw = await client.get_picture_settings(
        keys=["contrast", "oledLight", "brightness", "color"]
    )
    if isinstance(settings_raw, Mapping) and PANEL_LIGHT_OLED in settings_raw:
        return settings_raw, PANEL_LIGHT_OLED

    return settings_raw, PANEL_LIGHT_LCD


def parse_picture_settings(output: str) -> dict[str, int]:
    """Parse picture settings from WebOsClient.get_picture_settings() output.

    The WebOsClient returns a dict, but for string output (from debugging/logging),
    this function extracts values using regex to handle various formats.

    Note: Some TVs expose panel light as "backlight" while OLED models often use
    "oledLight". This parser normalizes both to the returned "backlight" key.

    Args:
        output: String representation of picture settings dict

    Returns:
        Dict with keys: backlight, brightness, contrast (all 0-100).
        Missing keys default to 0.

    Examples:
        >>> parse_picture_settings("{'backlight': 50, 'brightness': 47}")
        {'backlight': 50, 'brightness': 47, 'contrast': 0}
        >>> parse_picture_settings("{'oledLight': 80, 'brightness': 50}")
        {'backlight': 80, 'brightness': 50, 'contrast': 0}
    """
    backlight = 0
    brightness = 0
    contrast = 0

    # backlight on LCD panels, oledLight on OLED; either gives the same value.
    if match := re.search(r"['\"](?:backlight|oledLight)['\"]:\s*(\d+)", output):
        backlight = int(match.group(1))

    if match := re.search(r"['\"]brightness['\"]:\s*(\d+)", output):
        brightness = int(match.group(1))
    if match := re.search(r"['\"]contrast['\"]:\s*(\d+)", output):
        contrast = int(match.group(1))

    return {
        "backlight": backlight,
        "brightness": brightness,
        "contrast": contrast,
    }


def estimate_current_level(settings: dict[str, int]) -> int:
    """Estimate current brightness level (1-100) from picture settings.

    Three-tier mapping:
    - Level 1-33: Maps to brightness parameter (40-55)
    - Level 33-67: Maps to contrast parameter (0-90)
    - Level 67-100: Maps to panel light parameter (backlight/oledLight, 0-100)

    Args:
        settings: Dict with brightness/contrast and either backlight or oledLight.
            (Values are expected to be 0-100, as returned by the TV API.)

    Returns:
        Estimated brightness level 1-100

    Raises:
        ValueError: If settings dict is missing required keys
    """
    required_keys = {"brightness", "contrast"}
    missing = required_keys - settings.keys()
    if missing:
        raise ValueError(
            f"Missing required keys in settings: {missing}. "
            f"Got keys: {set(settings.keys())}"
        )

    if PANEL_LIGHT_LCD in settings:
        panel_light = settings[PANEL_LIGHT_LCD]
    elif PANEL_LIGHT_OLED in settings:
        panel_light = settings[PANEL_LIGHT_OLED]
    else:
        raise ValueError(
            "Missing required panel light key in settings "
            "(expected 'backlight' or 'oledLight'). "
            f"Got keys: {set(settings.keys())}"
        )

    brightness = settings["brightness"]
    contrast = settings["contrast"]
    ranges = BRIGHTNESS_RANGES

    if brightness <= ranges["brightness"]["min"]:
        return 1

    if brightness < ranges["brightness"]["max"]:
        level = (
            (brightness - ranges["brightness"]["min"])
            * 33.0
            / (ranges["brightness"]["max"] - ranges["brightness"]["min"])
        )
        return max(1, round(level))

    if contrast < ranges["contrast"]["max"]:
        level = 33 + (
            (contrast - ranges["contrast"]["min"])
            * 34.0
            / (ranges["contrast"]["max"] - ranges["contrast"]["min"])
        )
        return round(level)

    level = 67 + (
        (panel_light - ranges["backlight"]["min"])
        * 33.0
        / (ranges["backlight"]["max"] - ranges["backlight"]["min"])
    )
    return round(level)


def interpolate(range_dict: dict[str, int], value: int, max_value: int) -> int:
    """Interpolate a value into a hardware range.

    Args:
        range_dict: Dict with 'min' and 'max' keys
        value: Value to interpolate (0 to max_value)
        max_value: Maximum value for interpolation scale

    Returns:
        Interpolated hardware value
    """
    return round(
        range_dict["min"] + (range_dict["max"] - range_dict["min"]) * value / max_value
    )


def apply_brightness_level(level: int) -> dict[str, int]:
    """Convert brightness level (1-100) to hardware parameters.

    Returns the three hardware parameters needed for set_current_picture_settings:
    - Level 1-33: Set brightness parameter, keep contrast/backlight at min
    - Level 33-67: Set contrast parameter, max brightness, min backlight
    - Level 67-100: Set backlight parameter, max brightness/contrast

    Args:
        level: Brightness level 1-100 (0 is accepted but treated as 1)

    Returns:
        Dict with keys: backlight, contrast, brightness
    """
    # Clamp level to valid range.
    # We treat 0 as reserved and use 1 as the minimum user level.
    level = max(1, min(100, level))
    ranges = BRIGHTNESS_RANGES

    if level <= BRIGHTNESS_TIER_1_MAX:
        # Tier 1: Adjust brightness parameter
        # Map user levels 1..33 to brightness min..max.
        return {
            "backlight": ranges["backlight"]["min"],
            "contrast": ranges["contrast"]["min"],
            "brightness": interpolate(ranges["brightness"], level - 1, 32),
        }

    if level <= BRIGHTNESS_TIER_2_MAX:
        # Tier 2: Adjust contrast parameter
        # Map user levels 34..67 to contrast min..max.
        return {
            "backlight": ranges["backlight"]["min"],
            "contrast": interpolate(ranges["contrast"], level - 34, 33),
            "brightness": ranges["brightness"]["max"],
        }

    # Tier 3: Adjust backlight/oledLight parameter
    # Map user levels 68..100 to backlight min..max.
    return {
        "backlight": interpolate(ranges["backlight"], level - 68, 32),
        "contrast": ranges["contrast"]["max"],
        "brightness": ranges["brightness"]["max"],
    }


def get_dark_mode_for_level_dynamic(level: int) -> str:
    """Get darkMode setting for legacy dynamic dimming (3-tier).

    darkMode provides additional dimming below what picture settings can achieve:
    - Level 0-40: darkMode "level2" (darkest)
    - Level 41-70: darkMode "level1"
    - Level 71-100: darkMode "off"

    Args:
        level: Brightness level (legacy behavior treats 0 as 1)

    Returns:
        darkMode value: "off", "level1", or "level2"
    """
    if level <= DARK_MODE_DYNAMIC_LEVEL2_MAX:
        return "level2"
    if level <= DARK_MODE_DYNAMIC_LEVEL1_MAX:
        return "level1"
    return "off"


def get_dark_mode_for_level_simple(level: int) -> str:
    """Get darkMode setting for simple dimming.

    Thresholds:
    - Level 0-29: darkMode "level2" (darkest)
    - Level 30-69: darkMode "level1"
    - Level 70-100: darkMode "off"
    """
    if level < DARK_MODE_SIMPLE_LEVEL2_BELOW:
        return "level2"
    if level < DARK_MODE_SIMPLE_LEVEL1_BELOW:
        return "level1"
    return "off"


def panel_light_value_for_level(level: int) -> int:
    """Map level 0-100 to panel light value 0-100 (linear)."""
    level = max(0, min(100, level))
    return interpolate(BRIGHTNESS_RANGES["backlight"], level, 100)


def estimate_level_from_panel_light(value: int) -> int:
    """Inverse of panel_light_value_for_level (approx).

    The backlight range spans the same 0-100 as the level, so the inverse is
    the clamp alone.
    """
    return max(0, min(100, value))


async def _detect_panel_light_key(
    client: WebOsClient,
) -> tuple[Mapping[str, object], str]:
    settings_raw, panel_light_key = await get_picture_settings_and_panel_key(client)
    available_keys = (
        sorted(settings_raw.keys()) if isinstance(settings_raw, Mapping) else []
    )
    logger.debug(
        "Detected picture panel light key: %s (available keys: %s)",
        panel_light_key,
        ",".join(available_keys),
    )
    return settings_raw, panel_light_key


async def _write_picture_settings(
    client: WebOsClient, params: dict[str, int], dark_mode: str
) -> None:
    await client.set_other_settings({"darkMode": dark_mode})
    if hasattr(client, "set_system_settings"):
        await client.set_system_settings("picture", params)
    else:
        await client.set_current_picture_settings(params)


async def _verify_applied(
    client: WebOsClient, keys: list[str], panel_light_key: str, expected: int
) -> object | None:
    """Poll until the TV reports the panel light we asked for, or retries run out.

    The set call returns before the panel has moved, so a read straight after it
    still shows the old value.
    """
    updated: object | None = None
    for _ in range(APPLY_VERIFY_RETRIES):
        await asyncio.sleep(APPLY_VERIFY_DELAY_SECONDS)
        try:
            try:
                updated = await client.get_picture_settings(keys=keys)
            except TypeError:
                updated = await client.get_picture_settings()
        except (OSError, KeyError, ValueError):
            logger.debug("Failed to read picture settings after apply", exc_info=True)
            break

        if isinstance(updated, Mapping) and updated.get(panel_light_key) == expected:
            break
    return updated


async def apply_level_dynamic(client: WebOsClient, level: int) -> None:
    """Legacy apply: 3-tier (brightness/contrast/panel light) + color + darkMode."""
    logger.debug("Applying brightness level %s (dynamic)", level)

    # Clamp to legacy 1-100 range (0 treated as 1)
    level = max(1, min(100, level))

    _, panel_light_key = await _detect_panel_light_key(client)

    params = apply_brightness_level(level)
    panel_light_value = params.pop(PANEL_LIGHT_LCD)
    params[panel_light_key] = panel_light_value
    params["color"] = NEUTRAL_COLOR

    dark_mode = get_dark_mode_for_level_dynamic(level)
    logger.debug(
        "Setting picture params: brightness=%s, contrast=%s, %s=%s, color=%s, "
        "darkMode=%s",
        params.get("brightness"),
        params.get("contrast"),
        panel_light_key,
        panel_light_value,
        NEUTRAL_COLOR,
        dark_mode,
    )

    await _write_picture_settings(client, params, dark_mode)

    keys = ["contrast", panel_light_key, "brightness", "color"]
    updated = await _verify_applied(client, keys, panel_light_key, panel_light_value)

    logger.debug("Picture settings after apply: %s", updated)
    logger.info("Brightness set to %s (dynamic)", level)


async def apply_level_simple(client: WebOsClient, level: int) -> None:
    """Simple apply: only panel light + darkMode."""
    logger.debug("Applying brightness level %s (simple)", level)

    level = max(0, min(100, level))

    _, panel_light_key = await _detect_panel_light_key(client)

    panel_light_value = panel_light_value_for_level(level)
    params = {panel_light_key: panel_light_value}

    dark_mode = get_dark_mode_for_level_simple(level)
    logger.debug(
        "Setting picture params: %s=%s, darkMode=%s",
        panel_light_key,
        panel_light_value,
        dark_mode,
    )

    await _write_picture_settings(client, params, dark_mode)

    updated = await _verify_applied(
        client, [panel_light_key], panel_light_key, panel_light_value
    )

    logger.debug("Picture settings after apply: %s", updated)
    logger.info("Brightness set to %s (simple)", level)


async def increase(client: WebOsClient, amount: int, *, dynamic: bool = False) -> None:
    """Increase brightness by specified amount."""
    logger.debug("Increasing brightness by %s (dynamic=%s)", amount, dynamic)
    settings_raw, panel_light_key = await get_picture_settings_and_panel_key(client)

    settings: dict[str, int] = {
        k: int(v) for k, v in settings_raw.items() if v is not None
    }

    if dynamic:
        current = estimate_current_level(settings)
        new_level = min(100, max(1, current + amount))
        logger.info("Setting brightness to %s (was %s, dynamic)", new_level, current)
        await apply_level_dynamic(client, new_level)
        return

    current_panel_light = int(settings.get(panel_light_key, 0))
    current = estimate_level_from_panel_light(current_panel_light)
    new_level = min(100, max(0, current + amount))
    logger.info("Setting brightness to %s (was %s, simple)", new_level, current)
    await apply_level_simple(client, new_level)


async def decrease(client: WebOsClient, amount: int, *, dynamic: bool = False) -> None:
    """Decrease brightness by specified amount."""
    logger.debug("Decreasing brightness by %s (dynamic=%s)", amount, dynamic)
    settings_raw, panel_light_key = await get_picture_settings_and_panel_key(client)

    settings: dict[str, int] = {
        k: int(v) for k, v in settings_raw.items() if v is not None
    }

    if dynamic:
        current = estimate_current_level(settings)
        new_level = max(1, current - amount)
        logger.info("Setting brightness to %s (was %s, dynamic)", new_level, current)
        await apply_level_dynamic(client, new_level)
        return

    current_panel_light = int(settings.get(panel_light_key, 0))
    current = estimate_level_from_panel_light(current_panel_light)
    new_level = max(0, current - amount)
    logger.info("Setting brightness to %s (was %s, simple)", new_level, current)
    await apply_level_simple(client, new_level)


async def get_level(client: WebOsClient, *, dynamic: bool = False) -> int:
    """Get current brightness level.

    Behavior:
    - dynamic=False: estimate from the panel light key (backlight/oledLight),
      returns 0-100
    - dynamic=True: estimate from the legacy 3-tier picture settings,
      returns 1-100

    Prints:
        "Brightness: <value>"

    Returns:
        Current brightness level.
    """

    settings_raw, panel_light_key = await get_picture_settings_and_panel_key(client)
    settings: dict[str, int] = {
        k: int(v) for k, v in settings_raw.items() if v is not None
    }

    if dynamic:
        current = estimate_current_level(settings)
    else:
        current_panel_light = int(settings.get(panel_light_key, 0))
        current = estimate_level_from_panel_light(current_panel_light)

    print(f"Brightness: {current}")
    return current
