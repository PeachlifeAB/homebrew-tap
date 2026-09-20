from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..domain.models import Handoff, ProductManifest, ReleaseError
from .ports import GitHubPort, GitPort, ProcessPort

CHECK_DISCOVERY_ATTEMPTS = 60
PUBLISH_RUN_DISCOVERY_ATTEMPTS = 30

_TOP_LEVEL_SHA = re.compile(r'^ {2}sha256 "[0-9a-f]{64}"$', re.MULTILINE)
_BOTTLE_BLOCK = re.compile(r"\n {2}bottle do\n.*?\n {2}end\n", re.DOTALL)


def version_assertion_pattern(executable: str) -> re.Pattern[str]:
    """The formula test's version assertion, which must derive from `version`.

    What matters is that the expected string is interpolated from `version`
    rather than written as a literal: a hardcoded one silently passes against
    the previous release after a bump. The spelling is not what matters, and
    pinning one is how this check broke — it required `assert_match
    version.to_s` while every formula had moved to `assert_equal`, which is
    the stronger assertion, so each release aborted on a correct formula.
    """
    return re.compile(
        rf'assert_\w+.*\bversion\b.*shell_output\(\s*"#\{{bin\}}/{re.escape(executable)}'
        r' --version"',
    )


def source_url_pattern(repository: str) -> re.Pattern[str]:
    """The `url` stanza update_formula rewrites. It is anchored to the
    repository the manifest names, so a formula pointing elsewhere matches
    nothing and aborts the release instead of being rewritten."""
    return re.compile(
        rf'^ {{2}}url "https://github\.com/{re.escape(repository)}/[^"]+"$',
        re.MULTILINE,
    )


