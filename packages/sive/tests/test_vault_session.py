from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from sive.core.vault_session import acquire_session


def test_rejected_grant_recovers_using_stored_credentials(authentication, tmp_path):
    fixture = authentication
    status = json.dumps(
        {"status": "locked", "userEmail": fixture.email, "serverUrl": fixture.server}
    )
    responses = [
        subprocess.CompletedProcess([], 1, "", fixture.rejected_grant),
        subprocess.CompletedProcess([], 0, status, ""),
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 0, fixture.session, ""),
    ]
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=fixture.email),
        patch("sive.core.bw.subprocess.run", side_effect=responses) as process,
    ):
        session = acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
    assert session == fixture.session
    assert [call.args[0][2] for call in process.call_args_list] == [
        "unlock",
        "status",
        "logout",
        "login",
    ]
    for call in process.call_args_list:
        assert call.kwargs["env"]["BITWARDENCLI_APPDATA_DIR"] == str(tmp_path)
    login = process.call_args_list[-1]
    assert login.kwargs["env"]["SIVE_BW_PASSWORD"] == fixture.password
    assert fixture.password not in login.args[0]


@pytest.mark.parametrize("failure_field", ["wrong_password", "network_failure"])
def test_nonrecoverable_unlock_does_not_login(authentication, tmp_path, failure_field):
    from sive.core.vault_session import VaultSessionError

    fixture = authentication
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch(
            "sive.core.bw.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 1, "", getattr(fixture, failure_field)
            ),
        ) as process,
        pytest.raises(VaultSessionError, match=getattr(fixture, failure_field)),
    ):
        acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
    assert process.call_count == 1


def test_healthy_unlock_does_not_login(authentication, tmp_path, monkeypatch):
    fixture = authentication
    monkeypatch.setenv("BW_SESSION", "unrelated-account-session")
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch(
            "sive.core.bw.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, fixture.session, ""),
        ) as process,
        patch("sive.core.credentials.get_email") as email,
    ):
        assert (
            acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
            == fixture.session
        )
    email.assert_not_called()
    process.assert_called_once()
    assert "BW_SESSION" not in process.call_args.kwargs["env"]


def test_supplied_session_does_not_read_credentials(authentication, tmp_path):
    fixture = authentication
    with (
        patch("sive.core.credentials.get_password") as password,
        patch("sive.core.bw.subprocess.run") as process,
    ):
        assert (
            acquire_session(
                fixture.vault_name, fixture.session, appdata_dir=str(tmp_path)
            )
            == fixture.session
        )
    password.assert_not_called()
    process.assert_not_called()


def test_missing_login_does_not_logout(authentication, tmp_path):
    fixture = authentication
    responses = [
        subprocess.CompletedProcess([], 1, "", fixture.missing_login),
        subprocess.CompletedProcess(
            [], 0, json.dumps({"status": "unauthenticated"}), ""
        ),
        subprocess.CompletedProcess([], 0, fixture.session, ""),
    ]
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=fixture.email),
        patch("sive.core.bw.subprocess.run", side_effect=responses) as process,
    ):
        assert (
            acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
            == fixture.session
        )
    assert [call.args[0][2] for call in process.call_args_list] == [
        "unlock",
        "status",
        "login",
    ]


@pytest.mark.parametrize("account_email", ["different@example.com", None])
def test_unverified_account_is_not_logged_out(authentication, tmp_path, account_email):
    from sive.core.vault_session import VaultAuthenticationError

    fixture = authentication
    responses = [
        subprocess.CompletedProcess([], 1, "", fixture.rejected_grant),
        subprocess.CompletedProcess(
            [], 0, json.dumps({"status": "locked", "userEmail": account_email}), ""
        ),
    ]
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=fixture.email),
        patch("sive.core.bw.subprocess.run", side_effect=responses) as process,
        pytest.raises(VaultAuthenticationError),
    ):
        acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
    assert process.call_count == 2


@pytest.mark.parametrize("failure_field", ["additional_factor", "rejected_grant"])
def test_failed_recovery_is_not_retried(authentication, tmp_path, failure_field):
    from sive.core.vault_session import VaultAuthenticationError

    fixture = authentication
    responses = [
        subprocess.CompletedProcess([], 1, "", fixture.missing_login),
        subprocess.CompletedProcess(
            [], 0, json.dumps({"status": "unauthenticated"}), ""
        ),
        subprocess.CompletedProcess([], 1, "", getattr(fixture, failure_field)),
    ]
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=fixture.email),
        patch("sive.core.bw.subprocess.run", side_effect=responses) as process,
        pytest.raises(VaultAuthenticationError, match="sive setup"),
    ):
        acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
    assert process.call_count == 3


def test_missing_email_prevents_account_reset(authentication, tmp_path):
    from sive.core.vault_session import VaultAuthenticationError

    fixture = authentication
    with (
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=None),
        patch(
            "sive.core.bw.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", fixture.rejected_grant),
        ) as process,
        pytest.raises(VaultAuthenticationError, match="No stored vault email"),
    ):
        acquire_session(fixture.vault_name, appdata_dir=str(tmp_path))
    assert process.call_count == 1


def test_refresh_continues_after_recovery_without_password_prompt(
    authentication, tmp_path
):
    from sive.commands.refresh import run
    from sive.core.vaults import VaultConfig

    fixture = authentication
    vault = VaultConfig(fixture.vault_name, fixture.server, tmp_path)
    responses = [
        subprocess.CompletedProcess([], 1, "", fixture.rejected_grant),
        subprocess.CompletedProcess(
            [], 0, json.dumps({"status": "locked", "userEmail": fixture.email}), ""
        ),
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 0, fixture.session, ""),
        subprocess.CompletedProcess([], 0, "", ""),
    ]
    with (
        patch("sive.core.vaults.load_vault", return_value=vault),
        patch("sive.core.credentials.get_password", return_value=fixture.password),
        patch("sive.core.credentials.get_email", return_value=fixture.email),
        patch("sive.core.bw.subprocess.run", side_effect=responses) as process,
        patch("sive.core.ui.password") as password_prompt,
    ):
        assert run(fixture.vault_name, sources=[]) == 0
    password_prompt.assert_not_called()
    assert [call.args[0][2] for call in process.call_args_list] == [
        "unlock",
        "status",
        "logout",
        "login",
        "sync",
    ]
