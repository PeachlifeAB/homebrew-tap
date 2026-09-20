from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from app.composition import Components, build

from ..application.observation import print_observation, project_version
from ..application.ports import GitHubPort, ProcessPort
from ..application.producer import ProducerRelease
from ..application.tap import TapRelease
from ..domain.models import Handoff, ProductManifest, ReleaseError
from ..infrastructure.adapters import require_commands

TAP_ROOT = Path(__file__).resolve().parents[4]


class Command(StrEnum):
    OBSERVE = "observe"
    VERIFY = "verify"
    PREPARE = "prepare"
    PUBLISH = "publish"
    RESUME = "resume"
    POST_VERIFY = "post-verify"
    RELEASE = "release"


DRY_RUN_COMMANDS = frozenset({Command.PREPARE, Command.PUBLISH, Command.RELEASE})


def releasable_products() -> tuple[str, ...]:
    """The products with a manifest, which is what makes one releasable.

    Listing them here as literals let `lgtvctrl` gain a manifest without
    becoming selectable.
    """
    manifests = (TAP_ROOT / "release-products").glob("*.toml")
    return tuple(sorted(path.stem for path in manifests))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Release Peachlife products through Homebrew."
    )
    parser.add_argument("--product", required=True, choices=releasable_products())
    parser.add_argument("--project-root", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in Command:
        command = subparsers.add_parser(name)
        command.add_argument("version")
        if name in DRY_RUN_COMMANDS:
            command.add_argument("--dry-run", action="store_true")
    return parser


def _components(args: argparse.Namespace) -> Components:
    return build(args.product, args.project_root)


def _existing_pull_request(
    github: GitHubPort, product: str, version: str
) -> tuple[int, str] | None:
    return github.pull_request(
        "PeachlifeAB/homebrew-tap", f"release/{product}-{version}"
    )


def _live_handoff(
    manifest: ProductManifest,
    process: ProcessPort,
    github: GitHubPort,
    version: str,
) -> Handoff:
    tag = manifest.tag(version)
    commit = github.tag_commit(manifest.repository, tag)
    if commit is None:
        raise ReleaseError(f"live tag unavailable: {tag}")
    source_url = manifest.asset_url(version)
    content = process.read_bytes(
        ["curl", "--fail", "--silent", "--show-error", "--location", source_url],
        cwd=Path.cwd(),
    )
    return Handoff(
        schema_version=1,
        product=manifest.name,
        repository=manifest.repository,
        version=version,
        tag=tag,
        commit=commit,
        source_url=source_url,
        source_sha256=hashlib.sha256(content).hexdigest(),
    )


def _publish_prepared(
    args: argparse.Namespace, producer: ProducerRelease, tap: TapRelease
) -> tuple[int, str]:
    commit = producer.commit_tag_push(args.version, dry_run=args.dry_run)
    handoff = producer.build_release(args.version, commit, dry_run=args.dry_run)
    print(handoff.to_json(), end="")
    return tap.create_formula_pull_request(handoff, dry_run=args.dry_run)


def _resume(args: argparse.Namespace, c: Components) -> None:
    manifest, process, github = c.manifest, c.process, c.github
    producer, tap = c.producer, c.tap
    observation = producer.observe(args.version)
    if observation.remote_tag_commit is None:
        if (
            project_version(producer.project_root, producer.manifest.package)
            != args.version
        ):
            producer.prepare(args.version, dry_run=False)
        commit = producer.commit_tag_push(args.version, dry_run=False)
        handoff = producer.build_release(args.version, commit, dry_run=False)
        pull_request = tap.create_formula_pull_request(handoff, dry_run=False)
    else:
        if not observation.github_release_exists:
            handoff = producer.build_release(
                args.version, observation.remote_tag_commit, dry_run=False
            )
        else:
            handoff = _live_handoff(manifest, process, github, args.version)
        existing = _existing_pull_request(github, manifest.name, args.version)
        pull_request = existing or tap.create_formula_pull_request(
            handoff, dry_run=False
        )
    tap.wait_and_publish(*pull_request)
    tap.post_verify(args.version, producer.project_root)


def _observe(args: argparse.Namespace, c: Components) -> None:
    print_observation(c.producer.observe(args.version))


def _verify(args: argparse.Namespace, c: Components) -> None:
    c.producer.verify_prepared(args.version)
    print_observation(c.producer.observe(args.version))


def _prepare(args: argparse.Namespace, c: Components) -> None:
    c.producer.prepare(args.version, dry_run=args.dry_run)


def _publish(args: argparse.Namespace, c: Components) -> None:
    pull_request = _publish_prepared(args, c.producer, c.tap)
    if not args.dry_run:
        c.tap.wait_and_publish(*pull_request)


def _post_verify(args: argparse.Namespace, c: Components) -> None:
    c.tap.post_verify(args.version, c.project_root)


def _release_dry_run(args: argparse.Namespace, c: Components) -> None:
    c.producer.prepare(args.version, dry_run=True)
    print(f"[dry-run] commit, tag, push, publish {c.manifest.asset_name(args.version)}")
    print("[dry-run] create formula pull request, wait for bottles, run brew pr-pull")
    print(f"[dry-run] brew update && brew upgrade {c.manifest.formula}")


def _release(args: argparse.Namespace, c: Components) -> None:
    if args.dry_run:
        _release_dry_run(args, c)
        return
    c.producer.prepare(args.version, dry_run=False)
    pull_request = _publish_prepared(args, c.producer, c.tap)
    c.tap.wait_and_publish(*pull_request)
    c.tap.post_verify(args.version, c.project_root)


Handler = Callable[[argparse.Namespace, Components], None]


HANDLERS: dict[str, Handler] = {
    Command.OBSERVE: _observe,
    Command.VERIFY: _verify,
    Command.PREPARE: _prepare,
    Command.PUBLISH: _publish,
    Command.POST_VERIFY: _post_verify,
    Command.RELEASE: _release,
    Command.RESUME: _resume,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_commands(("git", "gh", "uv", "brew", "curl"))
        HANDLERS[args.command](args, _components(args))
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0
