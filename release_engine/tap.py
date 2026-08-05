from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from .adapters import GitAdapter, GitHubAdapter, SubprocessAdapter
from .models import Handoff, ProductManifest, ReleaseError

_TOP_LEVEL_SHA = re.compile(r'^  sha256 "[0-9a-f]{64}"$', re.MULTILINE)
_BOTTLE_BLOCK = re.compile(r"\n  bottle do\n.*?\n  end\n", re.DOTALL)


class TapRelease:
    def __init__(
        self,
        tap_root: Path,
        manifest: ProductManifest,
        process: SubprocessAdapter,
        git: GitAdapter,
        github: GitHubAdapter,
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
                f"live tag commit {live_commit or '<missing>'} != handoff {handoff.commit}"
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
        url_pattern = re.compile(
            rf'^  url "https://github\.com/{re.escape(self.manifest.repository)}/[^\"]+"$',
            re.MULTILINE,
        )
        content, url_count = url_pattern.subn(
            f'  url "{handoff.source_url}"', content, count=1
        )
        content, sha_count = _TOP_LEVEL_SHA.subn(
            f'  sha256 "{handoff.source_sha256}"', content, count=1
        )
        content = _BOTTLE_BLOCK.sub("\n", content, count=1)
        if url_count != 1 or sha_count != 1:
            raise ReleaseError(
                f"formula update expected one URL/SHA, got url={url_count}, sha={sha_count}"
            )
        expected_test = f'assert_match version.to_s, shell_output("#{{bin}}/{self.manifest.executable} --version")'
        if expected_test not in content:
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
                f"Automated Homebrew release for {self.manifest.name} {handoff.version}.",
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
        command = [
            "gh",
            "pr",
            "checks",
            str(pull_request),
            "--repo",
            self.tap_repository,
            "--json",
            "name,state",
        ]
        for _ in range(60):
            result = subprocess.run(
                command,
                cwd=self.tap_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and json.loads(result.stdout):
                return
            time.sleep(2)
        raise ReleaseError("pull-request checks did not appear")

    def _latest_publish_run(self) -> str:
        raw = self.process.run(
            [
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
            ],
            cwd=self.tap_root,
            capture=True,
        )
        rows = json.loads(raw)
        return str(rows[0]["databaseId"]) if rows else ""

    def _wait_for_new_publish_run(self, previous: str) -> str:
        for _ in range(30):
            current = self._latest_publish_run()
            if current and current != previous:
                return current
            time.sleep(2)
        raise ReleaseError("publish workflow run did not appear")
