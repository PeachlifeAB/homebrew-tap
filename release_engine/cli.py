from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from .adapters import GitAdapter, GitHubAdapter, SubprocessAdapter, require_commands
from .manifest import load_manifest
from .models import Handoff, ReleaseError
from .observation import print_observation, project_version
from .producer import ProducerRelease
from .tap import TapRelease


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Release Peachlife products through Homebrew."
    )
    parser.add_argument("--product", required=True, choices=("sive", "bgtail"))
    parser.add_argument("--project-root", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "observe",
        "verify",
        "prepare",
        "publish",
        "resume",
        "post-verify",
        "release",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("version")
        if name in {"prepare", "publish", "release"}:
            command.add_argument("--dry-run", action="store_true")
    return parser


def _components(args: argparse.Namespace):
    tap_root = Path(__file__).resolve().parents[1]
    project_root = args.project_root.resolve()
    manifest = load_manifest(tap_root, args.product)
    process = SubprocessAdapter()
    git = GitAdapter(process)
    github = GitHubAdapter(process)
    producer = ProducerRelease(manifest, project_root, process, git, github)
    tap = TapRelease(tap_root, manifest, process, git, github)
    return tap_root, project_root, manifest, process, github, producer, tap


def _existing_pull_request(github: GitHubAdapter, product: str, version: str):
    return github.pull_request(
        "PeachlifeAB/homebrew-tap", f"release/{product}-{version}"
    )


def _live_handoff(manifest, process, github, version: str) -> Handoff:
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
):
    commit = producer.commit_tag_push(args.version, dry_run=args.dry_run)
    handoff = producer.build_release(args.version, commit, dry_run=args.dry_run)
    print(handoff.to_json(), end="")
    return tap.create_formula_pull_request(handoff, dry_run=args.dry_run)


def _resume(args: argparse.Namespace, manifest, process, github, producer, tap):
    observation = producer.observe(args.version)
    if observation.remote_tag_commit is None:
        if project_version(producer.project_root) != args.version:
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
        pull_request = _existing_pull_request(github, manifest.name, args.version)
        if pull_request is None:
            pull_request = tap.create_formula_pull_request(handoff, dry_run=False)
    tap.wait_and_publish(*pull_request)
    tap.post_verify(args.version, producer.project_root)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_commands(("git", "gh", "uv", "task", "brew", "curl"))
        _, project_root, manifest, process, github, producer, tap = _components(args)
        if args.command == "observe":
            print_observation(producer.observe(args.version))
        elif args.command == "verify":
            producer.verify_prepared(args.version)
            print_observation(producer.observe(args.version))
        elif args.command == "prepare":
            producer.prepare(args.version, dry_run=args.dry_run)
        elif args.command == "publish":
            pull_request = _publish_prepared(args, producer, tap)
            if not args.dry_run:
                tap.wait_and_publish(*pull_request)
        elif args.command == "post-verify":
            tap.post_verify(args.version, project_root)
        elif args.command == "release":
            if args.dry_run:
                producer.prepare(args.version, dry_run=True)
                print(
                    f"[dry-run] commit, tag, push, publish {manifest.asset_name(args.version)}"
                )
                print(
                    "[dry-run] create formula pull request, wait for bottles, run brew pr-pull"
                )
                print(f"[dry-run] brew update && brew upgrade {manifest.formula}")
            else:
                producer.prepare(args.version, dry_run=False)
                pull_request = _publish_prepared(args, producer, tap)
                tap.wait_and_publish(*pull_request)
                tap.post_verify(args.version, project_root)
        elif args.command == "resume":
            _resume(args, manifest, process, github, producer, tap)
        else:  # pragma: no cover
            raise ReleaseError(f"unsupported command: {args.command}")
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0
