#!/bin/sh
# sive mise env hook — sourced via `_.source` in mise.toml.
# Runs `sive _mise-env`, which reads encrypted per-tag snapshots only
# (no live Bitwarden calls), and exports the result into the shell.
# mise diffs the environment before/after sourcing this script and
# merges any exported vars — see the `_.source` directive in mise docs.
#
# This runs inside `mise hook-env`, where PATH is led by mise's shim
# directory. Any interpreter resolved through PATH is a shim that re-enters
# mise and re-sources this hook, forking without bound. sive is already a
# Python process, so it emits shell-quoted exports itself and nothing else
# here needs looking up.

command -v sive >/dev/null 2>&1 || return 0

eval "$(sive _mise-env --format=sh 2>/dev/null)"
