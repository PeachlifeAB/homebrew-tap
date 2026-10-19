from __future__ import annotations

import io

import pytest

from sive import cli
from sive.commands import set_secret
from sive.core import credentials, ui


class TerminalInput(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    "mode", ["argument", "pipe", "stdin", "terminal", "empty", "eof"]
)
def test_secret_input_reaches_public_write_command(
    monkeypatch, authentication, capsys, mode
):
    arguments = ["sive", "set", authentication.vault_name]
    if mode == "argument":
        arguments.append(authentication.password)
    if mode == "stdin":
        arguments.append("--stdin")
    stream_type = TerminalInput if mode in {"terminal", "eof"} else io.StringIO
    stream = stream_type("" if mode == "empty" else authentication.password)
    monkeypatch.setattr(cli.sys, "argv", arguments)
    monkeypatch.setattr(cli.sys, "stdin", stream)
    monkeypatch.setattr(credentials, "ensure_unlocked", lambda: True)
    captured_values = []

    def store(key, value, **kwargs):
        captured_values.append(value)
        return 0

    def password(*args, **kwargs):
        if mode == "eof":
            raise EOFError
        return authentication.password

    monkeypatch.setattr(set_secret, "run", store)
    monkeypatch.setattr(ui, "password", password)
    try:
        with pytest.raises(SystemExit) as result:
            cli.main()
        failing = mode in {"empty", "eof"}
        assert result.value.code == int(failing)
        assert captured_values == ([] if failing else [authentication.password])
        assert authentication.password not in capsys.readouterr().err
    finally:
        ui.configure()
