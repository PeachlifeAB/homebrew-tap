"""Every subcommand stays wired to its handler.

create_parser was split into per-group helpers; these assert the registration
each helper performs, including that dim's --dynamic still precedes its
action subparsers.
"""

from lgtvctrl.main import create_parser


def test_every_subcommand_parses():
    p = create_parser()
    cases = [
        (["dim", "--dynamic", "up", "7"], "_dim", True),
        (["dim", "up", "7"], "_dim", True),
        (["volume", "up"], "_volume", True),
        (["volume", "set", "30"], "_volume", True),
        (["screen", "on"], "_screen", True),
        (["power", "off"], "_power", True),
        (["input", "list", "--json"], "_input", True),
        (["raw", "cmd", "a", "b"], "_raw", True),
        (["query", "picture"], "_query", True),
        (["picture-all"], "_picture_all", True),
        (["status"], "_status", False),
        (["auth"], "_auth", False),
    ]
    for argv, fn, needs in cases:
        ns = p.parse_args(argv)
        assert ns.func.__name__ == fn, (argv, ns.func.__name__)
        assert ns.needs_client is needs, argv
    ns = p.parse_args(["dim", "--dynamic", "up", "7"])
    assert ns.dynamic is True and ns.amount == 7
    assert p.parse_args(["dim", "up"]).amount == 5
    assert p.parse_args(["volume", "up"]).amount == 1
    assert p.parse_args(["input", "list", "--json"]).json is True
    assert p.parse_args(["raw", "cmd", "a", "b"]).args == ["a", "b"]


def test_lock_is_bypassed_only_for_commands_that_never_reach_the_tv():
    """`tv power on` wakes a sleeping TV, so it must not wait on the lock a
    hung session holds; everything that talks to a live TV must take it."""
    from unittest.mock import patch

    from lgtvctrl import main as main_module

    def took_lock(argv):
        with (
            patch.object(main_module, "setup_logging"),
            patch.object(main_module, "main_async", return_value=0),
            patch.object(main_module, "webos_lock") as lock,
        ):
            main_module.main(argv)
            return lock.called

    for argv in (
        [],
        ["--help"],
        ["-h"],
        ["--version"],
        ["help"],
        ["auth"],
        ["power", "on"],
    ):
        assert not took_lock(argv), argv

    for argv in (["power", "off"], ["volume", "up"], ["status"], ["dim", "get"]):
        assert took_lock(argv), argv


def test_validate_ipv4_rejects_malformed_addresses():
    """The unpack-into-four form raised on both wrong length and non-numeric
    parts; the explicit list must keep rejecting each."""
    from lgtvctrl.auth import validate_ipv4

    # "0.0.0.0" here is a validator input, not a bind address.
    for good in ("192.168.1.10", "0.0.0.0", "255.255.255.255"):
        assert validate_ipv4(good), good

    for bad in (
        "192.168.1",
        "192.168.1.1.1",
        "192.168.1.256",
        "-1.0.0.0",
        "a.b.c.d",
        "",
        "192.168..1",
        "192.168.1.x",
    ):
        assert not validate_ipv4(bad), bad
