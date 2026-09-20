"""Select platform adapters at the application boundary."""

from __future__ import annotations

from lgtvctrl import platforms
from lgtvctrl.display import DisplayRecovery, LinuxDisplayRecovery


class UnsupportedPlatformError(RuntimeError):
    """The running platform has no host-display recovery adapter."""


def display_recovery() -> DisplayRecovery:
    """Construct the host-display recovery adapter for this platform."""
    if platforms.is_macos():
        from lgtvctrl.macos_display import MacOSDisplayRecovery

        return MacOSDisplayRecovery()
    if platforms.is_linux():
        return LinuxDisplayRecovery()
    raise UnsupportedPlatformError(
        f"host display recovery is unsupported on platform {platforms.sys.platform!r}"
    )
