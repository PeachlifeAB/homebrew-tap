import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from lgtvctrl import __version__, auth, query, raw, screen
from lgtvctrl import brightness as brightness_module
from lgtvctrl import input as input_module
from lgtvctrl import power as power_module
from lgtvctrl import volume as volume_module
from lgtvctrl.composition import display_recovery
from lgtvctrl.config import STATE_DIR, Config
from lgtvctrl.log import setup_logging
from lgtvctrl.status import get_status
from lgtvctrl.webos import get_client

try:
    import fcntl  # macOS/Linux; absent on Windows
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


# Subcommand action names. Declared once: the parser registers them, the
# handlers dispatch on them, and the usage messages list them.
UP, DOWN, SET, GET = "up", "down", "set", "get"
ON, OFF, STATUS = "on", "off", "status"
FAVORITE, LIST = "favorite", "list"
LEVEL_ACTIONS = (UP, DOWN, SET, GET)

# Step sizes chosen per control: brightness moves in coarser increments
# than volume.
DIM_STEP_DEFAULT = 5
VOLUME_STEP_DEFAULT = 1

# Flags handled before the TV lock is taken: they never reach the TV.
HELP_FLAGS = ("--version", "-h", "--help")
POWER_COMMAND = "power"
# argparse exits 2 on a usage error, anything else is a normal early exit.
ARGPARSE_USAGE_ERROR = 2


def _lock_path() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / "lgtvctrl.lock"


@contextmanager
def webos_lock():
    if fcntl is None:
        yield
        return

    path = _lock_path()
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _missing_action(action: str | None, expected: str) -> bool:
    """Report a missing sub-action. True means the command cannot proceed."""
    if action:
        return False
    print(f"Error: {expected}", file=sys.stderr)
    return True


async def _auth(_args: argparse.Namespace, _client: object) -> int:
    await auth.setup()
    return 0


async def _status(_args: argparse.Namespace, _client: object) -> int:
    print(json.dumps(asdict(await get_status()), indent=2, sort_keys=True))
    return 0


async def _dim(args: argparse.Namespace, client: object) -> int:
    if _missing_action(
        args.dim_action, f"dim action required: {'|'.join(LEVEL_ACTIONS)}"
    ):
        return 1
    if args.dim_action == UP:
        await brightness_module.increase(client, args.amount, dynamic=args.dynamic)
    elif args.dim_action == DOWN:
        await brightness_module.decrease(client, args.amount, dynamic=args.dynamic)
    elif args.dim_action == SET:
        if args.dynamic:
            await brightness_module.apply_level_dynamic(client, args.level)
        else:
            await brightness_module.apply_level_simple(client, args.level)
    elif args.dim_action == GET:
        await brightness_module.get_level(client, dynamic=args.dynamic)
    return 0


async def _screen(args: argparse.Namespace, client: object) -> int:
    if _missing_action(
        args.screen_action, f"screen action required: {ON}|{OFF}|{STATUS}"
    ):
        return 1
    if args.screen_action == ON:
        await screen.turn_on(client)
    elif args.screen_action == OFF:
        await screen.turn_off(client)
    elif args.screen_action == STATUS:
        state = await screen.get_state(client)
        print(f"Screen: {'on' if state.get('screen_on') else 'off'}")
        print(f"State: {state.get('state')}")
    return 0


async def _power(args: argparse.Namespace, client: object) -> int:
    if args.power_action == ON:
        await power_module.wakeup(display_recovery())
        return 0
    if args.power_action != OFF:
        print(f"Error: power action required: {ON}|{OFF}", file=sys.stderr)
        return 1
    await power_module.standby(client)
    return 0


async def _input(args: argparse.Namespace, client: object) -> int:
    if _missing_action(
        args.input_action, f"input action required: {SET}|{FAVORITE}|{LIST}"
    ):
        return 1
    if args.input_action == SET:
        await input_module.switch_input(client, args.input_id)
    elif args.input_action == FAVORITE:
        tv = Config.get_tv_config()
        if not tv.pc_input:
            print("Error: missing 'pc_input' in config.json", file=sys.stderr)
            return 1
        await input_module.switch_input(client, tv.pc_input)
    elif args.input_action == LIST:
        inputs = await input_module.list_inputs(client)
        print(json.dumps(inputs, default=str) if args.json else inputs)
    return 0


async def _volume(args: argparse.Namespace, client: object) -> int:
    if _missing_action(
        args.volume_action, f"volume action required: {'|'.join(LEVEL_ACTIONS)}"
    ):
        return 1
    if args.volume_action == UP:
        await volume_module.volume_up(client, args.amount)
    elif args.volume_action == DOWN:
        await volume_module.volume_down(client, args.amount)
    elif args.volume_action == SET:
        await volume_module.volume_set(client, args.level)
    elif args.volume_action == GET:
        await volume_module.volume_get(client)
    return 0


