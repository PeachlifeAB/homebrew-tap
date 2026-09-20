"""power.py must reach BetterDisplay through the adapter, not raw urllib.

The adapter owns the port literal, the typed errors, and a JSON parser that
handles BetterDisplay's concatenated-object responses. A second hand-rolled
client in power.py drifted from all three, and its blocking urlopen calls sat
inside async functions where they stall the event loop.
"""

from __future__ import annotations

import ast
from pathlib import Path

POWER = Path(__file__).resolve().parents[1] / "src" / "lgtvctrl" / "power.py"
TREE = ast.parse(POWER.read_text())


def _imported_modules() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_power_does_not_import_platform_adapters_directly() -> None:
    forbidden = {
        "lgtvctrl.betterdisplay",
        "lgtvctrl.macos_display",
        "subprocess",
        "urllib.error",
        "urllib.request",
    }
    assert forbidden.isdisjoint(_imported_modules())


def test_power_does_not_hardcode_the_betterdisplay_port() -> None:
    assert "55777" not in POWER.read_text()


def test_async_functions_make_no_blocking_calls() -> None:
    blocking = {"urlopen", "run", "Popen", "sleep"}
    for node in ast.walk(TREE):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in blocking:
                # asyncio.sleep is the non-blocking one.
                prefix = getattr(getattr(fn, "value", None), "id", "")
                assert prefix == "asyncio", (
                    f"{node.name} calls blocking {prefix}.{name}"
                )


def test_wakeup_gives_up_after_a_bounded_number_of_attempts() -> None:
    """`attempts` was compared but never incremented, so a display that never
    recovered left `tv power on` looping forever."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from lgtvctrl import power

    display = AsyncMock()
    display.available.return_value = True
    with (
        patch.object(power, "load_config", return_value={"mac": "00:11:22:33:44:55"}),
        patch.object(power, "wol"),
        patch.object(power, "recovery", return_value=False) as never_recovers,
        patch.object(power.asyncio, "sleep", return_value=None),
    ):
        asyncio.run(power.wakeup(display))

    assert never_recovers.call_count == power.RECOVERY_ATTEMPTS
