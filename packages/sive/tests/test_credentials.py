from __future__ import annotations

import pytest

from sive.core.credentials import (
    CredentialError,
    CredentialStoreUnavailableError,
    build_credential_store,
)
from sive.core.keychain_linux import LinuxKeyringStore
from sive.core.keychain_macos import MacOSKeychainStore


class UnavailableKeyring:
    def get_password(self, service: str, account: str) -> str | None:
        raise RuntimeError("The Secret Service daemon is neither running")


def test_build_credential_store_selects_macos_adapter() -> None:
    assert isinstance(build_credential_store("Darwin"), MacOSKeychainStore)


def test_build_credential_store_selects_linux_adapter() -> None:
    assert isinstance(build_credential_store("Linux"), LinuxKeyringStore)


def test_linux_store_reports_unavailable_secret_service() -> None:
    store = LinuxKeyringStore(UnavailableKeyring())

    with pytest.raises(CredentialStoreUnavailableError, match="Secret Service"):
        store.get_secret("personal", "master_password")


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        self.values[service, account] = password

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def test_linux_store_round_trips_a_sive_value() -> None:
    keyring = MemoryKeyring()
    store = LinuxKeyringStore(keyring)

    store.store_secret("personal", "snapshot_key:global", "secret")

    assert keyring.values == {
        ("sive/personal", "snapshot_key:global"): "sive1:c2VjcmV0"
    }
    assert store.get_secret("personal", "snapshot_key:global") == "secret"


def test_linux_store_reports_a_missing_credential() -> None:
    store = LinuxKeyringStore(MemoryKeyring())

    with pytest.raises(CredentialError, match="not found"):
        store.get_secret("personal", "master_password")


def test_unknown_platform_fails_at_the_credential_boundary() -> None:
    with pytest.raises(CredentialStoreUnavailableError, match="FreeBSD"):
        build_credential_store("FreeBSD")
