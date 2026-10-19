from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from sive.core import bw
from sive.core.credentials import CredentialError
from sive.core.vault_session import VaultAuthenticationError, acquire_session


def test_missing_password_does_not_execute_bitwarden(authentication, tmp_path):
    with (
        patch(
            "sive.core.credentials.get_password",
            side_effect=CredentialError("missing vault password"),
        ),
        patch("sive.core.bw.subprocess.run") as process,
        pytest.raises(VaultAuthenticationError, match="missing vault password"),
    ):
        acquire_session(authentication.vault_name, appdata_dir=str(tmp_path))
    process.assert_not_called()


def test_password_is_redacted_from_failure_diagnostics(authentication, tmp_path):
    fixture = authentication
    response = subprocess.CompletedProcess([], 1, "", fixture.password)
    with (
        patch("sive.core.bw.subprocess.run", return_value=response),
        pytest.raises(bw.BWError) as raised,
    ):
        bw.login(fixture.email, fixture.password, appdata_dir=tmp_path)
    assert fixture.password not in str(raised.value)


def test_authentication_error_is_not_queued_as_network_failure(
    authentication, tmp_path
):
    from sive.commands.set_secret import run
    from sive.core.pending_queue import load_pending
    from sive.core.vaults import VaultConfig

    fixture = authentication
    vault = VaultConfig(fixture.vault_name, fixture.server, tmp_path)
    responses = [
        subprocess.CompletedProcess([], 1, "", fixture.rejected_grant),
        subprocess.CompletedProcess([], 0, '{"status":"unauthenticated"}', ""),
        subprocess.CompletedProcess([], 1, "", fixture.additional_factor),
    ]
    with (
        patch("sive.core.pending_queue.STATE_DIR", tmp_path / "queue"),
        patch("sive.commands.set_secret.load_vault", return_value=vault),
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=fixture.email),
        patch("sive.core.bw.subprocess.run", side_effect=responses),
    ):
        assert (
            run(
                "FIXTURE_SECRET",
                "fixture-value",
                tag="fixture",
                vault_name=fixture.vault_name,
            )
            != 0
        )
        assert load_pending(fixture.vault_name) == []
