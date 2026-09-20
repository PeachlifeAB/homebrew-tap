"""sive — entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys

from . import __version__
from .core import ui


def _version_string() -> str:
    try:
        import os

        package_dir = os.path.dirname(os.path.abspath(__file__))
        repo_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=package_dir,
            check=False,
        )
        if repo_result.returncode != 0:
            return f"sive {__version__}"

        repo_root = repo_result.stdout.strip()
        # Only trust the hash when cli.py is at <repo>/src/sive/cli.py (a dev checkout);
        # an installed copy in site-packages would otherwise resolve an ancestor repo
        # such as Homebrew's and report its hash.
        if os.path.join(repo_root, "src", "sive") != package_dir:
            return f"sive {__version__}"
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )
        if result.returncode == 0:
            short_hash = result.stdout.strip()
            return f"sive {__version__} ({short_hash})"
    except (OSError, subprocess.SubprocessError):
        # git absent or not a repository: the plain version is correct then.
        pass
    return f"sive {__version__}"


def main() -> None:
    try:
        _main()
    except KeyboardInterrupt:
        ui.echo("\nAborted.", file=sys.stderr)
        sys.exit(130)


def _print_top_level_help() -> None:
    ui.echo(
        "usage: sive [-h] [--version] <command> [<args>]\n\n"
        "Make secrets available automatically for the current project.\n\n"
        "commands:\n"
        "  setup     Configure current project directory\n"
        "  set       Write or delete a secret in a tag folder\n"
        "  delete    Delete a secret by moving it to vault trash\n"
        "  refresh   Sync local encrypted snapshots from the vault\n\n"
        "options:\n"
        "  -h, --help  show this help message and exit\n"
        "  --version   show program's version number and exit\n\n"
        "Examples:\n"
        "  sive setup\n"
        "  sive setup --tag work --tag personal\n"
        "  sive set OPENAI_API_KEY\n"
        "  sive set OPENAI_API_KEY --tag work\n"
        "  sive delete OPENAI_API_KEY --tag work\n"
        "  sive refresh"
    )


_VAULT_HELP = "Vault name (default: personal)"


def _read_secret_value(args: argparse.Namespace) -> str:
    """Resolve the value to store: flag, stdin, or an interactive prompt."""
    if args.value is not None:
        return str(args.value)

    if args.stdin or not sys.stdin.isatty():
        value = sys.stdin.read().strip()
        if not value:
            ui.echo("sive: stdin is empty", file=sys.stderr)
            sys.exit(1)
        return value

    try:
        return str(ui.password(f"Value for {args.key}"))
    except EOFError:
        ui.echo("No input received, aborting.", file=sys.stderr)
        sys.exit(1)


# Subcommand names, shared with the parser that registers them.
CMD_SET = "set"
CMD_DELETE = "delete"


def _run_set_or_delete(args: argparse.Namespace) -> int:
    from .commands.set_secret import run

    if args.command == CMD_DELETE or args.delete:
        if args.command == CMD_SET and (args.value is not None or args.stdin):
            ui.eprint("sive: --delete does not accept a value or --stdin")
            return 1
        return int(run(args.key, tag=args.tag, vault_name=args.vault, delete=True))

    value = _read_secret_value(args)
    return int(run(args.key, value, tag=args.tag, vault_name=args.vault))


def _run_setup(args: argparse.Namespace) -> int:
    from .commands.setup import run_project_setup

    return int(run_project_setup(tags=args.tags, no_global=args.no_global))


def _run_status(_args: argparse.Namespace) -> int:
    from .commands.status import run

    return int(run())


def _run_mise_env(args: argparse.Namespace) -> int:
    from .commands.mise_env import run

    return int(run(args.tags, output_format=args.format))


def _run_refresh(args: argparse.Namespace) -> int:
    from .commands.refresh import run

    return int(run(vault_name=args.vault, sources=args.sources))


def _run_sync_vault(args: argparse.Namespace) -> int:
    from .core.sync_state import run_sync_vault

    return int(run_sync_vault(args.vault_name))


_COMMANDS = {
    "setup": _run_setup,
    "status": _run_status,
    "_mise-env": _run_mise_env,
    "refresh": _run_refresh,
    "set": _run_set_or_delete,
    "delete": _run_set_or_delete,
    "_sync-vault": _run_sync_vault,
}


_TAG_OVERRIDE_HELP = "Override the target tag (default: most-specific active tag)"
_KEY_HELP = "Variable name (e.g. MY_API_KEY)"


def _add_secret_target(parser: argparse.ArgumentParser) -> None:
    """The key, tag and vault every secret-mutating command takes."""
    parser.add_argument("key", help=_KEY_HELP)
    parser.add_argument("--tag", default=None, help=_TAG_OVERRIDE_HELP)
    parser.add_argument("--vault", default="personal", help=_VAULT_HELP)


def _add_setup(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("setup", help="Configure current project directory")
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        metavar="TAG",
        help="Tag to load in this project (repeatable); omit to be prompted",
    )
    parser.add_argument(
        "--no-global",
        action="store_true",
        default=False,
        help="Do not auto-include the 'global' tag (strict isolation)",
    )


def _add_internal(subparsers: argparse._SubParsersAction) -> None:
    """Commands the mise hook calls, hidden from help."""
    subparsers.add_parser("status", help=argparse.SUPPRESS)

    mise_env = subparsers.add_parser("_mise-env", help=argparse.SUPPRESS)
    mise_env.add_argument(
        "--tag", action="append", dest="tags", help="Tag name, e.g. global"
    )
    mise_env.add_argument(
        "--format", choices=("json", "sh"), default="json", help=argparse.SUPPRESS
    )

    subparsers.add_parser("_sync-vault", help=argparse.SUPPRESS).add_argument(
        "vault_name"
    )


def _add_refresh(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "refresh", help="Sync local encrypted snapshots from the vault"
    )
    parser.add_argument("--vault", default="personal", help=_VAULT_HELP)
    parser.add_argument(
        "--source", action="append", dest="sources", help="Override source specs"
    )


def _add_set_and_delete(subparsers: argparse._SubParsersAction) -> None:
    set_parser = subparsers.add_parser(
        CMD_SET, help="Write or delete a secret in a tag folder"
    )
    set_parser.add_argument("key", help=_KEY_HELP)
    set_parser.add_argument(
        "value", nargs="?", help="Secret value (avoid for sensitive values)"
    )
    set_parser.add_argument("--tag", default=None, help=_TAG_OVERRIDE_HELP)
    set_parser.add_argument("--vault", default="personal", help=_VAULT_HELP)
    set_parser.add_argument(
        "--delete", action="store_true", help="Move the key to vault trash"
    )
    set_parser.add_argument(
        "--stdin", action="store_true", help="Read the secret value from stdin"
    )

    _add_secret_target(
        subparsers.add_parser(
            CMD_DELETE, help="Delete a secret by moving it to vault trash"
        )
    )


def _main() -> None:
    if len(sys.argv) == 1 or sys.argv[1] in {"-h", "--help"}:
        _print_top_level_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="sive",
        description="Make secrets available automatically for the current project.",
        epilog=(
            "Examples:\n"
            "  sive setup\n"
            "  sive setup --tag work --tag personal\n"
            "  sive set OPENAI_API_KEY\n"
            "  sive set OPENAI_API_KEY --tag work\n"
            "  printf %s 'my-secret-value' | sive set MY_KEY\n"
            "  sive delete OPENAI_API_KEY --tag work\n"
            "  sive refresh"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=_version_string())

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    _add_setup(subparsers)
    _add_internal(subparsers)
    _add_refresh(subparsers)
    _add_set_and_delete(subparsers)

    args = parser.parse_args()

    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(0)
    sys.exit(handler(args))
