"""The bandit subprocess suppression in .qlty/qlty.toml rests on two
invariants. If either breaks, the suppression is no longer earned, so they are
asserted here rather than trusted.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    path
    for path in ROOT.glob("packages/**/*.py")
    if ".venv" not in path.parts and "build" not in path.parts
)

SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}


def _subprocess_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in SPAWNERS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]


class SubprocessPolicyTests(unittest.TestCase):
    def test_no_package_uses_shell_true(self) -> None:
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _subprocess_calls(tree):
                for keyword in call.keywords:
                    if keyword.arg == "shell":
                        self.assertNotEqual(
                            getattr(keyword.value, "value", None),
                            True,
                            f"{path.relative_to(ROOT)} passes shell=True",
                        )

    def test_every_command_is_a_list_literal(self) -> None:
        """A string command line would be parsed by the shell."""
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _subprocess_calls(tree):
                if not call.args:
                    continue
                first = call.args[0]
                is_string = isinstance(first, ast.JoinedStr) or (
                    isinstance(first, ast.Constant) and isinstance(first.value, str)
                )
                self.assertFalse(
                    is_string,
                    f"{path.relative_to(ROOT)}:{call.lineno} passes a string command",
                )

    def test_every_release_command_is_bounded(self) -> None:
        """A release runs binaries it just built. Unbounded, a hung one stops
        the release forever instead of failing it."""
        adapter = ROOT / "src/modules/engine/infrastructure/adapters.py"
        tree = ast.parse(adapter.read_text(encoding="utf-8"))
        calls = _subprocess_calls(tree)
        self.assertTrue(calls, "no subprocess calls found to check")
        for call in calls:
            self.assertIn(
                "timeout",
                [keyword.arg for keyword in call.keywords],
                f"adapters.py:{call.lineno} runs a command with no time bound",
            )


class SubprocessTimeoutTests(unittest.TestCase):
    """The bound is enforced, not merely declared."""

    def test_a_command_that_never_exits_fails_the_release(self) -> None:
        from modules.engine.domain.models import CommandFailed
        from modules.engine.infrastructure.adapters import SubprocessAdapter

        with self.assertRaises(CommandFailed) as raised:
            SubprocessAdapter().run(["sleep", "30"], cwd=ROOT, timeout_seconds=0.25)
        self.assertIn("no exit within", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
