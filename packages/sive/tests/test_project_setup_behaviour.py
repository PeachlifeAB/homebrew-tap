from __future__ import annotations

import json
import subprocess

import pytest

from sive.commands import setup
from sive.core import (
    credentials,
    project_config,
    snapshot_crypto,
    sync_state,
    ui,
    vaults,
)


@pytest.fixture
def configured_project(monkeypatch, tmp_path, authentication):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    configuration = tmp_path / "sive"
    monkeypatch.setattr(vaults, "CONFIG_DIR", configuration)
    monkeypatch.setattr(vaults, "VAULTS_TOML", configuration / "vaults.toml")
    monkeypatch.setattr(sync_state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(setup, "MISE_CONFIG_DIR", tmp_path / "mise")
    monkeypatch.setattr(setup, "GLOBAL_MISE_CONFIG", tmp_path / "mise" / "config.toml")
    monkeypatch.setattr(setup, "SIVE_HOOK_SCRIPT", tmp_path / "hook" / "env.sh")
    monkeypatch.setattr(
        setup, "get_stored_password", lambda name: authentication.password
    )
    monkeypatch.setattr(
        credentials, "get_password", lambda name: authentication.password
    )
    monkeypatch.setattr(
        snapshot_crypto, "ensure_key", lambda *args: authentication.password
    )
    monkeypatch.setattr(ui, "ensure_homebrew_command", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui, "style", lambda *args, **kwargs: None)
    vaults.write_vault_stub("personal", authentication.server)
    return tmp_path


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("empty_choice", [False, True])
def test_project_setup_selects_available_tags(
    monkeypatch, configured_project, authentication, cached, empty_choice
):
    if cached:
        sync_state.save_sync_state(
            "personal", {"known_tags": [authentication.vault_name, "", None]}
        )
    selected = [] if empty_choice else [authentication.vault_name]
    monkeypatch.setattr(ui, "choose", lambda *args, **kwargs: selected)

    def run(args, **kwargs):
        if args[2] == "status":
            output = json.dumps({"status": "locked"})
        elif args[2] == "unlock":
            output = authentication.session
        else:
            output = json.dumps([{"name": "env/" + authentication.vault_name}])
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert setup.run_project_setup() == int(empty_choice)
    if empty_choice:
        assert not (configured_project / ".sive").exists()
    else:
        assert project_config.read_project_tags() == [
            "global",
            authentication.vault_name,
        ]


@pytest.mark.parametrize("unlock_fails", [False, True])
@pytest.mark.parametrize("empty_input", [False, True])
def test_project_setup_falls_back_to_text(
    monkeypatch, configured_project, authentication, unlock_fails, empty_input
):
    monkeypatch.setattr(
        ui,
        "input",
        lambda *args, **kwargs: "" if empty_input else authentication.vault_name,
    )

    def run(args, **kwargs):
        if args[2] == "status":
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"status": "locked"}), ""
            )
        if args[2] == "unlock":
            return subprocess.CompletedProcess(
                args,
                int(unlock_fails),
                authentication.session,
                authentication.network_failure,
            )
        return subprocess.CompletedProcess(args, 0, "[]", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert setup.run_project_setup(no_global=True) == int(empty_input)
    if not empty_input:
        assert project_config.read_project_tags() == [authentication.vault_name]


@pytest.mark.parametrize(
    "failure", ["storage-continue", "storage-stop", "unlock", "login", "server"]
)
def test_project_setup_handles_login_failures(
    monkeypatch, configured_project, authentication, capsys, failure
):
    from sive.core.credentials import CredentialError

    def missing(name):
        raise CredentialError(authentication.network_failure)

    monkeypatch.setattr(setup, "get_stored_password", missing)
    monkeypatch.setattr(ui, "input", lambda *args, **kwargs: authentication.email)
    monkeypatch.setattr(ui, "password", lambda *args, **kwargs: authentication.password)
    answers = iter([True, failure == "storage-continue"])
    monkeypatch.setattr(ui, "confirm", lambda *args, **kwargs: next(answers))

    def store(*args):
        raise CredentialError(authentication.network_failure)

    monkeypatch.setattr(setup, "store_password", store)

    def run(args, **kwargs):
        command = args[2]
        if command == "status":
            output = json.dumps(
                {
                    "status": "unauthenticated",
                    "serverUrl": authentication.server if failure != "server" else "",
                }
            )
            return subprocess.CompletedProcess(args, 0, output, "")
        failed = (
            (failure == "server" and command == "config")
            or (failure == "login" and command == "login")
            or (failure == "unlock" and command == "unlock")
        )
        return subprocess.CompletedProcess(
            args,
            int(failed),
            authentication.session if not failed else "",
            authentication.network_failure if failed else "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    expected = 0 if failure == "storage-continue" else 1
    assert setup.run_project_setup(tags=[authentication.vault_name]) == expected
    captured = capsys.readouterr()
    assert authentication.network_failure in captured.err
    assert project_config.read_project_tags() == (
        ["global", authentication.vault_name] if expected == 0 else []
    )
