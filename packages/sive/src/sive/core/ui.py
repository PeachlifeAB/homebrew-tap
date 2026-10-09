"""Terminal UI helpers using gum, with plain-prompt fallback."""

from __future__ import annotations

import builtins
import getpass as _getpass
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import TextIO

# The shell's conventional code for a process killed by SIGINT: gum exits
# with it when the user presses Ctrl-C at a prompt.
SIGINT_EXIT_CODE = 130


class NonInteractiveError(Exception):
    """A prompt was needed where sive may not ask; names the flag to pass."""


# Set once by the CLI from -y/--yes, --no-input and the answer flags.
_assume_yes = False
_no_input = False
_answers: dict[str, str] = {}


def configure(
    *,
    assume_yes: bool = False,
    no_input: bool = False,
    answers: dict[str, str] | None = None,
) -> None:
    global _assume_yes, _no_input, _answers
    _assume_yes = assume_yes
    _no_input = no_input
    _answers = dict(answers or {})


def can_prompt() -> bool:
    return not _no_input and sys.stdin.isatty()


def _answer(prompt: str, flag: str) -> str | None:
    """Return the flag's answer, None to prompt, or raise when sive may not ask."""
    if flag in _answers:
        return _answers[flag]
    if not can_prompt():
        needed = flag or f"an answer to '{prompt}'"
        raise NonInteractiveError(f"{needed} is required without a terminal")
    return None


def _run_gum(
    args: list[str], *, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run gum, turning Ctrl-C into KeyboardInterrupt.

    A non-zero exit that is not Ctrl-C raises FileNotFoundError so the
    caller's existing fallback path handles a missing or unusable gum the
    same way, whichever it turns out to be.
    """
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE if capture else None,
        text=True,
        check=False,
    )
    if result.returncode == SIGINT_EXIT_CODE:
        raise KeyboardInterrupt
    return result


def echo(
    *values: object, sep: str = " ", end: str = "\n", file: TextIO | None = None
) -> None:
    """Write terminal output without using debug-style print calls."""
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


def eprint(*values: object, sep: str = " ", end: str = "\n") -> None:
    """Write terminal error output."""
    echo(*values, sep=sep, end=end, file=sys.stderr)


def ensure_homebrew_command(
    command: str,
    formula: str,
    noun: str,
    *,
    fallback: str = "",
) -> bool:
    """Ensure a command exists, offering a Homebrew install when missing."""
    if shutil.which(command):
        return True

    echo(f"  {noun} not found.")
    if confirm(f"Install {noun} with Homebrew now?", default=True):
        try:
            install = subprocess.run(["brew", "install", formula], check=False)
        except FileNotFoundError:
            install = subprocess.CompletedProcess(["brew", "install", formula], 127)
        if install.returncode == 0 and shutil.which(command):
            return True
        echo(f"  Homebrew install did not make '{command}' available.")

    echo(f"  Install it: brew install {formula}")
    if fallback:
        echo(f"  Or: {fallback}")
    return False


def style(
    text: str,
    *,
    bold: bool = False,
    foreground: str = "",
    background: str = "",
    padding: str = "",
) -> None:
    """Print styled text via gum style; falls back to plain print."""
    try:
        args = ["style"]
        if bold:
            args += ["--bold"]
        if foreground:
            args += ["--foreground", foreground]
        if background:
            args += ["--background", background]
        if padding:
            args += ["--padding", padding]
        args.append(text)
        _run_gum(["gum", *args], capture=False)
    except FileNotFoundError:
        echo(text)


def input(prompt: str, *, placeholder: str = "", flag: str = "") -> str:
    """Prompt for a single line of text. Falls back to built-in input()."""
    answer = _answer(prompt, flag)
    if answer is not None:
        return answer
    try:
        args = ["gum", "input", "--prompt", f"{prompt}: "]
        if placeholder:
            args += ["--placeholder", placeholder]
        result = _run_gum(args)
        if result.returncode != 0:
            raise FileNotFoundError
        return result.stdout.strip()
    except FileNotFoundError:
        return builtins.input(f"  {prompt}: ").strip()


def password(prompt: str, *, flag: str = "") -> str:
    """Prompt for a hidden password. Falls back to getpass."""
    answer = _answer(prompt, flag)
    if answer is not None:
        return answer
    try:
        args = ["gum", "input", "--password", "--prompt", f"{prompt}: "]
        result = _run_gum(args)
        if result.returncode != 0:
            raise FileNotFoundError
        return result.stdout.strip()
    except FileNotFoundError:
        return _getpass.getpass(f"  {prompt}: ")


def confirm(prompt: str, *, default: bool = True) -> bool:
    """Ask a yes/no question. Falls back to y/n input loop."""
    if _assume_yes:
        return True
    if not can_prompt():
        raise NonInteractiveError(f"'{prompt}' needs confirmation: rerun with --yes")
    try:
        args = ["gum", "confirm", prompt]
        if default:
            args += ["--default"]
        result = _run_gum(args, capture=False)
        if result.returncode not in (0, 1):
            raise FileNotFoundError
        return result.returncode == 0
    except FileNotFoundError:
        return _confirm_plain(prompt, default=default)


def _confirm_plain(prompt: str, *, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        raw = builtins.input(f"  {prompt} {hint}: ").strip().lower()
        if raw in ("", "y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def spin[T](title: str, fn: Callable[[], T]) -> T:
    """Show progress text, then run fn() and propagate its result."""
    echo(f"  {title}")
    return fn()


def choose(
    header: str,
    options: list[str],
    *,
    selected: list[str] | None = None,
    flag: str = "",
) -> list[str]:
    """Multi-select checkbox list via gum choose --no-limit.

    Falls back to plain input when gum is unavailable.
    """
    if not options:
        return []
    if not can_prompt():
        needed = flag or f"a choice for '{header}'"
        raise NonInteractiveError(f"{needed} is required without a terminal")
    try:
        args = [
            "gum",
            "choose",
            "--no-limit",
            "--header",
            header,
            "--cursor",
            "> ",
            "--cursor-prefix",
            "[ ] ",
            "--selected-prefix",
            "[✓] ",
            "--unselected-prefix",
            "[ ] ",
        ]
        if selected:
            args += ["--selected", ",".join(selected)]
        args += options
        result = _run_gum(args)
        if result.returncode != 0:
            raise FileNotFoundError
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except FileNotFoundError:
        echo(f"  {header}")
        for opt in options:
            echo(f"    • {opt}")
        raw = builtins.input("  Enter choices (space or comma separated): ").strip()
        chosen = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
        valid = set(options)
        return [c for c in chosen if c in valid]
