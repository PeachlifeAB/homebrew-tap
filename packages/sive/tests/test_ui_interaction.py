from __future__ import annotations

import io
import subprocess

import pytest

from sive.core import ui


class TerminalInput(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def interactive_terminal(monkeypatch):
    monkeypatch.setattr(ui.sys, "stdin", TerminalInput())
    ui.configure()
    yield
    ui.configure()


@pytest.mark.parametrize("exit_code", [0, 1, 127])
@pytest.mark.parametrize("secret", [False, True])
def test_input_uses_gum_or_plain_fallback(
    monkeypatch, authentication, exit_code, secret
):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, exit_code, authentication.email)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(ui.builtins, "input", lambda prompt: authentication.email)
    monkeypatch.setattr(ui._getpass, "getpass", lambda prompt: authentication.email)
    if secret:
        result = ui.password(authentication.vault_name)
    else:
        result = ui.input(authentication.vault_name, placeholder=authentication.email)
    assert result == authentication.email
    assert calls


@pytest.mark.parametrize("exit_code", [0, 1, 127])
@pytest.mark.parametrize("default", [False, True])
def test_confirmation_preserves_explicit_choice(monkeypatch, exit_code, default):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, exit_code),
    )
    answers = iter(["unrecognized", "no"])
    monkeypatch.setattr(ui.builtins, "input", lambda prompt: next(answers))
    assert ui.confirm("Continue", default=default) is (exit_code == 0)


def test_plain_confirmation_empty_answer_accepts_yes_default(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", unavailable)
    monkeypatch.setattr(ui.builtins, "input", lambda prompt: "")
    assert ui.confirm("Continue") is True


@pytest.mark.parametrize("exit_code", [0, 1])
@pytest.mark.parametrize("selected", [False, True])
def test_choose_preserves_selection_and_filters_fallback(
    monkeypatch, authentication, exit_code, selected
):
    options = [authentication.vault_name, authentication.email]
    output = "\n".join(options) if exit_code == 0 else ""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, exit_code, output),
    )
    monkeypatch.setattr(
        ui.builtins,
        "input",
        lambda prompt: ", ".join([*options, authentication.server]),
    )
    assert (
        ui.choose(
            authentication.vault_name,
            options,
            selected=options if selected else None,
        )
        == options
    )
    assert ui.choose(authentication.vault_name, []) == []


@pytest.mark.parametrize("operation", [ui.input, ui.password, ui.confirm, ui.choose])
def test_ctrl_c_is_not_a_fallback(monkeypatch, operation, authentication):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, ui.SIGINT_EXIT_CODE),
    )
    with pytest.raises(KeyboardInterrupt):
        if operation is ui.choose:
            operation(authentication.vault_name, [authentication.email])
        else:
            operation(authentication.vault_name)


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("styled", [False, True])
def test_style_has_plain_fallback(
    monkeypatch, capsys, authentication, available, styled
):
    def run(args, **kwargs):
        if not available:
            raise FileNotFoundError
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    ui.style(
        authentication.vault_name,
        bold=styled,
        foreground=authentication.email if styled else "",
        background=authentication.email if styled else "",
        padding=authentication.email if styled else "",
    )
    assert capsys.readouterr().out == (
        "" if available else authentication.vault_name + "\n"
    )


def test_spin_preserves_result_and_exception(authentication):
    assert (
        ui.spin(authentication.vault_name, lambda: authentication.email)
        == authentication.email
    )

    def fail():
        raise OSError(authentication.network_failure)

    with pytest.raises(OSError, match=authentication.network_failure):
        ui.spin(authentication.vault_name, fail)
