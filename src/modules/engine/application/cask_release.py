"""Checking a cask bump before it is committed.

A cask is generated and released by an upstream repository, so the tap neither
builds nor tags it. What the tap owns is the moment the generated file lands:
the bump must change only that file, name the version asked for, move the
version forward, pass `brew style`, and keep to the tap's supported platforms.

Every formula gate is either shared with a cask or skipped for one with a
recorded reason; a test fails when a new formula gate has neither.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..domain.models import CaskManifest, ReleaseError
from ..domain.platform_policy import intel_declarations
from .gates import Gate, GateCost, run_gates
from .observation import changed_paths, repository_state
from .ports import GitPort, ProcessPort
from .repository_gates import state_gates

# The tap's changelog, which holds one announcement line per cask bump.
ANNOUNCEMENT_FILE = "CHANGELOG.md"
ANNOUNCEMENT_HEADING = "## Casks"
EMPTY_ANNOUNCEMENTS = f"# Changelog\n\n{ANNOUNCEMENT_HEADING}\n"

# Formula gates a cask runs unchanged, by name.
CASK_SHARED_GATES = frozenset(
    {
        "no-dependabot-branches",
        "release-branch",
        "tracking-branch",
        "synced-with-remote",
    }
)

# Formula gates that do not apply to a cask, and why. Reported by every check.
CASK_SKIPPED_GATES = {
    "project-root-is-package": "a cask has no package",
    "clean-worktree": (
        "the generated cask is the change; only-the-cask-changed checks it"
    ),
    "version-increases": "cask-version compares the cask with its committed version",
    "tag-is-free": "the tap does not tag a cask; its upstream releases it",
    "github-release-is-free": "the tap publishes no release for a cask",
    "reviewed-notes": "a cask is announced by one line linking its upstream notes",
    "publish-workflow-present": "a cask has no formula pull request or bottles",
    "brew-style-clean": "brew-style-cask checks the cask file",
    "sdist-builds-and-verifies": "a cask ships no source distribution",
    "quality-task": "a cask has no package tests",
}

_VERSION_LINE = re.compile(r'^\s*version\s+"([^"]+)"', re.MULTILINE)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _declared_version(cask_source: str) -> str | None:
    match = _VERSION_LINE.search(cask_source)
    return match.group(1) if match else None


class CaskRelease:
    def __init__(
        self,
        manifest: CaskManifest,
        tap_root: Path,
        process: ProcessPort,
        git: GitPort,
        watched_remotes: tuple[str, ...] = (),
    ) -> None:
        self.manifest = manifest
        self.tap_root = tap_root.resolve()
        self.process = process
        self.git = git
        self.watched_remotes = watched_remotes

    @property
    def cask_file(self) -> Path:
        return self.tap_root / self.manifest.path

    def gates(self, version: str) -> tuple[Gate, ...]:
        """The checks a cask bump runs, cheapest first."""
        state = repository_state(self.git, self.tap_root, self.watched_remotes)
        own: tuple[tuple[str, GateCost, Callable[[], None]], ...] = (
            (
                "only-the-cask-changed",
                GateCost.INSTANT,
                lambda: self._only_the_cask_changed(state.dirty),
            ),
            ("cask-version", GateCost.INSTANT, lambda: self._version(version)),
            ("cask-announced", GateCost.INSTANT, lambda: self._announced(version)),
            ("no-intel-declared", GateCost.INSTANT, self._no_intel_declared),
            ("brew-style-cask", GateCost.SECONDS, self._brew_style),
        )
        return (
            *state_gates(state),
            *(Gate(name, cost, run) for name, cost, run in own),
        )

    def check(self, version: str, report: Callable[[str], None] = print) -> None:
        """Say which formula gates a cask skips, then run the ones that apply."""
        for gate, reason in CASK_SKIPPED_GATES.items():
            report(f"skip {gate} (cask: {reason})")
        run_gates(self.gates(version), report=report)

    def _only_the_cask_changed(self, dirty: tuple[str, ...]) -> None:
        owned = {self.manifest.path, ANNOUNCEMENT_FILE}
        others = [path for path in changed_paths(dirty) if path not in owned]
        if others:
            raise ReleaseError(
                f"paths other than {self.manifest.path} and {ANNOUNCEMENT_FILE} "
                f"changed: {', '.join(others)}"
            )

    def _announcement_line(self, version: str) -> str:
        link = self.manifest.release_notes_url(version)
        return f"- {self.manifest.name} {version}: {link}"

    def _announcement_text(self) -> str:
        path = self.tap_root / ANNOUNCEMENT_FILE
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def announce(self, version: str) -> str:
        """Put the version's line at the top of the Casks section, once."""
        line = self._announcement_line(version)
        text = self._announcement_text() or EMPTY_ANNOUNCEMENTS
        if line in text.splitlines():
            return line
        if ANNOUNCEMENT_HEADING not in text:
            text = f"{text.rstrip()}\n\n{ANNOUNCEMENT_HEADING}\n\n"
        text = text.replace(
            f"{ANNOUNCEMENT_HEADING}\n\n", f"{ANNOUNCEMENT_HEADING}\n\n{line}\n", 1
        )
        (self.tap_root / ANNOUNCEMENT_FILE).write_text(text, encoding="utf-8")
        return line

    def _announced(self, version: str) -> None:
        line = self._announcement_line(version)
        if line not in self._announcement_text().splitlines():
            raise ReleaseError(
                f"{ANNOUNCEMENT_FILE} has no line for {self.manifest.name} {version}; "
                f"run: notes {version}"
            )

    def _committed_version(self) -> str | None:
        source = self.git.output(
            ["show", f"HEAD:{self.manifest.path}"], cwd=self.tap_root
        )
        return _declared_version(source)

    def _version(self, requested: str) -> None:
        declared = _declared_version(self.cask_file.read_text(encoding="utf-8"))
        if declared != requested:
            raise ReleaseError(
                f"{self.manifest.path} declares {declared}, "
                f"not the requested {requested}"
            )
        committed = self._committed_version()
        if committed is not None and _version_tuple(requested) <= _version_tuple(
            committed
        ):
            raise ReleaseError(f"release version {requested} must exceed {committed}")

    def _no_intel_declared(self) -> None:
        declared = intel_declarations(self.cask_file.read_text(encoding="utf-8"))
        if declared:
            raise ReleaseError(
                f"{self.manifest.path} declares Intel support: {', '.join(declared)}"
            )

    def _brew_style(self) -> None:
        code, output = self.process.try_run(
            ["brew", "style", str(self.cask_file)], cwd=self.tap_root
        )
        if code != 0:
            raise ReleaseError(f"brew style reported offenses:\n{output.strip()}")
