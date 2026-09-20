"""WebOS client connection helpers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from lgtvctrl.config import KEYFILE_PATH, Config

if TYPE_CHECKING:
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]


@asynccontextmanager
async def get_client() -> AsyncGenerator[WebOsClient, None]:
    tv = Config.get_tv_config()

    if not KEYFILE_PATH.exists():
        raise ConnectionError(f"Missing keyfile: {KEYFILE_PATH}. Run 'tv auth'.")

    client_key = Config.extract_client_key(str(KEYFILE_PATH), tv.ip)
    if not client_key:
        raise ConnectionError(f"No client key for {tv.ip}. Run 'tv auth'.")

    # Imported at call time, not module scope: only an actual connection needs
    # the TV client, so the module stays importable without it installed.
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

    client = await WebOsClient.create(
        ip=tv.ip,
        client_key=client_key,
        timeout_connect=Config.TIMEOUT,
        ping_interval=None,
        states=[],
    )

    try:
        await client.connect()
        yield client
    finally:
        try:
            await client.disconnect()
        except OSError:
            # Already tearing the connection down.
            pass
