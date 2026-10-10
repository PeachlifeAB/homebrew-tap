"""Release gates: checks ordered cheapest first, stopping at the first failure.

Every product is released by the same ladder. A gate checks one thing and
changes nothing; the owners of each concern (the producer for the package, the
tap for the formula) contribute their gates and this module only orders and runs
them, so a failure that costs a second to find is never found after one that
costs a minute, and never after something public.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum

from ..domain.models import ReleaseError


class GateCost(IntEnum):
    """How long a gate takes; the ladder runs lower values first."""

    INSTANT = 0  # local git and files, no network
    SECONDS = 1  # one network call or a short subprocess
    MINUTES = 2  # test suites and builds


@dataclass(frozen=True)
class Gate:
    name: str
    cost: GateCost
    run: Callable[[], None]
    """Raises ReleaseError to fail; must not change the repository or remote."""


def run_gates(gates: Iterable[Gate], report: Callable[[str], None] = print) -> None:
    """Run gates cheapest first (ties keep declaration order), stopping at the
    first failure. The raised error names the failed gate and carries its message,
    so the caller prints one line instead of the ladder printing it a second time."""
    for gate in sorted(gates, key=lambda candidate: candidate.cost):
        try:
            gate.run()
        except ReleaseError as error:
            raise ReleaseError(f"{gate.name}: {error}") from error
        report(f"ok   {gate.name} ({gate.cost.name.lower()})")
