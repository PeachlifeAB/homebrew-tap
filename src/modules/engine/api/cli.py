from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from app.composition import Components, build, build_cask

from ..application.gates import run_gates
from ..application.observation import print_observation, project_version
from ..application.ports import GitHubPort, ProcessPort
from ..application.producer import ProducerRelease
from ..application.release_notes import NOTES_FILE, NotesSource, render_release_notes
from ..application.tap import TapRelease
from ..domain.models import CaskManifest, Handoff, ProductManifest, ReleaseError
from ..infrastructure.adapters import require_commands
from ..infrastructure.manifest import load_product

TAP_ROOT = Path(__file__).resolve().parents[4]


class Command(StrEnum):
    OBSERVE = "observe"
    VERIFY = "verify"
    NOTES = "notes"
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
        if name is Command.RELEASE:
            command.add_argument(
                "--check",
                action="store_true",
                help="run every gate, cheapest first, and change nothing",
            )
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
    producer.require_resumable(observation)
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


def _notes(args: argparse.Namespace, c: Components) -> None:
    """Write the product's whole CHANGELOG.md and print it for review.

    Writes nothing else: `release` checks the reviewed file and never rewrites it.
    """
    notes = render_release_notes(
        c.manifest,
        args.version,
        NotesSource(
            repository=c.tap_root,
            config=c.tap_root / "cliff.toml",
            repository_slug=c.tap.tap_repository,
        ),
        c.process,
    )
    (c.project_root / NOTES_FILE).write_text(notes.changelog + "\n", encoding="utf-8")
    print(notes.changelog)


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
    for step in c.producer.publication_steps(args.version):
        print(f"[dry-run] {step.label}")
    print(
        f"[dry-run] publish {c.manifest.asset_name(args.version)} as the release asset"
    )
    print("[dry-run] create formula pull request, wait for bottles, run brew pr-pull")
    print(f"[dry-run] brew update; brew upgrade or install {c.manifest.formula}")


def _check(args: argparse.Namespace, c: Components) -> None:
    """Every gate, cheapest first, stopping at the first failure."""
    run_gates((*c.producer.release_gates(args.version), *c.tap.release_gates()))


def _release(args: argparse.Namespace, c: Components) -> None:
    if args.check:
        _check(args, c)
        return
    if args.dry_run:
        _release_dry_run(args, c)
        return
    _check(args, c)  # nothing changes until every gate has passed
    c.producer.prepare(args.version, dry_run=False)
    pull_request = _publish_prepared(args, c.producer, c.tap)
    c.tap.wait_and_publish(*pull_request)
    c.tap.post_verify(args.version, c.project_root)


Handler = Callable[[argparse.Namespace, Components], None]


HANDLERS: dict[str, Handler] = {
    Command.OBSERVE: _observe,
    Command.VERIFY: _verify,
    Command.NOTES: _notes,
    Command.PREPARE: _prepare,
    Command.PUBLISH: _publish,
    Command.POST_VERIFY: _post_verify,
    Command.RELEASE: _release,
    Command.RESUME: _resume,
}


def _run_cask(args: argparse.Namespace, manifest: CaskManifest) -> None:
    """A cask is released by its upstream. The tap checks the generated bump
    before it is committed, and refuses every command that would build, tag or
    publish something."""
    if args.command == Command.NOTES:
        print(build_cask(manifest).announce(args.version))
        return
    if args.command != Command.RELEASE or not getattr(args, "check", False):
        raise ReleaseError(
            f"{manifest.name} is a cask, released by {manifest.repository}; "
            f"`{args.command}` is for formulae. Check a generated bump with: "
            f"release {args.version} --check"
        )
    build_cask(manifest).check(args.version)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_commands(("git", "gh", "uv", "brew", "curl"))
        product = load_product(TAP_ROOT, args.product)
        if isinstance(product, CaskManifest):
            _run_cask(args, product)
        else:
            HANDLERS[args.command](args, _components(args))
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0
