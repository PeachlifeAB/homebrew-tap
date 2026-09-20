"""Host display recovery is selected at the platform boundary."""

from __future__ import annotations

import asyncio

import pytest

from lgtvctrl import composition, power
from lgtvctrl.display import LinuxDisplayRecovery


def test_linux_selects_an_explicit_wol_only_display_adapter(monkeypatch) -> None:
    monkeypatch.setattr(composition.platforms, "is_macos", lambda: False)
    monkeypatch.setattr(composition.platforms, "is_linux", lambda: True)

    assert isinstance(composition.display_recovery(), LinuxDisplayRecovery)


def test_linux_adapter_reports_the_unavailable_facility() -> None:
    recovery = LinuxDisplayRecovery()

    assert asyncio.run(recovery.available()) is False
    assert recovery.unavailable_message() == (
        "Host display recovery is unavailable on Linux; sent Wake-on-LAN only."
    )


def test_macos_selects_the_macos_display_adapter(monkeypatch) -> None:
    from lgtvctrl.macos_display import MacOSDisplayRecovery

    monkeypatch.setattr(composition.platforms, "is_macos", lambda: True)

    assert isinstance(composition.display_recovery(), MacOSDisplayRecovery)


def test_an_unknown_platform_fails_at_display_composition(monkeypatch) -> None:
    monkeypatch.setattr(composition.platforms, "is_macos", lambda: False)
    monkeypatch.setattr(composition.platforms, "is_linux", lambda: False)

    with pytest.raises(
        composition.UnsupportedPlatformError, match="host display recovery"
    ):
        composition.display_recovery()


def test_linux_power_on_sends_wol_without_host_display_calls(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(power, "load_config", lambda: {"mac": "00:11:22:33:44:55"})
    monkeypatch.setattr(power, "wol", lambda mac: calls.append(mac))

    asyncio.run(power.wakeup(LinuxDisplayRecovery()))

    assert calls == ["00:11:22:33:44:55"]
