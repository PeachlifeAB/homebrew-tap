"""TV input helpers and input switching."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def input_label(item: dict[str, Any]) -> str | None:
    value = item.get("label")
    if isinstance(value, str) and value:
        return value

    value = item.get("_label")
    if isinstance(value, str) and value:
        return value

    return None


def resolve_input_id(inputs: object, target: str) -> str | None:
    if not isinstance(inputs, list) or not isinstance(target, str) or not target:
        return None

    for item in inputs:
        if isinstance(item, dict) and item.get("id") == target:
            return target

    for item in inputs:
        if not isinstance(item, dict):
            continue
        if input_label(item) == target:
            value = item.get("id")
            return value if isinstance(value, str) and value else None

    return None


async def switch_input(client: WebOsClient, input_id: str) -> None:
    logger.debug("Setting input to %s", input_id)
    await client.set_input(input_id)
    logger.info("Switched to input %s", input_id)


async def switch_to_favorite(client: WebOsClient, favorite_input: str) -> None:
    await switch_input(client, favorite_input)


async def list_inputs(client: WebOsClient) -> Any:
    logger.debug("Fetching available inputs")
    inputs = await client.get_inputs()
    logger.info(
        "Found %s inputs", len(inputs) if isinstance(inputs, list) else "unknown"
    )
    return inputs
