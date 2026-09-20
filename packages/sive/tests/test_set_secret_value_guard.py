"""A missing value must fail loudly, including under `python -O`.

`assert` statements are stripped by -O, so an assert-guarded invariant would
let None reach the vault as a secret.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src/sive/commands/set_secret.py"


def test_value_invariant_is_not_guarded_by_assert() -> None:
    assert "assert value is not None" not in SOURCE.read_text(), (
        "python -O strips assert, so this guard disappears and None would be "
        "written to the vault as a secret"
    )


def test_guard_survives_optimised_bytecode() -> None:
    """-O must not change whether the invariant is enforced."""
    program = (
        "import ast,sys;"
        f"tree=ast.parse(open({str(SOURCE)!r}).read());"
        "asserts=[n for n in ast.walk(tree) if isinstance(n,ast.Assert)];"
        "sys.exit(1 if asserts else 0)"
    )
    result = subprocess.run([sys.executable, "-O", "-c", program], check=False)
    assert result.returncode == 0, "assert statements remain in set_secret.py"
