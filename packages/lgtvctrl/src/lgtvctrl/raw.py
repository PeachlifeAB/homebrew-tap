"""Raw command execution via WebOsClient methods."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


async def execute(client: WebOsClient, command: str, *args: Any) -> Any:
    """Execute an arbitrary WebOsClient method.

    Args:
        client: WebOsClient instance
        command: Method name to execute
        *args: Arguments to pass to the method

    Returns:
        Result from the WebOsClient method call

    Raises:
        AttributeError: If command method doesn't exist on client
        TypeError: If the resolved attribute isn't callable
        Exception: If command execution fails
    """
    logger.debug("Executing raw command: %s with args: %s", command, args)

    if not hasattr(client, command):
        raise AttributeError(
            f"WebOsClient has no method '{command}'. "
            "This may indicate a version mismatch with bscpylgtv."
        )

    # Prefer exec_func if available. This matches bscpylgtv's underlying API and
    # keeps behavior consistent across sync/async client implementations.
    if hasattr(client, "exec_func") and callable(client.exec_func):
        result = client.exec_func(command, *args)
        if inspect.isawaitable(result):
            return await result
        return result

    method = getattr(client, command)
    if not callable(method):
        raise TypeError(f"WebOsClient attribute '{command}' is not callable")

    result = method(*args)
    if inspect.isawaitable(result):
        return await result
    return result
