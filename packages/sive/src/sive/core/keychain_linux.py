"""Linux Secret Service credential adapter."""

from __future__ import annotations

from typing import Protocol

from .credentials import (
    EMAIL_ACCOUNT,
    MASTER_PASSWORD_ACCOUNT,
    CredentialError,
    CredentialStoreUnavailableError,
    decode_secret_value,
    encode_secret_value,
    service_name,
)


class KeyringApi(Protocol):
    """The narrow keyring surface used by the Linux adapter."""

    def get_password(self, service_name: str, account: str) -> str | None: ...

    def set_password(self, service_name: str, account: str, password: str) -> None: ...
    def delete_password(self, service_name: str, account: str) -> None: ...


class LinuxKeyringStore:
    """Store Sive credentials in the Linux Secret Service."""

    def __init__(self, keyring_api: KeyringApi | None = None) -> None:
        self._keyring_api = keyring_api

    def _api(self) -> KeyringApi:
        if self._keyring_api is None:
            try:
                import keyring
            except ImportError as error:
                raise CredentialStoreUnavailableError(
                    "Linux Secret Service support is not installed. "
                    "Reinstall sive with its Linux dependencies."
                ) from error
            self._keyring_api = keyring
        return self._keyring_api

    @staticmethod
    def _unavailable(error: Exception) -> CredentialStoreUnavailableError:
        return CredentialStoreUnavailableError(
            "Linux Secret Service is unavailable. Start a D-Bus session and "
            "unlock a Secret Service provider such as GNOME Keyring, then rerun "
            f"'sive setup'. ({error})"
        )

    @staticmethod
    def _is_availability_error(error: Exception) -> bool:
        return isinstance(error, RuntimeError) or type(error).__module__.startswith(
            "keyring."
        )

    def ensure_unlocked(self) -> bool:
        # The desktop session's Secret Service agent owns unlocking.
        return True

    def store_secret(self, vault_name: str, account: str, value: str) -> None:
        try:
            self._api().set_password(
                service_name(vault_name), account, encode_secret_value(value)
            )
        except Exception as error:  # keyring exposes plugin-specific exceptions.
            if self._is_availability_error(error):
                raise self._unavailable(error) from error
            raise

    def get_secret(
        self, vault_name: str, account: str, *, missing_hint: str = ""
    ) -> str:
        try:
            value = self._api().get_password(service_name(vault_name), account)
        except Exception as error:  # keyring exposes plugin-specific exceptions.
            if self._is_availability_error(error):
                raise self._unavailable(error) from error
            raise
        if value is None:
            hint = missing_hint or "Run 'sive setup' to store it."
            raise CredentialError(
                f"Credential entry '{account}' for vault "
                f"'{vault_name}' not found.\n{hint}"
            )
        return decode_secret_value(value)

    def delete_secret(self, vault_name: str, account: str) -> None:
        try:
            self._api().delete_password(service_name(vault_name), account)
        except Exception as error:  # deletion remains best effort.
            if self._is_availability_error(error):
                return
            raise

    def store_password(self, vault_name: str, password: str) -> None:
        self.store_secret(vault_name, MASTER_PASSWORD_ACCOUNT, password)

    def get_password(self, vault_name: str) -> str:
        return self.get_secret(
            vault_name,
            MASTER_PASSWORD_ACCOUNT,
            missing_hint="Run 'sive setup' to store it.",
        )

    def delete_password(self, vault_name: str) -> None:
        self.delete_secret(vault_name, MASTER_PASSWORD_ACCOUNT)

    def store_email(self, vault_name: str, email: str) -> None:
        self.store_secret(vault_name, EMAIL_ACCOUNT, email)

    def get_email(self, vault_name: str) -> str | None:
        try:
            return self.get_secret(vault_name, EMAIL_ACCOUNT)
        except CredentialError:
            return None
