"""sive runs unattended: every prompt is answered by a flag or names that flag.

Without a terminal (or with --no-input) a prompt never blocks and never
tracebacks. -y/--yes answers confirmations; --server, --email and
--password-stdin answer setup's questions.
"""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from sive import cli
from sive.core import ui


@pytest.fixture(autouse=True)
def fresh_prompt_settings():
    ui.configure()
    yield
    ui.configure()


@pytest.fixture
def no_terminal():
    with patch("sys.stdin.isatty", return_value=False):
        yield


@pytest.mark.usefixtures("no_terminal")
def test_input_without_a_terminal_names_the_flag_that_answers_it():
    with pytest.raises(ui.NonInteractiveError, match="--server"):
        ui.input("Server URL", flag="--server")


@pytest.mark.usefixtures("no_terminal")
def test_a_flag_answers_the_prompt_without_a_terminal():
    ui.configure(answers={"--email": "me@example.com"})

    assert ui.input("Email", flag="--email") == "me@example.com"


@pytest.mark.usefixtures("no_terminal")
def test_password_without_a_terminal_names_the_flag():
    with pytest.raises(ui.NonInteractiveError, match="--password-stdin"):
        ui.password("Master password", flag="--password-stdin")


@pytest.mark.usefixtures("no_terminal")
def test_yes_answers_a_confirmation_without_a_terminal():
    ui.configure(assume_yes=True)

    assert ui.confirm("Store master password?") is True


@pytest.mark.usefixtures("no_terminal")
def test_confirmation_without_yes_stops_instead_of_guessing():
    with pytest.raises(ui.NonInteractiveError, match="--yes"):
        ui.confirm("Store master password?")


def test_no_input_refuses_to_prompt_even_on_a_terminal():
    ui.configure(no_input=True)
    with (
        patch("sys.stdin.isatty", return_value=True),
        pytest.raises(ui.NonInteractiveError),
    ):
        ui.input("Email", flag="--email")


@pytest.mark.parametrize(
    "argv",
    [
        ["sive", "-y", "--no-input", "setup"],
        ["sive", "setup", "-y", "--no-input"],
    ],
)
def test_prompt_flags_work_before_or_after_the_command(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setitem(cli._COMMANDS, "setup", lambda _args: 0)
    with (
        patch("sive.core.credentials.ensure_unlocked"),
        pytest.raises(SystemExit),
    ):
        cli.main()

    assert ui.can_prompt() is False
    assert ui.confirm("Proceed?") is True


def test_setup_flags_become_prompt_answers(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "sive",
            "setup",
            "--server",
            "https://vw",
            "--email",
            "me@x",
            "--password-stdin",
        ],
    )
    monkeypatch.setattr("sys.stdin", _Stdin("hunter2\n"))
    monkeypatch.setitem(cli._COMMANDS, "setup", lambda _args: 0)
    with (
        patch("sive.core.credentials.ensure_unlocked"),
        pytest.raises(SystemExit),
    ):
        cli.main()

    assert ui.input("Server URL", flag="--server") == "https://vw"
    assert ui.input("Email", flag="--email") == "me@x"
    assert ui.password("Master password", flag="--password-stdin") == "hunter2"


def test_setup_without_a_terminal_exits_2_without_a_traceback(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "sive", "setup"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        timeout=30,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    assert "without a terminal" in result.stderr
    assert "Traceback" not in result.stderr


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text

    def isatty(self) -> bool:
        return False
