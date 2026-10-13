from __future__ import annotations

from . import bw, credentials


class VaultSessionError(Exception):
    pass


def acquire_session(
    vault_name: str, existing_session: str | None = None, *, appdata_dir: str
) -> str:
    if existing_session:
        return existing_session
    try:
        password = credentials.get_password(vault_name)
    except credentials.CredentialError as error:
        raise VaultSessionError(str(error)) from error
    try:
        return bw.unlock(password, appdata_dir=appdata_dir)
    except bw.BWError as error:
        raise VaultSessionError(f"Silent unlock failed: {error}") from error
