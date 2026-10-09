"""Credential-store port and platform-selected facade."""

from __future__ import annotations

import base64
import platform
from typing import Protocol

SERVICE_PREFIX = "sive"
_VALUE_PREFIX = "sive1:"
MACOS_SYSTEM = "Darwin"
LINUX_SYSTEM = "Linux"

# Credential-store account labels, not credentials: the value stored under
# MASTER_PASSWORD_ACCOUNT is the password, this names the slot.
MASTER_PASSWORD_ACCOUNT = "master_password"  # noqa: S105
EMAIL_ACCOUNT = "email"


class CredentialError(Exception):
    """A credential store could not complete an operation."""


class CredentialStoreUnavailableError(CredentialError):
    """The selected platform has no usable credential store."""


class CredentialStore(Protocol):
    """Secure storage for one Sive vault's credentials."""

    def ensure_unlocked(self) -> bool: ...

    def store_secret(self, vault_name: str, account: str, value: str) -> None: ...

    def get_secret(
        self, vault_name: str, account: str, *, missing_hint: str = ""
    ) -> str: ...

    def delete_secret(self, vault_name: str, account: str) -> None: ...

    def store_password(self, vault_name: str, password: str) -> None: ...

    def get_password(self, vault_name: str) -> str: ...

    def delete_password(self, vault_name: str) -> None: ...

    def store_email(self, vault_name: str, email: str) -> None: ...

    def get_email(self, vault_name: str) -> str | None: ...


def service_name(vault_name: str) -> str:
    """Return the stable storage service name for a vault."""
    return f"{SERVICE_PREFIX}/{vault_name}"


def encode_secret_value(value: str) -> str:
    """Keep stored values compatible across platform adapters."""
    encoded = base64.b64encode(value.encode()).decode("ascii")
    return f"{_VALUE_PREFIX}{encoded}"


def decode_secret_value(value: str) -> str:
    """Decode a value written by a Sive credential adapter."""
    if not value.startswith(_VALUE_PREFIX):
        return value
    encoded = value.removeprefix(_VALUE_PREFIX)
    return base64.b64decode(encoded.encode("ascii")).decode()


def build_credential_store(system: str | None = None) -> CredentialStore:
    """Compose the credential adapter for a supported operating system."""
    system = system or platform.system()
    if system == MACOS_SYSTEM:
        from .keychain_macos import MacOSKeychainStore

        return MacOSKeychainStore()
    if system == LINUX_SYSTEM:
        from .keychain_linux import LinuxKeyringStore

        return LinuxKeyringStore()
    raise CredentialStoreUnavailableError(
        f"No credential store is configured for {system}. "
        "Sive supports macOS Keychain and Linux Secret Service."
    )


def _store() -> CredentialStore:
    return build_credential_store()


def ensure_unlocked() -> bool:
    return _store().ensure_unlocked()


def store_secret(vault_name: str, account: str, value: str) -> None:
    _store().store_secret(vault_name, account, value)


def get_secret(vault_name: str, account: str, *, missing_hint: str = "") -> str:
    return _store().get_secret(vault_name, account, missing_hint=missing_hint)


def delete_secret(vault_name: str, account: str) -> None:
    _store().delete_secret(vault_name, account)


def store_password(vault_name: str, password: str) -> None:
    _store().store_password(vault_name, password)


def get_password(vault_name: str) -> str:
    return _store().get_password(vault_name)


def delete_password(vault_name: str) -> None:
    _store().delete_password(vault_name)


def store_email(vault_name: str, email: str) -> None:
    _store().store_email(vault_name, email)


def get_email(vault_name: str) -> str | None:
    return _store().get_email(vault_name)
