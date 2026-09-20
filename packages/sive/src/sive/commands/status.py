"""sive status — show vault state and active tags."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from ..core import ui
from ..core.bw import BWError, BWNotInstalledError, get_status
from ..core.keychain_macos import KeychainError, get_password
from ..core.project_config import read_project_tags
from ..core.sync_state import load_sync_state, sync_is_stale
from ..core.vaults import ConfigError, load_vault
from .setup import ENV_CACHE_KEY, MISE_SOURCE_KEY, SIVE_MARKER


def _print_vault(vault, status: dict[str, str], *, keychain_ok: bool) -> None:
    server_url = status.get("serverUrl") or vault.server
    ui.echo("Vault:")
    ui.echo(f"  name: {vault.name}")
    ui.echo(f"  configured server: {vault.server}")
    ui.echo(f"  current server: {server_url}")
    matches = server_url.rstrip("/") == vault.server.rstrip("/")
    ui.echo(f"  server matches config: {'yes' if matches else 'no'}")
    ui.echo(f"  appdata dir: {vault.appdata_dir}")
    ui.echo(f"  status: {status.get('status', 'unknown')}")
    ui.echo(f"  keychain: {'ok' if keychain_ok else 'not set'}")
    user_email = status.get("userEmail", "")
    if user_email:
        ui.echo(f"  user: {user_email}")


def _print_tags(project_tags: list[str], *, hook_configured: bool) -> None:
    ui.echo("Active tags:")
    if not hook_configured:
        ui.echo("  sive not configured in mise")
    elif project_tags:
        for tag in project_tags:
            ui.echo(f"  - {tag}")
    else:
        ui.echo("  - global (default, no .sive in this directory)")


def _print_sync(vault_name: str, sync_state: dict[str, str]) -> None:
    ui.echo("Background sync:")
    ui.echo(
        f"  last successful sync: {sync_state.get('last_successful_sync_at', 'never')}"
    )
    ui.echo(f"  last attempt: {sync_state.get('last_attempt_at', 'never')}")
    ui.echo(f"  stale: {'yes' if sync_is_stale(vault_name) else 'no'}")
    if sync_state.get("last_error"):
        ui.echo(f"  last error at: {sync_state.get('last_error_at', 'unknown')}")
        ui.echo(f"  last error: {sync_state['last_error']}")


def _print_warnings(
    *, hook_configured: bool, cache_enabled: bool, server_matches: bool
) -> int:
    """Report degraded configuration. Non-zero means something needs attention."""
    if not hook_configured:
        ui.echo("Warning: sive env hook not configured in mise.", file=sys.stderr)
    if not cache_enabled:
        ui.echo("Warning: mise env_cache is disabled.", file=sys.stderr)
    if not server_matches:
        ui.echo(
            "Warning: current vault server does not match configured server.",
            file=sys.stderr,
        )
    return 1 if not (hook_configured and cache_enabled and server_matches) else 0


def _load_bw_status(vault) -> dict[str, str] | None:
    """Read bw status, reporting the actionable failures. None means give up."""
    try:
        return get_status(appdata_dir=str(vault.appdata_dir))
    except BWNotInstalledError:
        ui.echo("bw CLI: NOT INSTALLED", file=sys.stderr)
        ui.echo("  Install: brew install bitwarden-cli", file=sys.stderr)
        ui.echo("  Or: npm install -g @bitwarden/cli", file=sys.stderr)
    except BWError as e:
        ui.echo(f"bw CLI: error — {e}", file=sys.stderr)
    return None


def run() -> int:
    from .. import __version__

    ui.echo(f"sive {__version__}\n")

    try:
        vault = load_vault("personal")
    except ConfigError as e:
        ui.echo(f"Config error: {e}", file=sys.stderr)
        return 1

    status = _load_bw_status(vault)
    if status is None:
        return 1

    keychain_ok = True
    try:
        get_password("personal")
    except KeychainError:
        keychain_ok = False

    server_url = status.get("serverUrl") or vault.server
    server_matches = server_url.rstrip("/") == vault.server.rstrip("/")
    hook_configured, cache_enabled, cache_ttl = _read_mise_state()

    _print_vault(vault, status, keychain_ok=keychain_ok)
    ui.echo()
    _print_tags(read_project_tags(), hook_configured=hook_configured)

    ui.echo()
    ui.echo("Cache:")
    ui.echo(f"  mise env_cache: {'enabled' if cache_enabled else 'disabled'}")
    ui.echo(f"  mise env_cache_ttl: {cache_ttl or 'unset'}")

    ui.echo()
    _print_sync(vault.name, load_sync_state(vault.name))

    if not keychain_ok:
        ui.echo(
            "\nWarning: master password not in Keychain — silent unlock will fail.",
            file=sys.stderr,
        )
        return 1

    return _print_warnings(
        hook_configured=hook_configured,
        cache_enabled=cache_enabled,
        server_matches=server_matches,
    )


def _read_mise_state() -> tuple[bool, bool, str]:
    """Return (hook_configured, env_cache_enabled, env_cache_ttl)."""
    mise_config = Path.home() / ".config" / "mise" / "config.toml"
    if not mise_config.exists():
        return False, False, ""

    try:
        data = tomllib.loads(mise_config.read_text())
    except tomllib.TOMLDecodeError as _error:
        return False, False, ""

    settings = data.get("settings", {})
    env = data.get("env", {})
    hook_configured = (
        isinstance(env, dict)
        and MISE_SOURCE_KEY in env
        and SIVE_MARKER in str(env[MISE_SOURCE_KEY])
    )
    return (
        hook_configured,
        bool(settings.get(ENV_CACHE_KEY, False)),
        str(settings.get("env_cache_ttl", "")),
    )
