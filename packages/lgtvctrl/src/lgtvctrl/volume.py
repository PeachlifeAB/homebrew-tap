"""Volume control for LG TV."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

UP = "up"
DOWN = "down"


async def _get_sound_output(client: WebOsClient) -> str | None:
    try:
        sound_output = await client.get_sound_output()
    except (OSError, KeyError, TypeError, ValueError):
        # Older models do not report sound output; treat it as unknown.
        return None

    return sound_output if isinstance(sound_output, str) else None


def _is_external_sound_output(sound_output: str | None) -> bool:
    if not sound_output:
        return False

    # Values vary by model/firmware. Observed examples include:
    # - tv_speaker
    # - external_arc
    return sound_output not in {"tv_speaker", "internal_tv_speaker"}


async def _warn_if_external_sound_output(client: WebOsClient) -> str | None:
    """Warn when sound output is external (ARC/soundbar/etc).

    When output is external, LG's absolute volume get/set may not control the
    external device's audible volume.

    Returns the sound output string if available.
    """

    sound_output = await _get_sound_output(client)

    if _is_external_sound_output(sound_output):
        print(
            f"Warning: sound output is {sound_output}; volume get/set may not "
            "change the external speakers volume.",
            file=sys.stderr,
        )

    return sound_output


def _clamp_volume(volume: int) -> int:
    return max(0, min(100, volume))


async def _step_external(client: WebOsClient, *, direction: str, amount: int) -> None:
    """External audio reports no level, so step blindly and report the action."""
    step_fn = client.volume_up if direction == UP else client.volume_down
    for _ in range(amount):
        await step_fn()
    suffix = f" x{amount}" if amount > 1 else ""
    print(f"Volume: {direction}{suffix}")


async def _set_internal(client: WebOsClient, *, direction: str, amount: int) -> None:
    """Internal speakers report a level, so read it and set the target directly.

    A single step uses the TV's own command; larger changes set the level
    outright rather than sending repeated steps.
    """
    before = int(await client.get_volume())
    delta = amount if direction == UP else -amount
    target = _clamp_volume(before + delta)

    if target == before:
        print(f"Volume: {before} -> {before}")
        return

    if amount > 1:
        logger.debug("Setting volume to %s (was %s)", target, before)
        await client.set_volume(target)
        after = target
    else:
        logger.debug("Sending volume %s step", direction)
        await (client.volume_up() if direction == UP else client.volume_down())
        after = int(await client.get_volume())

    print(f"Volume: {before} -> {after}")


async def _set_relative_volume(
    client: WebOsClient,
    *,
    direction: str,
    amount: int,
) -> None:
    if direction not in {UP, DOWN}:
        raise ValueError(f"direction must be {UP!r} or {DOWN!r}")
    if amount < 1:
        raise ValueError("amount must be >= 1")

    sound_output = await _get_sound_output(client)
    if _is_external_sound_output(sound_output):
        await _step_external(client, direction=direction, amount=amount)
        return
    await _set_internal(client, direction=direction, amount=amount)


async def volume_up(client: WebOsClient, amount: int = 1) -> None:
    """Increase volume by amount.

    Behavior:
    - amount=1: uses the TV's step command
    - amount>1: reads current volume and uses set_volume() to avoid spamming steps

    Prints: "Volume: <before> -> <after>".
    """

    await _set_relative_volume(client, direction=UP, amount=amount)


async def volume_down(client: WebOsClient, amount: int = 1) -> None:
    """Decrease volume by amount.

    Behavior:
    - amount=1: uses the TV's step command
    - amount>1: reads current volume and uses set_volume() to avoid spamming steps

    Prints: "Volume: <before> -> <after>".
    """

    await _set_relative_volume(client, direction=DOWN, amount=amount)


async def volume_set(client: WebOsClient, level: int) -> None:
    """Set volume to an absolute level (0-100).

    Prints: "Volume: <before> -> <after>".
    """

    await _warn_if_external_sound_output(client)
    before = int(await client.get_volume())
    target = _clamp_volume(level)

    if target == before:
        print(f"Volume: {before} -> {before}")
        return

    logger.debug("Setting volume to %s (was %s)", target, before)
    await client.set_volume(target)
    print(f"Volume: {before} -> {target}")


async def volume_get(client: WebOsClient) -> int:
    """Get current volume.

    Prints: "Volume: <value>".

    Returns:
        Current volume level (0-100).
    """

    await _warn_if_external_sound_output(client)
    current = int(await client.get_volume())
    print(f"Volume: {current}")
    return current
