"""Best-effort code paths must name the exceptions they tolerate.

`except Exception: pass` also swallows genuine bugs - a typo, an AttributeError
- and hides them behind a silent fallback. bandit B110 stops flagging a
suppression once the exception type is narrowed.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    path
    for path in [*ROOT.glob("src/**/*.py"), *ROOT.glob("packages/*/**/*.py")]
    if ".venv" not in path.parts and "/tests/" not in str(path)
)


def _bare_except_pass(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        catches_everything = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id == "Exception"
        )
        body_is_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
        if catches_everything and body_is_pass:
            lines.append(node.lineno)
    return lines


def test_no_broad_except_pass_in_source() -> None:
    offenders = {
        str(path.relative_to(ROOT)): _bare_except_pass(
            ast.parse(path.read_text(encoding="utf-8"))
        )
        for path in SOURCES
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"broad except-pass remains: {offenders}"
