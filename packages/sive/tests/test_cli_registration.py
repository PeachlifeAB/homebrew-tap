"""Every subcommand keeps its options after the parser split.

_main registered all five commands inline; the registration now lives in
per-group helpers, so these assert what each one still accepts.
"""

from __future__ import annotations

import pytest

from sive import cli


def _parser():
    # _main builds and parses in one pass, so rebuild the same shape here.
    import argparse

    parser = argparse.ArgumentParser(prog="sive")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    cli._add_setup(subparsers)
    cli._add_internal(subparsers)
    cli._add_refresh(subparsers)
    cli._add_set_and_delete(subparsers)
    return parser


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["setup"], {"tags": None, "no_global": False}),
        (
            ["setup", "--tag", "work", "--no-global"],
            {"tags": ["work"], "no_global": True},
        ),
        (["refresh"], {"vault": "personal", "sources": None}),
        (
            ["refresh", "--vault", "w", "--source", "s"],
            {"vault": "w", "sources": ["s"]},
        ),
        (["set", "K"], {"key": "K", "value": None, "tag": None, "delete": False}),
        (
            ["set", "K", "V", "--tag", "t", "--stdin"],
            {"key": "K", "value": "V", "tag": "t", "stdin": True},
        ),
        (["set", "K", "--delete"], {"key": "K", "delete": True}),
        (["delete", "K", "--tag", "t"], {"key": "K", "tag": "t", "vault": "personal"}),
        (["_mise-env", "--tag", "global"], {"tags": ["global"]}),
        (["_sync-vault", "personal"], {"vault_name": "personal"}),
        (["status"], {}),
    ],
)
def test_subcommand_options(argv, expected):
    ns = _parser().parse_args(argv)
    assert ns.command == argv[0]
    for key, value in expected.items():
        assert getattr(ns, key) == value, key
