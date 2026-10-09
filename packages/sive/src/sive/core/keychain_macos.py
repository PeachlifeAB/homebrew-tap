"""macOS Keychain integration via the 'security' CLI."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from .credentials import EMAIL_ACCOUNT, MASTER_PASSWORD_ACCOUNT, CredentialError

SERVICE_PREFIX = "sive"
_VALUE_PREFIX = "sive1:"

# A Keychain read is a local IPC call: it answers in milliseconds or it is
# blocked on something no shell hook should wait for.
KEYCHAIN_TIMEOUT_SECONDS = 5


class KeychainError(CredentialError):
    pass


def _login_keychain() -> Path:
    # Named on every item call: a headless SSH session's search list holds only
    # System.keychain, so an unnamed lookup never reaches the user's items.
    return Path.home() / "Library" / "Keychains" / "login.keychain-db"


def _service(vault_name: str) -> str:
    return f"{SERVICE_PREFIX}/{vault_name}"


def _friendly_account(account: str) -> str:
    if account == MASTER_PASSWORD_ACCOUNT:
        return "master password"
    if account == EMAIL_ACCOUNT:
        return "email address"
    return account.replace("_", " ")


def _encode_value(value: str) -> str:
    encoded = base64.b64encode(value.encode()).decode("ascii")
    return f"{_VALUE_PREFIX}{encoded}"


def _decode_value(value: str) -> str:
    if not value.startswith(_VALUE_PREFIX):
        return value
    encoded = value.removeprefix(_VALUE_PREFIX)
    return base64.b64decode(encoded.encode("ascii")).decode()


# Fingerprints of the macOS `security` tool's own stderr.
GENERIC_SECKEYCHAIN_ERROR = "what a shameful experience"
# Matched with spaces and hyphens stripped, so one spelling covers the
# variants the tool uses across releases.
LOCKED_KEYCHAIN_MARKERS = ("userinteractionisnotallowed", "interactionnotallowed")
UNOPENABLE_KEYCHAIN_MARKER = "could not be opened"
# errSecInteractionNotAllowed: `find-generic-password` exits with it on a
# locked keychain and prints nothing to stderr.
LOCKED_KEYCHAIN_EXIT = 36


def _sanitize_security_error(stderr: str) -> str:
    raw = stderr.strip()
    if not raw:
        return "macOS Keychain did not provide an error message."
    if GENERIC_SECKEYCHAIN_ERROR in raw:
        return "macOS returned a generic SecKeychain error."
    return raw


def _store_error(vault_name: str, account: str, stderr: str) -> KeychainError:
    secret_name = _friendly_account(account)
    details = _sanitize_security_error(stderr)
    return KeychainError(
        f"Could not save the {secret_name} in macOS Keychain.\n"
        f"\n"
        f"Vault: {vault_name}\n"
        f"Keychain item: {SERVICE_PREFIX}/{vault_name} / {account}\n"
        f"\n"
        f"Try this and run setup again:\n"
        f"  1. Open Keychain Access and unlock the login keychain.\n"
        f"  2. Or run: security unlock-keychain ~/Library/Keychains/login.keychain-db\n"
        f"  3. If the item exists but is broken, delete "
        f"'{SERVICE_PREFIX}/{vault_name}' "
        f"entries in Keychain Access.\n"
        f"\n"
        f"Keychain said: {details}"
    )


def _add_generic_password(
    service: str, account: str, encoded_value: str
) -> subprocess.CompletedProcess:
    # `man security`: -U updates an existing item in place, avoiding a delete+add
    # sequence that could leave setup half-broken when delete succeeds but add fails.
    # The CLI cannot read `-w` from stdin; without a value it prompts on /dev/tty, so
    # the encoded value is passed as an arg. Args are a list to avoid shell expansion;
    # the value is still briefly visible to local process inspectors while it runs.
    return subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            service,
            "-a",
            account,
            "-w",
            encoded_value,
            str(_login_keychain()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _is_locked_keychain_error(stderr: str) -> bool:
    compact = stderr.lower().replace(" ", "").replace("-", "")
    return any(marker in compact for marker in LOCKED_KEYCHAIN_MARKERS) or (
        UNOPENABLE_KEYCHAIN_MARKER in stderr.lower()
    )


def _is_locked(result: subprocess.CompletedProcess) -> bool:
    return result.returncode == LOCKED_KEYCHAIN_EXIT or (
        result.returncode != 0 and _is_locked_keychain_error(result.stderr or "")
    )


def _raw(result: subprocess.CompletedProcess) -> str:
    output = (result.stderr or "").strip() or "(no output)"
    return f"`{' '.join(result.args)}` exited {result.returncode}: {output}"


def _unlock_failed_error(
    keychain: Path,
    probe: subprocess.CompletedProcess,
    unlock: subprocess.CompletedProcess,
) -> KeychainError:
    return KeychainError(
        "Could not unlock the login keychain, so sive cannot read its credentials.\n"
        "\n"
        f"Keychain check: {_raw(probe)}\n"
        f"Unlock attempt: {_raw(unlock)}\n"
        "\n"
        "To fix it yourself:\n"
        "  1. Unlock with your macOS login password:\n"
        f"     security unlock-keychain {keychain}\n"
        "  2. If you changed your login password, try the previous one;\n"
        f"     once unlocked, align them: security set-keychain-password {keychain}\n"
        "  3. Then run: sive refresh"
    )


def ensure_unlocked() -> bool:
    """Offer to unlock a locked login keychain; True once it is unlocked.

    Prompts only on a terminal, so the shell hook and background sync never
    block. An accepted unlock that fails raises with both raw errors.
    """
    from . import ui  # lazy import: ui imports no core modules, so no load-time cycle

    keychain = _login_keychain()
    if not keychain.exists():
        return False
    probe = subprocess.run(
        ["security", "show-keychain-info", str(keychain)],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=KEYCHAIN_TIMEOUT_SECONDS,
    )
    if probe.returncode == 0:
        return True
    if not _is_locked(probe) or not ui.can_prompt():
        return False
    if not ui.confirm(
        "The login keychain is locked, so sive cannot read its credentials. "
        "Unlock it now?",
        default=True,
    ):
        ui.eprint(
            f"sive: keychain left locked. Unlock with:\n"
            f"  security unlock-keychain {keychain}"
        )
        return False
    # The passphrase prompt reads /dev/tty itself, so stderr can be captured.
    unlock = subprocess.run(
        ["security", "unlock-keychain", str(keychain)],
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if unlock.returncode == 0:
        return True
    raise _unlock_failed_error(keychain, probe, unlock)


def store_secret(vault_name: str, account: str, value: str) -> None:
    """Store a secret in Keychain under (service, account).

    Overwrites any existing entry.
    """
    service = _service(vault_name)
    encoded_value = _encode_value(value)
    result = _add_generic_password(service, account, encoded_value)
    # Root-cause self-heal: a locked login keychain (or a non-GUI session)
    # rejects writes with "User interaction is not allowed". Unlock once and
    # retry before surfacing an error to the user.
    if (
        result.returncode != 0
        and _is_locked_keychain_error(result.stderr)
        and ensure_unlocked()
    ):
        result = _add_generic_password(service, account, encoded_value)
    if result.returncode != 0:
        raise _store_error(vault_name, account, result.stderr)


def get_secret(vault_name: str, account: str, *, missing_hint: str = "") -> str:
    """Retrieve a secret from Keychain. Raises KeychainError if not found."""
    service = _service(vault_name)
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
                str(_login_keychain()),
            ],
            capture_output=True,
            text=True,
            check=False,
            # A locked keychain makes `security` read a passphrase from the stdin
            # it inherits. Shell hooks call this on every prompt, so an inherited
            # tty freezes the terminal: deny the read, and bound the wait.
            stdin=subprocess.DEVNULL,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise KeychainError(
            f"Keychain lookup for '{account}' in vault '{vault_name}' timed out "
            f"after {KEYCHAIN_TIMEOUT_SECONDS}s. Unlock the login keychain."
        ) from e
    if _is_locked(result):
        raise KeychainError(
            f"macOS Keychain is locked; cannot read '{account}' for vault "
            f"'{vault_name}'.\nRun 'sive refresh' to unlock it and sync.\n"
            f"Keychain said: {_raw(result)}"
        )
    if result.returncode != 0:
        hint = missing_hint or "Run 'sive setup' to store it."
        raise KeychainError(
            f"Keychain entry '{account}' for vault '{vault_name}' not found.\n{hint}"
        )
    return _decode_value(result.stdout.strip())


def delete_secret(vault_name: str, account: str) -> None:
    """Remove a secret from Keychain (best-effort)."""
    service = _service(vault_name)
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            service,
            "-a",
            account,
            str(_login_keychain()),
        ],
        capture_output=True,
        check=False,
    )


def store_password(vault_name: str, password: str) -> None:
    """Store master password in Keychain."""
    store_secret(vault_name, MASTER_PASSWORD_ACCOUNT, password)


def get_password(vault_name: str) -> str:
    """Retrieve master password from Keychain. Raises KeychainError if not found."""
    return get_secret(
        vault_name,
        MASTER_PASSWORD_ACCOUNT,
        missing_hint="Run 'sive setup' to store it.",
    )


def delete_password(vault_name: str) -> None:
    """Remove master password from Keychain (best-effort)."""
    delete_secret(vault_name, MASTER_PASSWORD_ACCOUNT)


_EMAIL_ACCOUNT = "email"


def store_email(vault_name: str, email: str) -> None:
    store_secret(vault_name, _EMAIL_ACCOUNT, email)


def get_email(vault_name: str) -> str | None:
    try:
        return get_secret(vault_name, _EMAIL_ACCOUNT)
    except KeychainError:
        return None


class MacOSKeychainStore:
    """Adapt the bounded macOS `security` CLI to the credential port."""

    ensure_unlocked = staticmethod(ensure_unlocked)
    store_secret = staticmethod(store_secret)
    get_secret = staticmethod(get_secret)
    delete_secret = staticmethod(delete_secret)
    store_password = staticmethod(store_password)
    get_password = staticmethod(get_password)
    delete_password = staticmethod(delete_password)
    store_email = staticmethod(store_email)
    get_email = staticmethod(get_email)