_NAMED_QUERIES = {
    "picture": "picture",
    "picture-all": "picture_all",
    "inputs": "inputs",
    "apps": "apps",
    "system": "system",
    "update-status": "update_status",
}


async def _query(args: argparse.Namespace, client: object) -> int:
    attribute = _NAMED_QUERIES.get(args.setting)
    if attribute is None:
        await query.generic(client, args.setting)
    else:
        await getattr(query, attribute)(client)
    return 0


async def _picture_all(_args: argparse.Namespace, client: object) -> int:
    await query.picture_all(client)
    return 0


async def _raw(args: argparse.Namespace, client: object) -> int:
    print(await raw.execute(client, args.raw_command, *args.args))
    return 0


def _add_level_commands(
    subparsers: argparse._SubParsersAction,
    name: str,
    handler: object,
    *,
    step_default: int,
) -> argparse.ArgumentParser:
    """Register an up/down/set/get group, the shape dim and volume share."""
    parser = subparsers.add_parser(name)
    parser.set_defaults(func=handler, needs_client=True)
    actions = parser.add_subparsers(dest=f"{name}_action")
    for step in (UP, DOWN):
        actions.add_parser(step).add_argument(
            "amount", nargs="?", type=int, default=step_default
        )
    actions.add_parser(SET).add_argument("level", type=int)
    actions.add_parser(GET)
    return parser


def _add_screen_and_power(subparsers: argparse._SubParsersAction) -> None:
    screen_parser = subparsers.add_parser("screen")
    screen_parser.set_defaults(func=_screen, needs_client=True)
    screen_actions = screen_parser.add_subparsers(dest="screen_action")
    for action in (ON, OFF, STATUS):
        screen_actions.add_parser(action)

    power_parser = subparsers.add_parser("power")
    power_parser.set_defaults(func=_power, needs_client=True)
    power_actions = power_parser.add_subparsers(dest="power_action")
    for action in (ON, OFF):
        power_actions.add_parser(action)


def _add_input(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("input")
    parser.set_defaults(func=_input, needs_client=True)
    actions = parser.add_subparsers(dest="input_action")
    actions.add_parser(SET).add_argument("input_id")
    actions.add_parser(FAVORITE)
    actions.add_parser(LIST).add_argument("--json", action="store_true")


def _add_query_and_raw(subparsers: argparse._SubParsersAction) -> None:
    query_parser = subparsers.add_parser("query")
    query_parser.set_defaults(func=_query, needs_client=True)
    query_parser.add_argument("setting", nargs="?", default="picture")

    subparsers.add_parser("picture-all").set_defaults(
        func=_picture_all, needs_client=True
    )

    raw_parser = subparsers.add_parser("raw")
    raw_parser.set_defaults(func=_raw, needs_client=True)
    raw_parser.add_argument("raw_command")
    raw_parser.add_argument("args", nargs="*")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tv", description="Control LG TV")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    dim = _add_level_commands(subparsers, "dim", _dim, step_default=DIM_STEP_DEFAULT)
    dim.add_argument("--dynamic", action="store_true")
    _add_level_commands(subparsers, "volume", _volume, step_default=VOLUME_STEP_DEFAULT)

    _add_screen_and_power(subparsers)
    _add_input(subparsers)
    _add_query_and_raw(subparsers)

    subparsers.add_parser("status").set_defaults(func=_status, needs_client=False)
    subparsers.add_parser("auth").set_defaults(func=_auth, needs_client=False)
    subparsers.add_parser("help")
    return parser


async def main_async(argv: list[str] | None = None) -> int:
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 1 if e.code == ARGPARSE_USAGE_ERROR else 0

    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return 0

    if not args.needs_client:
        return await handler(args, None)

    async with get_client() as client:
        return await handler(args, client)


def main(argv: list[str] | None = None) -> int:
    effective = argv if argv is not None else sys.argv[1:]

    def run() -> int:
        try:
            return int(asyncio.run(main_async(effective)))
        except KeyboardInterrupt:
            return 1
        except Exception as e:  # noqa: BLE001
            # Top of the CLI: every failure below becomes an exit code and a
            # message rather than a traceback.
            print(f"Error: {e}", file=sys.stderr)
            return 1

    setup_logging()

    if not effective or any(flag in effective for flag in HELP_FLAGS):
        return run()
    if effective[0] in {"help", "auth"}:
        return run()
    if effective[:2] == [POWER_COMMAND, ON]:
        return run()

    with webos_lock():
        return run()


if __name__ == "__main__":
    sys.exit(main())
