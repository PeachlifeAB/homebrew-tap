from __future__ import annotations

import pytest

from sive.core.credentials import CredentialError, CredentialStoreUnavailableError
from sive.core.keychain_linux import LinuxKeyringStore


class CredentialService:
    def __init__(self, failure: Exception | None = None):
        self.accounts: dict[str, dict[str, str]] = {}
        self.failure = failure

    def get_password(self, service: str, account: str) -> str | None:
        if self.failure:
            raise self.failure
        return self.accounts.get(service, {}).get(account)

    def set_password(self, service: str, account: str, password: str) -> None:
        if self.failure:
            raise self.failure
        self.accounts.setdefault(service, {})[account] = password

    def delete_password(self, service: str, account: str) -> None:
        if self.failure:
            raise self.failure
        self.accounts.setdefault(service, {}).pop(account, None)


def test_credential_lifecycle_keeps_vault_accounts_separate(authentication):
    store = LinuxKeyringStore(CredentialService())
    vault = authentication.vault_name
    assert store.ensure_unlocked()
    assert store.get_email(vault) is None
    store.store_email(vault, authentication.email)
    store.store_password(vault, authentication.password)
    assert store.get_email(vault) == authentication.email
    assert store.get_password(vault) == authentication.password
    assert store.get_email(vault + "_other") is None
    store.delete_password(vault)
    assert store.get_email(vault) == authentication.email
    with pytest.raises(CredentialError, match="sive setup"):
        store.get_password(vault)


@pytest.mark.parametrize("unavailable", [False, True])
@pytest.mark.parametrize("operation", ["store", "get", "delete"])
def test_credential_failures_preserve_boundary(authentication, unavailable, operation):
    failure = (
        RuntimeError(authentication.network_failure)
        if unavailable
        else ValueError(authentication.network_failure)
    )
    store = LinuxKeyringStore(CredentialService(failure))

    def invoke():
        if operation == "store":
            store.store_password(authentication.vault_name, authentication.password)
        elif operation == "get":
            store.get_password(authentication.vault_name)
        else:
            store.delete_password(authentication.vault_name)

    if unavailable and operation == "delete":
        invoke()
    else:
        expected = CredentialStoreUnavailableError if unavailable else ValueError
        with pytest.raises(
            expected,
            match="Secret Service" if unavailable else authentication.network_failure,
        ):
            invoke()
