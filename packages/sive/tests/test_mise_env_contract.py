"""
Tests for the _mise-env output contract.

The contract is strict: even on failure, stdout must be valid JSON ({})
and exit code must be 0. Shell startup must never be broken.

_mise-env reads per-tag encrypted snapshots only — no live bw calls.
Tags are declared in order; last tag wins on key conflict.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import call, patch

from sive.commands.mise_env import run

# ---------------------------------------------------------------------------
# Happy path — snapshot present, stdout is valid JSON env map, exit 0
# ---------------------------------------------------------------------------


def test_run_prints_json_on_success(capsys):
    env_vars = {"ANTHROPIC_API_KEY": "sk-xxx", "GITHUB_TOKEN": "ghp-yyy"}
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value=env_vars),
    ):
        exit_code = run(["global"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == env_vars


def test_run_returns_exit_0_on_success():
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value={"FOO": "bar"}),
    ):
        assert run(["global"]) == 0


def test_run_empty_snapshot_returns_empty_json(capsys):
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value={}),
    ):
        exit_code = run(["global"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {}


# ---------------------------------------------------------------------------
# Failure contract — stdout is '{}', stderr has one warning, exit 0
# ---------------------------------------------------------------------------


def test_run_missing_snapshot_returns_empty_json_and_warns(capsys):
    with patch("sive.commands.mise_env.snapshot_exists", return_value=False):
        exit_code = run(["global"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {}
    assert "sive:" in captured.err
    assert "sive setup" in captured.err


def test_run_unreadable_snapshot_returns_empty_json_and_warns(capsys):
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value=None),
    ):
        exit_code = run(["global"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {}
    assert "sive:" in captured.err


def test_run_no_stack_trace_on_failure(capsys):
    with patch("sive.commands.mise_env.snapshot_exists", return_value=False):
        run(["global"])

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_run_stdout_is_valid_json_on_missing_snapshot(capsys):
    with patch("sive.commands.mise_env.snapshot_exists", return_value=False):
        run(["global"])

    captured = capsys.readouterr()
    assert isinstance(json.loads(captured.out), dict)


# ---------------------------------------------------------------------------
# Per-tag reads and merging
# ---------------------------------------------------------------------------


def test_run_reads_each_declared_tag(capsys):
    """_mise-env reads one snapshot per declared tag."""
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value={}) as mock_read,
    ):
        run(["global", "myproject"])

    assert mock_read.call_args_list == [
        call("personal", "global"),
        call("personal", "myproject"),
    ]


def test_run_empty_tags_returns_empty_json(capsys):
    with patch("sive.commands.mise_env.active_tags", return_value=[]) as mock_tags:
        exit_code = run([])
    captured = capsys.readouterr()
    mock_tags.assert_called_once()
    assert exit_code == 0
    assert json.loads(captured.out) == {}
    assert captured.err == ""


def test_run_merges_tags_last_wins(capsys):
    """Later tags override earlier tags on key conflict."""

    def fake_read(vault, tag):
        if tag == "global":
            return {"SHARED_KEY": "from_global", "GLOBAL_ONLY": "g"}
        if tag == "myproject":
            return {"SHARED_KEY": "from_myproject", "PROJECT_ONLY": "p"}
        return {}

    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", side_effect=fake_read),
    ):
        run(["global", "myproject"])

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["SHARED_KEY"] == "from_myproject"
    assert result["GLOBAL_ONLY"] == "g"
    assert result["PROJECT_ONLY"] == "p"


def test_run_missing_tag_warns_but_continues(capsys):
    """A missing tag snapshot emits a warning but other tags still load."""

    def fake_exists(vault, tag):
        return tag != "missing"

    def fake_read(vault, tag):
        return {"PRESENT_KEY": "val"}

    with (
        patch("sive.commands.mise_env.snapshot_exists", side_effect=fake_exists),
        patch("sive.commands.mise_env.read_snapshot", side_effect=fake_read),
    ):
        exit_code = run(["global", "missing"])

    captured = capsys.readouterr()
    assert exit_code == 0
    result = json.loads(captured.out)
    assert result["PRESENT_KEY"] == "val"
    assert "missing" in captured.err


def test_run_exception_returns_empty_json_and_warns(capsys):
    with patch("sive.commands.mise_env.active_tags", side_effect=RuntimeError("boom")):
        exit_code = run([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {}
    assert "error reading snapshots" in captured.err


# ---------------------------------------------------------------------------
# Shell output. The hook runs inside `mise hook-env`, where PATH is led by
# mise's shim directory: an interpreter resolved through PATH is a shim that
# re-enters mise and re-sources the hook, forking without bound. sive is
# already a Python process, so it emits the exports itself.
# ---------------------------------------------------------------------------

HOOK_SCRIPT = (
    Path(__file__).resolve().parents[1] / "src" / "sive" / "mise_hook" / "env.sh"
)

# One value per shell construct that must not execute or truncate.
HOSTILE_ENV = {
    "APOSTROPHE": "it's here",
    "SUBSHELL": "$(touch /tmp/sive-pwned)",
    "BACKTICK": "`touch /tmp/sive-pwned`",
    "BACKSLASH": "back\\slash",
    "NEWLINE": "line1\nline2",
    "DQUOTE": 'say "hi"',
    "DOLLAR": "$HOME and ${PATH}",
    "SEMICOLON": "a; touch /tmp/sive-pwned",
}


def test_hook_resolves_no_interpreter_through_path():
    """A PATH-resolved interpreter in the hook is a mise shim, and recurses."""
    for line in HOOK_SCRIPT.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        assert "python" not in stripped


def test_sh_format_emits_shell_assignments(capsys):
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value={"FOO": "bar"}),
    ):
        assert run(["global"], output_format="sh") == 0

    assert capsys.readouterr().out.strip() == "export FOO=bar"


def test_sh_format_survives_every_shell_construct(capsys):
    """Each hostile value must round-trip verbatim, executing nothing."""
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value=HOSTILE_ENV),
    ):
        run(["global"], output_format="sh")

    exports = capsys.readouterr().out
    probe = "; ".join(f'printf "%s\\0" "${k}"' for k in HOSTILE_ENV)
    result = subprocess.run(
        ["sh", "-c", f"{exports}\n{probe}"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert not Path("/tmp/sive-pwned").exists()
    assert result.stdout.split("\0")[: len(HOSTILE_ENV)] == list(HOSTILE_ENV.values())


def test_json_remains_the_default(capsys):
    """The documented contract is JSON; --format=sh is opt-in."""
    with (
        patch("sive.commands.mise_env.snapshot_exists", return_value=True),
        patch("sive.commands.mise_env.read_snapshot", return_value={"FOO": "bar"}),
    ):
        run(["global"])

    assert json.loads(capsys.readouterr().out) == {"FOO": "bar"}
