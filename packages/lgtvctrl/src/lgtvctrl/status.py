"""TV status helpers (power + input signal)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lgtvctrl.config import Config
from lgtvctrl.webos import get_client

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TVStatus:
    on: bool
    state: str
    input: str | None
    signal: bool


# WebSocket close 1008 is "Policy Violation"; webOS sends it while the TV is
# still booting and phrases the reason "try again later" -- the wording of
# 1013, not of 1008. Libraries surface it as a code or only as text, so both
# are matched.
WS_POLICY_VIOLATION = 1008
WS_POLICY_VIOLATION_TEXT = "policy violation"
WS_RETRY_TEXT = "try again later"

# webOS reports a powered-on panel as this power state.
POWER_STATE_ON = "Active"


def _is_policy_violation(exc: BaseException) -> bool:
    """True when the TV refused the connection because it is still starting."""
    if getattr(exc, "code", None) == WS_POLICY_VIOLATION:
        return True

    text = str(exc).lower()
    matched_code = str(WS_POLICY_VIOLATION) in text or WS_POLICY_VIOLATION_TEXT in text
    return matched_code and WS_RETRY_TEXT in text


async def _fetch_once(target_input: str | None) -> TVStatus:
    async with get_client() as client:
        power: Mapping[str, Any] = await client.get_power_state()
        log.debug("%r", power)

        raw_state = power.get("state") or "unknown"
        is_on = raw_state == POWER_STATE_ON

        inputs = await client.get_inputs()
        log.debug("%r", inputs)

        matched = None
        if target_input:
            matched = next(
                (
                    inp
                    for inp in inputs
                    if inp.get("id") == target_input or inp.get("label") == target_input
                ),
                None,
            )
        log.debug("%r", matched)

        signal = bool(matched.get("hdmiSignalExist", False)) if matched else False

    status = TVStatus(
        on=is_on,
        state=str(raw_state).lower(),
        input=target_input,
        signal=signal,
    )
    log.debug("%r", status)
    return status


async def get_status() -> TVStatus:
    target_input = Config.get_tv_config().pc_input
    log.debug("%r", target_input)

    try:
        return await _fetch_once(target_input)
    except Exception as exc:
        if not _is_policy_violation(exc):
            raise

        log.debug("%r", exc)
        await asyncio.sleep(2)
        return await _fetch_once(target_input)
