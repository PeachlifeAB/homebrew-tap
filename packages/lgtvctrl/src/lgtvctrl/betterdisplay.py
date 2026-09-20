"""BetterDisplay HTTP API client for display identifiers.

Fetches display identifiers for caching and reference.
See docs/betterdisplay-api.md for API reference.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from lgtvctrl import platforms
from lgtvctrl.config import IDENTIFIERS_CACHE_FILE, STATE_DIR

logger = logging.getLogger(__name__)

# BetterDisplay's HTTP API, off by default: Settings > Advanced > Enable HTTP API.
DEFAULT_HTTP_PORT = 55777

# urllib reports a refused connection only in the reason text.
CONNECTION_REFUSED = "Connection refused"
# BetterDisplay sometimes answers with concatenated top-level objects
# rather than a JSON array; this is the seam between them.
OBJECT_SEPARATOR = "},{"


class BetterDisplayError(Exception):
    """Base exception for BetterDisplay API errors."""


class BetterDisplayNotRunning(BetterDisplayError):
    """BetterDisplay is not running or HTTP API is disabled."""


class DisplayNotFound(BetterDisplayError):
    """No display matched the configured identifiers."""


def try_start_betterdisplay() -> bool:
    """Best-effort start of BetterDisplay (macOS only).

    Returns True if we attempted to launch BetterDisplay.

    Important: this does NOT guarantee the HTTP API is enabled; callers should
    retry the API call after a short delay.
    """
    if not platforms.is_macos():
        return False

    try:
        # Prefer `open -a BetterDisplay` (works for /Applications installs).
        subprocess.run(
            ["open", "-a", "BetterDisplay"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _utc_now_iso() -> str:
    """Return current UTC time as ISO string with milliseconds."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _url(command: str, http_port: int = DEFAULT_HTTP_PORT) -> str:
    return f"http://localhost:{http_port}/command/{command}"


def _http_get(url: str, timeout: float = 5.0) -> str:
    """Perform HTTP GET and return response body as string.

    Every caller builds its URL from a hardcoded ``http://localhost`` literal
    with only an integer port interpolated, so no caller-supplied scheme can
    reach urlopen here. Contrast auth.py, where the URL arrives in an SSDP
    header and is validated.

    Raises:
        BetterDisplayNotRunning: Connection refused (app not running)
        BetterDisplayError: Other HTTP/network errors
    """
    try:
        with urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as e:
        raise BetterDisplayError(f"HTTP {e.code}: {e.reason}") from e
    except URLError as e:
        if CONNECTION_REFUSED in str(e.reason):
            raise BetterDisplayNotRunning(
                "BetterDisplay not running or HTTP API disabled"
            ) from e
        raise BetterDisplayError(f"Network error: {e.reason}") from e


def _parse_identifiers_response(body: str) -> list[dict[str, Any]]:
    """Parse the /command/get?identifiers response.

    BetterDisplay returns valid JSON in some versions/settings, but we have
    observed it also returning *concatenated JSON objects* like:

        { ...display... },{ ...displayGroup... }

    i.e. multiple top-level JSON objects without a surrounding list.

    This parser accepts:
    - a JSON array
    - a single JSON object
    - concatenated objects (wrapped into a list)
    """
    if not body or not body.strip():
        return []

    raw = body.strip()

    def _normalize(parsed: Any) -> list[dict[str, Any]]:
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict):
            return [parsed]
        return []

    try:
        return _normalize(json.loads(raw))
    except json.JSONDecodeError:
        pass

    # Fallback: BetterDisplay sometimes returns concatenated objects.
    # We only attempt wrapping when it *starts* and *ends* as an object.
    if raw.startswith("{") and raw.endswith("}") and OBJECT_SEPARATOR in raw:
        wrapped = f"[{raw}]"
        try:
            return _normalize(json.loads(wrapped))
        except json.JSONDecodeError as e:
            logger.warning(
                "[%s] Failed to parse identifiers (concatenated objects): %s",
                _utc_now_iso(),
                e,
            )
            return []

    logger.warning(
        "[%s] Failed to parse identifiers JSON (unknown format)",
        _utc_now_iso(),
    )
    return []


def get_all_displays(http_port: int = DEFAULT_HTTP_PORT) -> list[dict[str, Any]]:
    """Fetch all connected displays from BetterDisplay.

    Returns list of display dicts with UUID, productName, vendor, model, serial, etc.
    """
    body = _http_get(_url("get?identifiers", http_port))
    return _parse_identifiers_response(body)


def api_ready(http_port: int = DEFAULT_HTTP_PORT, timeout: float = 1.0) -> bool:
    """Whether the HTTP API answers. False when BetterDisplay is not running."""
    try:
        _http_get(_url("get?identifiers", http_port), timeout=timeout)
    except BetterDisplayError:
        return False
    return True


def perform(
    command: str, http_port: int = DEFAULT_HTTP_PORT, timeout: float = 5.0
) -> None:
    """Issue a /command/perform action, e.g. "connectAllDisplays"."""
    _http_get(_url(f"perform?{command}", http_port), timeout=timeout)


def refresh_identifiers_cache(http_port: int = DEFAULT_HTTP_PORT) -> None:
    """Fetch and cache display identifiers atomically.

    This is fire-and-forget: it logs failures but doesn't raise exceptions.
    Always writes a list, even if BetterDisplay returns concatenated objects.
    """
    try:
        displays = get_all_displays(http_port=http_port)
        # Ensure we're writing a list
        if not isinstance(displays, list):
            displays = [displays] if isinstance(displays, dict) else []

        cache_data = {"cached_at": _utc_now_iso(), "displays": displays}

        # Create state directory if it doesn't exist
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file, then rename
        with tempfile.NamedTemporaryFile(
            mode="w", dir=STATE_DIR, delete=False, suffix=".json.tmp"
        ) as tmp:
            json.dump(cache_data, tmp, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_path = tmp.name

        # Atomic rename
        os.replace(temp_path, IDENTIFIERS_CACHE_FILE)

        logger.info(
            "[%s] Cached %d display identifiers to %s",
            _utc_now_iso(),
            len(displays),
            IDENTIFIERS_CACHE_FILE,
        )

    except (BetterDisplayError, OSError, TypeError) as e:
        logger.warning(
            "[%s] Failed to cache display identifiers: %s",
            _utc_now_iso(),
            e,
        )
        # Non-fatal: BetterDisplay might not be running


def load_cached_identifiers() -> list[dict[str, Any]]:
    """Load cached display identifiers.

    Returns empty list if cache doesn't exist or is invalid.
    """
    if not IDENTIFIERS_CACHE_FILE.exists():
        return []

    try:
        data = json.loads(IDENTIFIERS_CACHE_FILE.read_text())
        displays = data.get("displays", [])
        if isinstance(displays, list):
            return displays
        return []
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "[%s] Failed to load cached identifiers from %s: %s",
            _utc_now_iso(),
            IDENTIFIERS_CACHE_FILE,
            e,
        )
        return []
