"""Which host facilities are available.

Named here rather than compared inline so the macOS-only paths are findable
when the ports behind them land: several of these surfaces are slated to grow
Linux equivalents, and each is one call site to change.
"""

from __future__ import annotations

import sys

MACOS = "darwin"
LINUX = "linux"


def is_macos() -> bool:
    return sys.platform == MACOS


def is_linux() -> bool:
    return sys.platform.startswith(LINUX)
