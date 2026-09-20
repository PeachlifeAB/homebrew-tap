"""Tests for keychain_macos.py."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

import pytest

from sive.core.keychain_macos import (
    KeychainError,
    delete_password,
    get_password,
    get_secret,
    store_password,
)

case = unittest.TestCase()


# get_password


def test_get_password_returns_decoded_value_on_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "sive1:bXktc2VjcmV0LXBhc3N3b3Jk\n"

    with patch("subprocess.run", return_value=mock_result):
        result = get_password("personal")

    case.assertEqual(result, "my-secret-password")


def test_get_password_supports_legacy_plaintext_values():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "legacy-password\n"

    with patch("subprocess.run", return_value=mock_result):
        result = get_password("personal")

    case.assertEqual(result, "legacy-password")


def test_get_password_raises_keychain_error_when_not_found():
    mock_result = MagicMock()
    mock_result.returncode = 44
    mock_result.stdout = ""

    with (
        patch("subprocess.run", return_value=mock_result),
        pytest.raises(
            KeychainError, match="Keychain entry 'master_password'.*not found"
        ),
    ):
        get_password("personal")


# store_password


def test_store_password_uses_update_and_encoded_value():
    add_result = MagicMock(returncode=0, stderr="")

    with patch("subprocess.run", return_value=add_result) as mock_run:
        store_password("personal", "my-password")

    cmd = mock_run.call_args[0][0]
    case.assertEqual(cmd[:4], ["security", "add-generic-password", "-U", "-s"])
    case.assertIn("sive/personal", cmd)
    case.assertIn("master_password", cmd)
    case.assertIn("-w", cmd)
    case.assertEqual(cmd[cmd.index("-w") + 1], "sive1:bXktcGFzc3dvcmQ=")


def test_store_password_raises_helpful_error_on_failure():
    add_result = MagicMock(
        returncode=1,
        stderr="security: SecKeychain what a shameful experience",
    )

    with (
        patch("subprocess.run", return_value=add_result),
        pytest.raises(KeychainError) as error,
    ):
        store_password("personal", "my-password")

    message = str(error.value)
    case.assertIn("Could not save the master password in macOS Keychain.", message)
    case.assertIn(
        "security unlock-keychain ~/Library/Keychains/login.keychain-db", message
    )
    case.assertIn("macOS returned a generic SecKeychain error.", message)
    case.assertNotIn("what a shameful experience", message)


def test_store_password_self_heals_when_keychain_is_locked():
    """A locked keychain ('User interaction is not allowed') triggers unlock + retry."""
    locked = MagicMock(
        returncode=1,
        stderr="security: SecKeychainItemCreateFromContent (<default>): "
        "User interaction is not allowed.",
    )
    retry_ok = MagicMock(returncode=0, stderr="")

    with (
        patch("subprocess.run", side_effect=[locked, retry_ok]),
        patch("sive.core.keychain_macos._unlock_login_keychain", return_value=True),
    ):
        store_password("personal", "my-password")  # must not raise


def test_store_password_raises_when_user_declines_keychain_unlock():
    """If the user declines the unlock prompt, the store surfaces the friendly error."""
    locked = MagicMock(
        returncode=1,
        stderr="security: SecKeychainItemCreateFromContent (<default>): "
        "User interaction is not allowed.",
    )

    with (
        patch("subprocess.run", return_value=locked),
        patch("sive.core.keychain_macos._unlock_login_keychain", return_value=False),
        pytest.raises(KeychainError) as error,
    ):
        store_password("personal", "my-password")

    case.assertIn("Could not save the master password", str(error.value))


# Service name format


def test_service_name_includes_vault_name():
    mock_result = MagicMock(returncode=0, stdout="sive1:cGFzcw==\n")

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        get_password("work")

    cmd = mock_run.call_args[0][0]
    case.assertIn("sive/work", cmd)


def test_delete_password_is_best_effort_on_failure():
    mock_result = MagicMock(returncode=44)

    with patch("subprocess.run", return_value=mock_result):
        delete_password("personal")


# ---------------------------------------------------------------------------
# Non-interactive contract — the shell hook calls this on every prompt.
#
# `security` reads a passphrase from whatever stdin it inherits and blocks
# forever when the keychain is locked. mise runs the hook from a shell hook,
# so a blocked read freezes every new terminal.
# ---------------------------------------------------------------------------


def test_get_secret_never_inherits_stdin():
    """A locked keychain must not let `security` read from the caller's tty."""
    with patch("subprocess.run") as run_mock:
        run_mock.return_value = subprocess.CompletedProcess([], 0, "sive1:", "")
        get_secret("personal", "snapshot_key:global")

    assert run_mock.call_args.kwargs["stdin"] is subprocess.DEVNULL


def test_get_secret_bounds_the_subprocess():
    """An unbounded `security` call hangs the shell instead of failing."""
    with patch("subprocess.run") as run_mock:
        run_mock.return_value = subprocess.CompletedProcess([], 0, "sive1:", "")
        get_secret("personal", "snapshot_key:global")

    assert run_mock.call_args.kwargs.get("timeout") is not None


def test_get_secret_raises_keychain_error_on_timeout():
    """A timeout is a missing secret, not a traceback through the hook."""
    with (
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired("security", 5)),
        pytest.raises(KeychainError),
    ):
        get_secret("personal", "snapshot_key:global")
