# homebrew-tap

Homebrew tap + monorepo for the products it ships.

## Layout

```
Formula/*.rb             sive, bgtail, lgtvctrl
Casks/hyprspace.rb       generated in the hyprspace repo; never hand-edit
packages/<name>/         products - one deployment unit each
src/                     release engine - one deployment unit
release-products/*.toml  one manifest per product
bin/{release,repo-state,preflight}
```

- `Formula/` and `Casks/` cannot move. Homebrew scans `Formula/`,
  `HomebrewFormula/` or the repo root, takes the first that exists, ignores the
  rest. A nested formula makes the tap resolve nothing, silently.
- `packages/<name>/` = deployment unit (own `pyproject.toml`, version,
  `brew install`). `modules/<id>/` = bounded context inside one deployment unit
  (`domain/`, `application/`, `api/`, `infrastructure/`). Installable
  separately → packages, not modules.
- `src/modules/engine/`: dependencies inward only, `api`/`infrastructure` →
  `application` → `domain`. `src/app/composition.py` is the only place
  constructing adapters. Enforced by ruff `TID251`.

## Quality gates

`uv run poe validate` — must fail when any package fails.

Planned work lives in OpenSpec, and nowhere else. Do not record open work in
README.md, AGENTS.md, a backlog file, or any loose document: a note no gate
reads is a note that goes stale. Run `openspec list` to see what is open, and
add a change rather than a TODO and check <proj>/openspec/config.yaml for store.

Planning lives in a private store, so this public repository carries none of
it in its history — only the two-line pointer `openspec/config.yaml` naming
the store. Register it once per machine:

```bash
git clone git@github.com:PeachlifeAB/openspec ~/openspec
openspec store register ~/openspec/homebrew-tap
```

That clone holds one store per repository. It is a single git repository, so
scope every commit to this project's subtree; a bare `git add` there sweeps
sibling projects into one commit.

The pointer is what makes commands resolve with no `--store` flag. A
contributor without the store gets an error from `openspec` alone; nothing
else in the repository depends on it, so keep `openspec` out of CI.

This file describes how the repository is arranged and what its gates enforce.
Keep dated observations, measurements and line numbers out of it — put those in
the OpenSpec change that acts on them, where they are read while they are still
true.

| Check                      | Owner                           | Platform | When         |
| -------------------------- | ------------------------------- | -------- | ------------ |
| formula style / tap syntax | `tests.yml` `--only-tap-syntax` | macOS    | push + PR    |
| formula install + test     | `tests.yml` `--only-formulae`   | macOS    | PR only      |
| `qlty check`               | `quality.yml`                   | Linux    | push + PR    |
| ruff, mypy, pytest         | `poe validate`, pre-commit      | local    | every commit |

- Shared tool config lives in the **root** `pyproject.toml` only. A package
  declares its runtime deps, build backend, version, own `poe test` — nothing
  else.
- Do not add `brew style` to `quality.yml`. `tests.yml` owns it.
- Suppressions name the surface that earns them: fix, or scope to the exact
  rule + paths, with the reason recorded. Never repo-wide. Verify a claimed
  false positive by reading the code it names.
- mypy checks `src tests` only. `mypy_path` also names each package's `src/`,
  which governs import resolution, never the checked set; widening the checked
  paths to `packages/` waits on a triage of what that reports.

### Gotchas

- A package with its own `[tool.pytest.ini_options]` becomes pytest's
  configfile and silently discards the root `pythonpath`.
- Two `tests/__init__.py` make both claim module name `tests`. There are none.
- `setup-homebrew` fetches the tap by `GITHUB_SHA` from the remote → fails
  `upload-pack: not our ref` on unpushed commits. Keep it out of workflows
  meant to run under `act`.
- `act` is Linux containers only; the macOS matrix is not reproducible locally.
- `brew style` on a loose file outside a tap reports spurious offences.
- `brew` reads the installed tap, not your working tree.
- Generic rubocop reports 108 findings on `Formula/`+`Casks/`; its autofixes
  break `brew style`. `brew style` owns that surface.

## Local install

`sive` declares `depends_on :macos`: it still reaches a macOS-only facility
directly. The constraint drops per formula as that surface moves behind a port,
as it has for `bgtail` and `lgtvctrl`. A formula's `depends_on :macos`
and its manifest's `macos_only` must agree — `test_macos_only_matches_the_formula`
enforces it, and `quality.yml`'s `linux-packages` job runs every package whose
manifest claims `macos_only = false`.

```bash
brew install PeachlifeAB/tap/sive          # qualified name trusts just that item
cp Formula/sive.rb "$(brew --repository peachlifeab/tap)/Formula/" && brew reinstall sive
```

Homebrew 6.0.0+ requires a non-official tap be trusted before it loads.

## Release

**A release is not complete until the published artifact is installed from the
tap and exercised as a user gets it.** Clean diff + green CI ≠ working install.

Stages: `observe`, `verify`, `prepare`, `publish`, `post-verify`, `release`,
`resume`. `post_verify` in `src/modules/engine/application/tap.py` is the gate:

1. `brew update && brew upgrade <formula>`
2. resolve the real executable under `brew --prefix`
3. assert `<name> <version>` **exactly** — a substring match passes against a
   dev-suffixed build such as `0.1.1.dev+d20260805`
4. run the formula's smoke args against that binary
5. `brew test peachlifeab/tap/<formula>`
6. `bin/preflight <formula>` — fresh upstream + tap state, fails on drift

Run `bin/preflight <formula>` immediately before every release. A formula's
`test do` asserts the complete version string, never a substring.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
