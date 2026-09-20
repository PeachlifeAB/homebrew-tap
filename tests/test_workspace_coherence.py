"""The root pyproject is the single source of truth for workspace-wide settings.

PEP 621 forbids a dynamic or inherited `requires-python`: it is baked into each
built wheel, so a package installed standalone from Homebrew must carry its own
literal copy. These tests make the duplication safe by failing on drift.
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PYPROJECTS = sorted((ROOT / "packages").glob("*/pyproject.toml"))


def _load(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text())


class WorkspaceCoherenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(PACKAGE_PYPROJECTS, "no packages found to check")

    def test_every_package_declares_the_root_python_floor(self) -> None:
        expected = _load(ROOT / "pyproject.toml")["project"]["requires-python"]
        for path in PACKAGE_PYPROJECTS:
            with self.subTest(package=path.parent.name):
                self.assertEqual(
                    _load(path)["project"]["requires-python"],
                    expected,
                    "package python floor drifted from the root pyproject",
                )

    def test_every_package_uses_the_src_layout(self) -> None:
        """A flat layout puts the package on sys.path during a test run, so a
        test imports the working tree whether or not the install is correct —
        the same shape as a version assertion that passes on the wrong build.
        It also rules out the uv_build backend, which requires src/<name>/.
        """
        for path in PACKAGE_PYPROJECTS:
            package = path.parent
            with self.subTest(package=package.name):
                self.assertTrue(
                    (package / "src" / package.name).is_dir(),
                    f"{package.name} must live in src/{package.name}/",
                )
                self.assertFalse(
                    (package / package.name).is_dir(),
                    f"{package.name} still has a flat {package.name}/ directory",
                )

    def test_the_root_distribution_declares_no_console_script(self) -> None:
        """The root is a workspace container, not something anyone installs.

        Per the PyPA entry-points specification, "install tools are expected to
        set up wrappers for both `console_scripts` and `gui_scripts` in the
        scripts directory of the install scheme" — so a script entry point is
        dormant metadata until an installer processes the distribution. Homebrew
        installs the three products as their own distributions and the release
        engine is invoked as `bin/release`, by path, so nothing ever installs
        this one. `uv init` wrote a `homebrew-tap = "homebrew_tap:main"` entry
        pointing at a `print("Hello from homebrew-tap!")` placeholder, which
        made a stub the root's only advertised command.
        """
        root = _load(ROOT / "pyproject.toml")
        self.assertNotIn(
            "scripts",
            root["project"],
            "the root distribution is never installed, so a console script "
            "entry point cannot produce a command; invoke bin/release by path",
        )
        self.assertFalse(
            (ROOT / "src" / "homebrew_tap").exists(),
            "src/homebrew_tap/ is the uv init placeholder; nothing imports it",
        )

    def test_no_package_shadows_the_root_ruff_config(self) -> None:
        """Ruff resolves config from the nearest pyproject with a [tool.ruff]
        section, so a package-level one silently exempts that package from the
        workspace ruleset."""
        for path in PACKAGE_PYPROJECTS:
            with self.subTest(package=path.parent.name):
                self.assertNotIn(
                    "ruff",
                    _load(path).get("tool", {}),
                    "package [tool.ruff] shadows the root ruleset",
                )
