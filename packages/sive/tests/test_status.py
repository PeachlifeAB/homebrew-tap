"""`sive status` reports what it observed, never a guess about why."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sive.commands import status
from sive.core.credentials import CredentialError

LOCKED = "macOS Keychain is locked; cannot read 'master_password'."
HOOK = "/Users/u/.local/share/sive/mise_hook/env.sh"


def test_status_reports_the_credential_error_it_saw(capsys):
    vault = MagicMock(server="https://vault", appdata_dir="/tmp/appdata")
    vault.name = "personal"
    with (
        patch.object(status, "load_vault", return_value=vault),
        patch.object(status, "_load_bw_status", return_value={}),
        patch.object(status, "get_password", side_effect=CredentialError(LOCKED)),
        patch.object(status, "read_project_tags", return_value=[]),
        patch.object(status, "load_sync_state", return_value={}),
        patch.object(status, "_read_mise_state", return_value=(True, False, "")),
    ):
        assert status.run() == 1

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert LOCKED in output
    assert "not in credential storage" not in output


# mise reads `_.source` as the dotted key env._.source, in any of the forms
# documented at .gdog/docs/mise/environments.md#L530-L566.
@pytest.mark.parametrize(
    "directive",
    [
        f'_.source = "{HOOK}"',
        f'_.source = ["{HOOK}"]',
        f'_.source = {{ path = "{HOOK}" }}',
    ],
)
def test_status_sees_the_hook_setup_wrote(tmp_path, monkeypatch, directive):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / ".config" / "mise" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f"[env]\n{directive}\n")

    hook_configured, _cache, _ttl = status._read_mise_state()

    assert hook_configured is True
