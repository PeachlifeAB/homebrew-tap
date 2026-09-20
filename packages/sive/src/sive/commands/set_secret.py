"""sive set — write a secret into a Bitwarden tag folder."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ..core import ui
from ..core.bw import (
    NOT_LOGGED_IN_MARKERS,
    SECURE_NOTE_TYPE,
    BWError,
    create_folder,
    delete_item,
    find_folder_id,
    list_folders,
    list_items_in_folder,
    upsert_note,
)
from ..core.pending_queue import enqueue_pending
from ..core.project_config import read_project_tags, read_project_vault
from ..core.snapshot import read_snapshot, write_snapshot
from ..core.snapshot_crypto import ensure_key
from ..core.source_loader import SourceError, _ensure_session, load_source
from ..core.vaults import ConfigError, load_vault

_NETWORK_MARKERS = (
    "502",
    "503",
    "econnrefused",
    "timeout",
    "network",
    "fetch",
    "statuscode",
)


def _is_network_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _NETWORK_MARKERS)


def _patch_snapshot(vault_name: str, tag: str, key: str, value: str) -> None:
    """Merge key into existing local snapshot without hitting the vault."""
    try:
        ensure_key(vault_name, tag)
        env = read_snapshot(vault_name, tag) or {}
        env[key] = value
        source = f"{vault_name}.folder:env/{tag}"
        write_snapshot(vault_name, tag, env, [source])
    except Exception as e:  # noqa: BLE001
        ui.echo(f"  Warning: could not patch local snapshot — {e}", file=sys.stderr)


def _queue_offline(vault_name: str, key: str, value: str, tag: str) -> int:
    """Record a write that could not reach the vault, for the next sync.

    Only reached on the non-delete path, where run() has already established
    that a value was supplied.
    """
    enqueue_pending(vault_name, key, value, tag)
    _patch_snapshot(vault_name, tag, key, value)
    ui.echo(f"  Queued {key} (vault unreachable) — will sync when connection returns")
    return 0


def _resolve_tag(tag: str | None, vault_name: str) -> tuple[str | None, str]:
    """Fall back to the active project's last tag when none was given."""
    if tag is not None:
        return tag, vault_name
    vault_name = read_project_vault()
    project_tags = read_project_tags()
    if not project_tags:
        ui.echo(
            "sive: no active project configuration; "
            "run `sive setup` or provide `--tag`",
            file=sys.stderr,
        )
        return None, vault_name
    return project_tags[-1], vault_name


@dataclass(frozen=True)
class _VaultTarget:
    """Where a mutation lands: the tag, and the session it is applied through.

    These four travelled together through every mutation helper, and
    folder_path is always derived from tag, so it is derived here once.
    """

    tag: str
    session: str
    appdata_dir: str

    @property
    def folder_path(self) -> str:
        return f"env/{self.tag}"


def _delete_key(key: str, folder_id: str | None, target: _VaultTarget) -> int:
    if not folder_id:
        ui.echo(f"sive: tag '{target.tag}' was not found in the vault", file=sys.stderr)
        return 1
    matches = [
        item
        for item in list_items_in_folder(
            folder_id, target.session, appdata_dir=target.appdata_dir
        )
        if item.get("name") == key and item.get("type") == SECURE_NOTE_TYPE
    ]
    if not matches:
        ui.echo(
            f"sive: key '{key}' was not found in tag: {target.tag}", file=sys.stderr
        )
        return 1
    if len(matches) > 1:
        ui.echo(f"sive: key '{key}' is ambiguous in tag: {target.tag}", file=sys.stderr)
        return 1
    delete_item(matches[0]["id"], target.session, appdata_dir=target.appdata_dir)
    return 0


def _refresh_snapshot(
    vault_name: str, tag: str, source: str, session: str, *, delete: bool
) -> None:
    """Best effort: the vault already changed, so a failure here only warns."""
    try:
        ensure_key(vault_name, tag)
        env = load_source(source, session_key=session)
        write_snapshot(vault_name, tag, env, [source])
    except Exception as e:  # noqa: BLE001
        ui.echo(f"  Warning: snapshot refresh failed — {e}", file=sys.stderr)
        mutation = "deleted from" if delete else "written to"
        ui.echo(
            f"  Key was {mutation} vault but local snapshot is not yet updated.",
            file=sys.stderr,
        )


class _Queued(Exception):
    """The vault was unreachable and the write was queued instead."""


def _open_session(vault_name: str, appdata_dir: str, *, delete: bool) -> str | None:
    """Return a session, relogging in if needed. None means give up.

    Raises _Queued when the vault is unreachable on a write, since the caller
    must then report success rather than failure.
    """
    try:
        return str(_ensure_session(vault_name, None, appdata_dir=appdata_dir))
    except SourceError as e:
        if _is_network_error(e) and not delete:
            raise _Queued from e
        if NOT_LOGGED_IN_MARKERS[0] not in str(e).lower():
            ui.echo(f"sive: {e}", file=sys.stderr)
            return None

    from ..commands.setup import run_relogin

    rc, session, _ = run_relogin(vault_name)
    return session if rc == 0 and session else None


def _apply_mutation(
    key: str, secret: str, target: _VaultTarget, *, delete: bool
) -> int:
    """Delete or upsert the key. Raises _Queued if the vault went unreachable."""
    try:
        folders = list_folders(target.session, appdata_dir=target.appdata_dir)
        folder_id = find_folder_id(folders, target.folder_path)
        if delete:
            return _delete_key(key, folder_id, target)
        if not folder_id:
            folder_id = create_folder(
                target.folder_path, target.session, appdata_dir=target.appdata_dir
            )
        upsert_note(
            key, secret, folder_id, target.session, appdata_dir=target.appdata_dir
        )
    except BWError as e:
        if _is_network_error(e) and not delete:
            raise _Queued from e
        ui.echo(f"sive: {e}", file=sys.stderr)
        return 1
    return 0


def run(
    key: str,
    value: str | None = None,
    tag: str | None = None,
    vault_name: str = "personal",
    *,
    delete: bool = False,
) -> int:
    if value is None and not delete:
        ui.echo("sive: a value is required unless deleting", file=sys.stderr)
        return 1
    # Narrowed once here rather than re-asserted at each use: `python -O`
    # strips assert statements, so an assert-guarded invariant would vanish.
    secret = "" if value is None else value

    tag, vault_name = _resolve_tag(tag, vault_name)
    if tag is None:
        return 1

    source = f"{vault_name}.folder:env/{tag}"

    try:
        vault = load_vault(vault_name)
    except ConfigError as e:
        ui.echo(f"sive: {e}", file=sys.stderr)
        return 1

    appdata_dir = str(vault.appdata_dir)

    try:
        session = _open_session(vault_name, appdata_dir, delete=delete)
    except _Queued:
        return _queue_offline(vault_name, key, secret, tag)
    if session is None:
        return 1

    try:
        target = _VaultTarget(tag=tag, session=session, appdata_dir=appdata_dir)
        rc = _apply_mutation(key, secret, target, delete=delete)
    except _Queued:
        return _queue_offline(vault_name, key, secret, tag)
    if rc != 0:
        return rc

    ui.echo(
        f"  {'Deleted' if delete else 'Saved'} {key} "
        f"{'from' if delete else 'to'} tag: {tag}"
    )
    _refresh_snapshot(vault_name, tag, source, session, delete=delete)
    return 0
