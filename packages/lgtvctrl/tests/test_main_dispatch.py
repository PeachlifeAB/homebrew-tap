"""main_async routes commands; these pin its behaviour before decomposition.

main_async is 129 lines at cognitive complexity 65/15. These cover the paths
reachable without a TV so the refactor can be checked rather than trusted.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lgtvctrl import main as main_module


def test_no_command_prints_help() -> None:
    assert asyncio.run(main_module.main_async([])) == 0


def test_help_command_needs_no_client() -> None:
    assert asyncio.run(main_module.main_async(["help"])) == 0


def test_parser_exposes_subcommands() -> None:
    parser = main_module.create_parser()
    assert any(getattr(action, "choices", None) for action in parser._actions), (
        "parser exposes no subcommands"
    )


def test_missing_action_is_validated_behind_a_connection() -> None:
    """Recorded shape, not an endorsement: `dim` without an action is rejected
    only inside `async with get_client()`, so argument validation sits behind a
    network connection. A future decomposition should move it ahead of that.

    Asserted by substituting the client: reaching a real TV would make the
    suite depend on the network, and the point is that the connection is
    attempted at all.
    """
    connected = False

    @asynccontextmanager
    async def fake_client() -> AsyncIterator[object]:
        nonlocal connected
        connected = True
        yield object()

    with mock.patch.object(main_module, "get_client", fake_client):
        asyncio.run(main_module.main_async(["dim"]))

    assert connected, "argument validation ran before the client connected"


def test_every_subcommand_binds_a_handler() -> None:
    """set_defaults binds handler and client-need to the subparser, so the
    mapping cannot drift from the registered subcommands."""
    parser = main_module.create_parser()
    subparsers = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )
    unbound = [
        name
        for name, sub in subparsers.choices.items()
        if name != "help" and sub.get_default("func") is None
    ]
    assert not unbound, f"subcommands with no handler: {unbound}"


def test_client_need_is_declared_per_subcommand() -> None:
    parser = main_module.create_parser()
    subparsers = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )
    for name, sub in subparsers.choices.items():
        if name == "help":
            continue
        assert isinstance(sub.get_default("needs_client"), bool), (
            f"{name} does not declare needs_client"
        )
