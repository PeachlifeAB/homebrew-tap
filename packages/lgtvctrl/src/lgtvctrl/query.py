"""Query TV settings via WebOsClient methods."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


async def picture(client: WebOsClient) -> None:
    """Get current picture settings.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Querying picture settings")
    settings = await client.get_picture_settings()
    logger.info("Retrieved picture settings")
    print(settings)


async def _get_system_settings_batch(
    client: WebOsClient,
    category: str,
    keys: list[str],
) -> dict[str, object]:
    """Fetch system settings for a specific category/key batch.

    bscpylgtv's get_picture_settings() uses the same SSAP endpoint underneath
    (com.webos.service.settings/getSystemSettings) and returns the "settings"
    field from the response.

    When probing unknown keys, some TVs reject the entire batch. Callers can use
    *_probe_* helpers to split the batch and isolate unsupported keys.
    """
    res = await client.get_system_settings(category, keys)

    if isinstance(res, dict) and isinstance(res.get("settings"), dict):
        return dict(res["settings"])

    if isinstance(res, dict):
        return dict(res)

    raise TypeError(f"Unexpected get_system_settings() response type: {type(res)}")


async def _get_picture_settings_batch(
    client: WebOsClient, keys: list[str]
) -> dict[str, object]:
    """Fetch picture settings for a specific key batch."""
    return await _get_system_settings_batch(client, "picture", keys)


async def _probe_system_settings(
    client: WebOsClient,
    category: str,
    keys: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    """Probe system settings keys, returning (settings, supported, unsupported)."""
    if not keys:
        return {}, [], []

    try:
        settings = await _get_system_settings_batch(client, category, keys)
        return settings, list(keys), []
    except (OSError, KeyError, TypeError, ValueError) as e:
        if len(keys) == 1:
            logger.debug("Key probe failed for %s/%s: %s", category, keys[0], e)
            return {}, [], keys

    split = len(keys) // 2
    left = keys[:split]
    right = keys[split:]

    left_settings, left_supported, left_unsupported = await _probe_system_settings(
        client, category, left
    )
    right_settings, right_supported, right_unsupported = await _probe_system_settings(
        client, category, right
    )

    merged = dict(left_settings)
    merged.update(right_settings)

    return (
        merged,
        [*left_supported, *right_supported],
        [*left_unsupported, *right_unsupported],
    )


async def _probe_picture_settings(
    client: WebOsClient, keys: list[str]
) -> tuple[dict[str, object], list[str], list[str]]:
    """Probe picture keys, returning (settings, supported_keys, unsupported_keys)."""
    return await _probe_system_settings(client, "picture", keys)


async def picture_all(client: WebOsClient) -> None:
    """Query a broader set of picture-related keys.

    This command probes settings under the SSAP system settings categories:
    - "picture" (traditional picture controls)
    - "other" (some models expose picture-adjacent toggles here)

    The TV may reject unknown keys, so probing is done by splitting key batches
    until unsupported keys are isolated.

    Note: Some models expose "darkMode" (and variants) under "picture", others
    under "other", and some under both. We probe both and return a consolidated
    output.
    """

    dark_mode_keys = [
        "darkMode",
        "darkModeLevel",
        "darkModeType",
        "darkModeState",
        "darkRoom",
        "darkRoomMode",
        "darkRoomLevel",
        "darkRoomSetting",
        "darkroom",
        "darkroomMode",
    ]

    picture_keys = [
        # Baseline picture parameters
        "pictureMode",
        "brightness",
        "contrast",
        "color",
        "backlight",
        "oledLight",
        # Some models expose "dark mode" controls as picture settings.
        *dark_mode_keys,
        # Common picture processing
        "gamma",
        "blackLevel",
        "dynamicContrast",
        "superResolution",
        "colorGamut",
        "peakBrightness",
        "localDimming",
        "motionEyeCare",
        "eyeComfortMode",
        "blueLightFilter",
        # Eco/AI related toggles (names vary a lot by model/year)
        "energySaving",
        "energySavingMode",
        "aiBrightness",
        "autoBrightness",
        "ambientLight",
        "adaptiveContrast",
        "autoDynamicContrast",
        # Misc
        "hdrDynamicToneMapping",
        "truMotionMode",
        "noiseReduction",
        "mpegNoiseReduction",
        "sharpness",
        "colorTemperature",
        "whiteBalance",
    ]

    # Some models expose the exact same keys via "other".
    other_keys = list(dark_mode_keys)

    logger.debug("Probing system settings (picture-all)")

    (
        picture_settings,
        picture_supported,
        picture_unsupported,
    ) = await _probe_system_settings(client, "picture", picture_keys)

    other_settings, other_supported, other_unsupported = await _probe_system_settings(
        client,
        "other",
        other_keys,
    )

    logger.info(
        "picture-all (picture) supported=%s unsupported=%s",
        len(picture_supported),
        len(picture_unsupported),
    )
    if picture_unsupported:
        logger.debug("picture-all (picture) unsupported keys: %s", picture_unsupported)

    logger.info(
        "picture-all (other) supported=%s unsupported=%s",
        len(other_supported),
        len(other_unsupported),
    )
    if other_unsupported:
        logger.debug("picture-all (other) unsupported keys: %s", other_unsupported)

    # Consolidate "picture"-relevant keys so callers don't have to know the
    # underlying SSAP category.
    consolidated_picture = dict(picture_settings)
    consolidated_picture.update(other_settings)

    print(
        {
            "picture": consolidated_picture,
            "raw": {"picture": picture_settings, "other": other_settings},
        }
    )


async def inputs(client: WebOsClient) -> None:
    """Get available inputs.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Querying available inputs")
    input_list = await client.get_inputs()
    count = len(input_list) if isinstance(input_list, list) else "unknown"
    logger.info(f"Retrieved {count} inputs")
    print(input_list)


async def apps(client: WebOsClient) -> None:
    """Get installed apps.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Querying installed apps")
    app_list = await client.get_apps_all(True)
    logger.info(
        f"Retrieved {len(app_list) if isinstance(app_list, list) else 'unknown'} apps"
    )
    print(app_list)


async def system(client: WebOsClient) -> None:
    """Get system information.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Querying system information")
    sys_info = await client.get_software_info(True)
    logger.info("Retrieved system information")
    print(sys_info)


async def update_status(client: WebOsClient) -> None:
    """Get firmware update status.

    Args:
        client: WebOsClient instance

    Raises:
        Exception: If command fails
    """
    logger.debug("Querying firmware update status")
    result = await client.request("com.webos.service.update/getStatus")
    logger.info("Retrieved firmware update status")
    print(result)


async def generic(client: WebOsClient, setting: str) -> None:
    """Execute generic query using get_<setting> method.

    Args:
        client: WebOsClient instance
        setting: Setting name to query (e.g., "brightness" → get_brightness())

    Raises:
        Exception: If command fails
    """
    method_name = f"get_{setting}"
    logger.debug(f"Attempting generic query: {method_name}")
    if hasattr(client, method_name):
        method = getattr(client, method_name)
        logger.debug(f"Calling method {method_name}")
        result = await method()
        logger.info(f"Generic query '{setting}' completed")
        print(result)
    else:
        available = "picture, picture-all, inputs, apps, system, update-status"
        logger.warning(f"Unknown query '{setting}' - method {method_name} not found")
        print(f"Error: Unknown query '{setting}'. Available: {available}")