class TapRelease:
    def __init__(
        self,
        tap_root: Path,
        manifest: ProductManifest,
        process: ProcessPort,
        git: GitPort,
        github: GitHubPort,
    ) -> None:
        self.tap_root = tap_root.resolve()
        self.manifest = manifest
        self.process = process
        self.git = git
        self.github = github
        self.tap_repository = "PeachlifeAB/homebrew-tap"

    @property
    def formula_path(self) -> Path:
        return self.tap_root / "Formula" / f"{self.manifest.formula}.rb"

    def validate_handoff(self, handoff: Handoff) -> None:
        expected = {
            "schema_version": 1,
            "product": self.manifest.name,
            "repository": self.manifest.repository,
            "tag": self.manifest.tag(handoff.version),
            "source_url": self.manifest.asset_url(handoff.version),
        }
        actual = {
            "schema_version": handoff.schema_version,
            "product": handoff.product,
            "repository": handoff.repository,
            "tag": handoff.tag,
            "source_url": handoff.source_url,
        }
        mismatches = [key for key, value in expected.items() if actual[key] != value]
        if mismatches:
            raise ReleaseError(f"handoff mismatch: {', '.join(mismatches)}")
        if not re.fullmatch(r"[0-9a-f]{40}", handoff.commit):
            raise ReleaseError("handoff commit must be a full Git SHA")
        if not re.fullmatch(r"[0-9a-f]{64}", handoff.source_sha256):
            raise ReleaseError("handoff source_sha256 must be SHA-256")
        live_commit = self.github.tag_commit(handoff.repository, handoff.tag)
        if live_commit != handoff.commit:
            raise ReleaseError(
                f"live tag commit {live_commit or '<missing>'} "
                f"!= handoff {handoff.commit}"
            )
        content = self.process.read_bytes(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                handoff.source_url,
            ],
            cwd=self.tap_root,
        )
        live_sha = hashlib.sha256(content).hexdigest()
        if live_sha != handoff.source_sha256:
            raise ReleaseError(
                f"live source sha256 {live_sha} != handoff {handoff.source_sha256}"
            )

    def update_formula(self, handoff: Handoff) -> None:
        self.validate_handoff(handoff)
        content = self.formula_path.read_text(encoding="utf-8")
        content, url_count = source_url_pattern(self.manifest.repository).subn(
            f'  url "{handoff.source_url}"', content, count=1
        )
        content, sha_count = _TOP_LEVEL_SHA.subn(
            f'  sha256 "{handoff.source_sha256}"', content, count=1
        )
        content = _BOTTLE_BLOCK.sub("\n", content, count=1)
        if url_count != 1 or sha_count != 1:
            raise ReleaseError(
                f"formula update expected one URL/SHA, "
                f"got url={url_count}, sha={sha_count}"
            )
        if not version_assertion_pattern(self.manifest.executable).search(content):
            raise ReleaseError(
                f"formula test is not version-derived: {self.formula_path}"
            )
        self.formula_path.write_text(content, encoding="utf-8")

    def create_formula_pull_request(
        self, handoff: Handoff, *, dry_run: bool
    ) -> tuple[int, str]:
        branch = f"release/{self.manifest.name}-{handoff.version}"
        title = f"{self.manifest.name} {handoff.version}"
        if dry_run:
            print(f"[dry-run] update {self.formula_path}")
            print(f"[dry-run] push {branch} and open pull request {title!r}")
            return 0, "<dry-run>"

        dirty = self.git.output(["status", "--porcelain"], cwd=self.tap_root)
        if dirty:
            raise ReleaseError(f"tap worktree is dirty before formula update:\n{dirty}")
        self.git.run(["switch", "main"], cwd=self.tap_root)
        self.git.run(["pull", "--ff-only", "origin", "main"], cwd=self.tap_root)
        self.git.run(["switch", "-C", branch, "origin/main"], cwd=self.tap_root)
        self.update_formula(handoff)
        self.git.run(
            ["add", str(self.formula_path.relative_to(self.tap_root))],
            cwd=self.tap_root,
        )
        self.git.run(["commit", "-m", title], cwd=self.tap_root)
        self.git.run(
            ["push", "--force-with-lease", "-u", "origin", branch], cwd=self.tap_root
        )
        self.process.run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                self.tap_repository,
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                (
                    f"Automated Homebrew release for {self.manifest.name} "
                    f"{handoff.version}."
                ),
            ],
            cwd=self.tap_root,
        )
        pull_request = self.github.pull_request(self.tap_repository, branch)
        if pull_request is None:
            raise ReleaseError(f"formula pull request not found for {branch}")
        return pull_request

    def wait_and_publish(self, pull_request: int, head_sha: str) -> None:
        self._wait_for_checks(pull_request)
        self.process.run(
            [
                "gh",
                "pr",
                "checks",
                str(pull_request),
                "--repo",
                self.tap_repository,
                "--watch",
                "--fail-fast",
            ],
            cwd=self.tap_root,
        )
        current = self.process.run(
            [
                "gh",
                "pr",
                "view",
                str(pull_request),
                "--repo",
                self.tap_repository,
                "--json",
                "headRefOid",
                "--jq",
                ".headRefOid",
            ],
            cwd=self.tap_root,
            capture=True,
        )
        if current != head_sha:
            raise ReleaseError(
                f"pull-request head changed: expected {head_sha}, got {current}"
            )
        before = self._latest_publish_run()
        self.process.run(
            [
                "gh",
                "workflow",
                "run",
                "publish.yml",
                "--repo",
                self.tap_repository,
                "-f",
                f"pull_request={pull_request}",
                "-f",
                f"head_sha={head_sha}",
            ],
            cwd=self.tap_root,
        )
        run_id = self._wait_for_new_publish_run(before)
        self.process.run(
            [
                "gh",
                "run",
                "watch",
                run_id,
                "--repo",
                self.tap_repository,
                "--exit-status",
            ],
            cwd=self.tap_root,
        )
        self.git.run(["switch", "main"], cwd=self.tap_root)
        self.git.run(["pull", "--ff-only", "origin", "main"], cwd=self.tap_root)

    def post_verify(self, version: str, project_root: Path) -> None:
        tap_ref = f"peachlifeab/tap/{self.manifest.formula}"
        self.process.run(["brew", "update"], cwd=self.tap_root)
        self.process.run(["brew", "upgrade", self.manifest.formula], cwd=self.tap_root)
        prefix = Path(
            self.process.run(["brew", "--prefix"], cwd=self.tap_root, capture=True)
        )
        executable = prefix / "bin" / self.manifest.executable
        output = self.process.run(
            [str(executable), "--version"], cwd=self.tap_root, capture=True
        )
        expected = f"{self.manifest.name} {version}"
        if output != expected:
            raise ReleaseError(
                f"Homebrew version mismatch: expected {expected!r}, got {output!r}"
            )
        self.process.run(
            [str(executable), *self.manifest.smoke_args], cwd=self.tap_root
        )
        self.process.run(["brew", "test", tap_ref], cwd=self.tap_root)
        self.process.run(
            [str(self.tap_root / "bin" / "preflight"), self.manifest.formula],
            cwd=project_root,
        )

    def _wait_for_checks(self, pull_request: int) -> None:
        """Wait for the check suite to REGISTER; `gh pr checks --watch` then
        waits for it to pass. Only `name` is read, so only `name` is asked for.
        """
        self.process.poll_until(
            [
                "gh",
                "pr",
                "checks",
                str(pull_request),
                "--repo",
                self.tap_repository,
                "--json",
                "name",
            ],
            cwd=self.tap_root,
            ready=lambda code, out: code == 0 and bool(json.loads(out or "[]")),
            attempts=CHECK_DISCOVERY_ATTEMPTS,
        )

    def _publish_run_query(self) -> list[str]:
        return [
            "gh",
            "run",
            "list",
            "--repo",
            self.tap_repository,
            "--workflow",
            "publish.yml",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ]

    @staticmethod
    def _run_id(raw: str) -> str:
        rows = json.loads(raw or "[]")
        return str(rows[0]["databaseId"]) if rows else ""

    def _latest_publish_run(self) -> str:
        return self._run_id(
            self.process.run(self._publish_run_query(), cwd=self.tap_root, capture=True)
        )

    def _wait_for_new_publish_run(self, previous: str) -> str:
        """Wait for the dispatched run to appear so it has an id to watch."""
        self.process.poll_until(
            self._publish_run_query(),
            cwd=self.tap_root,
            ready=lambda code, out: (
                code == 0 and self._run_id(out) not in ("", previous)
            ),
            attempts=PUBLISH_RUN_DISCOVERY_ATTEMPTS,
        )
        return self._latest_publish_run()
