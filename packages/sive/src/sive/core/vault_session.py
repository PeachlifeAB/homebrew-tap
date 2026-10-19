from __future__ import annotations

from . import bw, credentials

UNAUTHENTICATED_STATUS = "unauthenticated"


class VaultSessionError(Exception):
    pass


class VaultAuthenticationError(VaultSessionError):
    pass


def acquire_session(
    vault_name: str, existing_session: str | None = None, *, appdata_dir: str
) -> str:
    if existing_session:
        return existing_session
    try:
        password = credentials.get_password(vault_name)
    except credentials.CredentialError as error:
        raise VaultAuthenticationError(str(error)) from error
    try:
        return bw.unlock(password, appdata_dir=appdata_dir)
    except bw.BWLoginRequiredError as error:
        try:
            return _recover_login(vault_name, password, appdata_dir=appdata_dir)
        except (bw.BWError, credentials.CredentialError) as recovery_error:
            raise VaultAuthenticationError(
                f"Authentication recovery failed: {recovery_error}\n"
                f"Original authentication failure: {error}\n"
                "Run 'sive setup' to repair stored credentials "
                "or complete additional authentication."
            ) from recovery_error
    except bw.BWAuthError as error:
        raise VaultAuthenticationError(f"Silent unlock failed: {error}") from error
    except bw.BWError as error:
        raise VaultSessionError(f"Silent unlock failed: {error}") from error


def _recover_login(vault_name: str, password: str, *, appdata_dir: str) -> str:
    email = credentials.get_email(vault_name)
    if not email:
        raise bw.BWAuthError("No stored vault email. Run 'sive setup' to configure it.")
    status = bw.get_status(appdata_dir=appdata_dir)
    account_email = status.get("userEmail")
    if account_email and account_email.casefold() != email.casefold():
        raise bw.BWAuthError(
            "Vault account differs from stored credentials; "
            "automatic account switching is disabled."
        )
    authentication_status = status.get("status")
    if authentication_status in ("locked", "unlocked"):
        if not account_email:
            raise bw.BWAuthError(
                "Cannot verify the vault account; refusing automatic logout."
            )
        bw.logout(appdata_dir=appdata_dir)
    elif authentication_status != UNAUTHENTICATED_STATUS:
        raise bw.BWAuthError(
            "Cannot determine vault authentication state; refusing automatic login."
        )
    session = bw.login(email, password, appdata_dir=appdata_dir)
    if not session:
        raise bw.BWAuthError("Login returned an empty session key.")
    return session
