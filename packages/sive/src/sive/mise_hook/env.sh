#!/usr/bin/env bash
# sive mise env hook — sourced via `_.source` in mise.toml.
# mise sources it with bash (crates/mise-util/src/env_diff.rs), and `brew style`
# checks it as bash, so `[[ ]]` is safe here.
# Runs `sive _mise-env`, which reads encrypted per-tag snapshots only
# (no live Bitwarden calls), and exports the result into the shell.
# mise diffs the environment before/after sourcing this script and
# merges any exported vars — see the `_.source` directive in mise docs.
#
# This runs inside `mise hook-env`, where PATH is led by mise's shim
# directory. Any command resolved through PATH can be a shim that re-enters
# mise and re-sources this hook, forking without bound — including `sive`
# itself when mise installed it. SIVE_MISE_HOOK_ACTIVE stops the nested run;
# it is unset before returning so mise never exports it into the shell.

[[ -n "${SIVE_MISE_HOOK_ACTIVE:-}" ]] && return 0
command -v sive >/dev/null 2>&1 || return 0

export SIVE_MISE_HOOK_ACTIVE=1
mise_env="$(sive _mise-env --format=sh 2>/dev/null)"
mise_env_status=$?
unset SIVE_MISE_HOOK_ACTIVE
[[ "${mise_env_status}" -eq 0 ]] && eval "${mise_env}"
unset mise_env mise_env_status
