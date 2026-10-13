"""Verify package metadata and CLI version behavior."""

from __future__ import annotations

import re
import subprocess
import sys
from importlib.metadata import version


def test_version_comes_from_distribution_metadata():
    from sive import __version__

    assert __version__ == version("sive")


def test_version_flag_via_cli():
    from sive import __version__

    result = subprocess.run(
        [sys.executable, "-m", "sive", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    assert output.startswith(f"sive {__version__}")


def test_development_checkout_may_include_its_commit_hash():
    from sive import __version__

    result = subprocess.run(
        [sys.executable, "-m", "sive", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()

    assert re.fullmatch(rf"sive {re.escape(__version__)}( \([0-9a-f]+\))?", output)


def test_cli_import_does_not_load_distribution_metadata():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import sive.cli; "
                "assert 'importlib.metadata' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
