"""Composition root: wires infrastructure adapters into application use cases.

The only place that constructs concrete adapters. Inbound adapters (api/)
request wired components here rather than building their own dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from modules.engine.application.ports import ReleasePorts
from modules.engine.application.producer import ProducerRelease
from modules.engine.application.tap import TapRelease
from modules.engine.domain.models import ProductManifest
from modules.engine.infrastructure.adapters import (
    GitAdapter,
    GitHubAdapter,
    Sha256Hasher,
    SubprocessAdapter,
)
from modules.engine.infrastructure.manifest import load_manifest

# app/ -> src/ -> repository root
TAP_ROOT = Path(__file__).resolve().parents[2]


class Components(NamedTuple):
    tap_root: Path
    project_root: Path
    manifest: ProductManifest
    process: SubprocessAdapter
    github: GitHubAdapter
    producer: ProducerRelease
    tap: TapRelease


def build(product: str, project_root: Path) -> Components:
    """Construct every adapter and inject it into the use cases."""
    manifest = load_manifest(TAP_ROOT, product)
    process = SubprocessAdapter()
    git = GitAdapter(process)
    github = GitHubAdapter(process)
    hasher = Sha256Hasher()
    return Components(
        tap_root=TAP_ROOT,
        project_root=project_root.resolve(),
        manifest=manifest,
        process=process,
        github=github,
        producer=ProducerRelease(
            manifest,
            project_root.resolve(),
            ReleasePorts(process=process, git=git, github=github, hasher=hasher),
        ),
        tap=TapRelease(TAP_ROOT, manifest, process, git, github),
    )
