from __future__ import annotations

import json
import subprocess

import pytest

from sive.commands import status
from sive.core import sync_state, vaults


@pytest.mark.parametrize("hook", [False, True])
@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("matching_server", [False, True])
def test_status_reports_configuration_warnings(
    monkeypatch, tmp_path, authentication, capsys, hook, cache, matching_server
):
    monkeypatch.setenv("HOME", str(tmp_path))
    configuration = tmp_path / ".config" / "sive"
    monkeypatch.setattr(vaults, "CONFIG_DIR", configuration)
    monkeypatch.setattr(vaults, "VAULTS_TOML", configuration / "vaults.toml")
    monkeypatch.setattr(sync_state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(status, "get_password", lambda name: authentication.password)
    monkeypatch.chdir(tmp_path)
    vaults.write_vault_stub("personal", authentication.server)
    mise = tmp_path / ".config" / "mise" / "config.toml"
    mise.parent.mkdir()
    content = f"[settings]\nenv_cache = {str(cache).lower()}\n"
    if hook:
        content += f'[env]\n_.source = "{status.SIVE_MARKER}/env.sh"\n'
    mise.write_text(content)

    def run(args, **kwargs):
        response = {
            "status": "locked",
            "userEmail": authentication.email,
            "serverUrl": authentication.server
            if matching_server
            else authentication.email,
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(response), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert status.run() == (0 if hook and cache and matching_server else 1)
    captured = capsys.readouterr()
    assert ("hook not configured" in captured.err) is (not hook)
    assert ("env_cache is disabled" in captured.err) is (not cache)
    assert ("does not match" in captured.err) is (not matching_server)
    assert authentication.email in captured.out


@pytest.mark.parametrize("failure", ["configuration", "missing-cli", "vault-error"])
def test_status_reports_unavailable_vault(
    monkeypatch, authentication, tmp_path, capsys, failure
):
    from sive.core.bw import BWError, BWNotInstalledError

    def load_vault(name):
        if failure == "configuration":
            raise vaults.ConfigError(authentication.network_failure)
        return vaults.VaultConfig(name, authentication.server, tmp_path)

    def get_status(**kwargs):
        error = BWNotInstalledError if failure == "missing-cli" else BWError
        raise error(authentication.network_failure)

    monkeypatch.setattr(status, "load_vault", load_vault)
    monkeypatch.setattr(status, "get_status", get_status)
    assert status.run() == 1
    captured = capsys.readouterr()
    assert (
        "NOT INSTALLED" in captured.err
        if failure == "missing-cli"
        else authentication.network_failure in captured.err
    )
