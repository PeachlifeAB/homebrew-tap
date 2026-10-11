# Releasing sive

sive is released from this repository by the tap's release engine, the same way
as every formula in `PeachlifeAB/tap`. Run everything from the repository root.

## 1. Write the release notes

```bash
bin/release --product sive --project-root packages/sive notes X.Y.Z
```

This renders `packages/sive/CHANGELOG.md` from the commits since the last
release. Read it, correct it, and keep only what a user would notice. The
reviewed section becomes the GitHub release body.

## 2. Check, then release

```bash
bin/release --product sive --project-root packages/sive release X.Y.Z --check
bin/release --product sive --project-root packages/sive release X.Y.Z
```

`--check` runs every gate, cheapest first, and changes nothing. It stops on an
open Dependabot branch in any repository behind any product, an unsynced or
dirty checkout, a version that does not increase, a stale `uv.lock`, missing
reviewed notes, an sdist that does not verify, `brew style` or
`brew audit --strict` problems, or a published release that no longer matches
its formula.

The release then commits the version and notes, waits for CI, tags, publishes
the sdist, opens the formula pull request (moving the formula to the tap's
Python), refuses to publish unless test-bot built a bottle, publishes it, and
verifies the installed formula as a user gets it.

## Recovery

```bash
bin/release --product sive --project-root packages/sive resume X.Y.Z
```

Resume continues an interrupted release from the tag, release, pull request and
bottle state it finds. Never move a published tag or replace a published asset;
publish a new patch version instead.
