# Repository state study.
#
# Sourced by bin/preflight. Prints the current git status, log, and tags for
# the upstream repo and the tap, unconditionally, so the study happens even
# when every gate passes. Reading beats remembering: the tap's release history
# is a list of failures caused by acting on stale assumptions about this state.

# Gates the upstream repo. Sets: declared_version
study_upstream() {
  local repo="$1" slug="$2" tag="$3" expect_version="$4" formula_name="$5"

  local package_root="${repo}/packages/${formula_name}"
  local package_name="${formula_name}"
  local monorepo_package=false
  if [[ ! -f "${package_root}/pyproject.toml" ]]
  then
    package_root="${repo}"
    package_name="${slug##*/}"
  else
    monorepo_package=true
  fi
  local tag_version="${tag#v}"
  if [[ "${tag}" == "${formula_name}-"* ]]
  then
    tag_version="${tag#"${formula_name}"-}"
  fi
  printf '\n=== UPSTREAM %s ===\n' "${slug:-?}"
  if [[ ! -d "${repo}/.git" ]]
  then
    warn "upstream repo not checked out at ${repo}; upstream gates skipped"
    return
  fi

  printf -- '--- git status ---\n'
  local status
  status="$(git -C "${repo}" status --short)"
  printf '%s\n' "${status:-(clean)}"

  printf -- '--- git log (last 10) ---\n'
  git -C "${repo}" log --oneline -10

  printf -- '--- git tags ---\n'
  git -C "${repo}" tag --sort=-creatordate

  printf -- '--- branch / HEAD ---\n'
  local branch head
  branch="$(git -C "${repo}" rev-parse --abbrev-ref HEAD)"
  head="$(git -C "${repo}" rev-parse --short HEAD)"
  printf '%s @ %s\n' "${branch}" "${head}"

  [[ -z "${status}" ]] ||
    fail "upstream worktree is dirty; commit or stash before releasing"

  # Unpushed commits mean the tag you push may not be reachable by others.
  local tracking ahead
  if tracking="$(git -C "${repo}" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)"
  then
    ahead="$(git -C "${repo}" rev-list --count "${tracking}..HEAD")"
    printf 'tracking: %s (%s ahead)\n' "${tracking}" "${ahead}"
    [[ "${ahead}" -eq 0 ]] ||
      fail "upstream has ${ahead} unpushed commit(s); push before releasing"
  else
    warn "upstream branch ${branch} has no tracking branch"
  fi

  # The tag must exist. Single-product repositories must still point at HEAD;
  # monorepo products may have later sibling or tap commits, so package state
  # is checked against the tag's version below.
  local tag_commit behind
  if [[ -n "${tag}" ]]
  then
    if git -C "${repo}" rev-parse -q --verify "refs/tags/${tag}" >/dev/null
    then
      tag_commit="$(git -C "${repo}" rev-parse --short "refs/tags/${tag}^{commit}")"
      behind="$(git -C "${repo}" rev-list --count "refs/tags/${tag}..HEAD")"
      printf 'tag %s -> %s (%s commit(s) behind HEAD)\n' "${tag}" "${tag_commit}" "${behind}"
      if [[ "${behind}" -ne 0 ]]
      then
        if [[ "${monorepo_package}" == true ]]
        then
          warn "tag ${tag} is ${behind} commit(s) behind monorepo HEAD; package state is checked below"
        else
          fail "tag ${tag} is ${behind} commit(s) behind HEAD; re-tag or release from the tagged commit"
        fi
      fi
    else
      fail "tag ${tag} referenced by the formula does not exist upstream"
    fi
  fi

  # Declared version must agree with the tag, or `brew test` fails after the
  # release is already public.
  declared_version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "${package_root}/pyproject.toml" 2>/dev/null)"
  declared_version="${declared_version%%$'\n'*}"
  if [[ -n "${declared_version}" ]]
  then
    printf 'pyproject version: %s\n' "${declared_version}"
    if [[ -n "${tag}" && "${tag_version}" != "${declared_version}" ]]
    then
      fail "pyproject version ${declared_version} != tag ${tag_version}"
    fi
  else
    warn "pyproject.toml has no static version (dynamic versioning); verify _version.py is committed"
  fi

  # uv.lock carries its own copy of the version and has been found stale in
  # git while pyproject.toml was correct. Regenerate with `uv lock`.
  local locked
  if [[ -n "${declared_version}" && -f "${repo}/uv.lock" ]]
  then
    locked="$(awk '
            /^name = "'"${package_name}"'"$/ { found = 1; next }
            found && /^version = "/ { gsub(/^version = "|"$/, ""); print; exit }
        ' "${repo}/uv.lock")"
    if [[ -n "${locked}" ]]
    then
      printf 'uv.lock version:   %s\n' "${locked}"
      [[ "${locked}" == "${declared_version}" ]] ||
        fail "uv.lock pins ${locked} but pyproject declares ${declared_version}; run 'uv lock' and commit"
    fi
  fi

  if [[ -n "${expect_version}" ]]
  then
    [[ -n "${tag}" && "${tag_version}" == "${expect_version}" ]] ||
      fail "expected version ${expect_version} but formula pins tag ${tag:-<none>}"
  fi
}

study_tap() {
  local tap="$1"

  printf '\n=== TAP %s ===\n' "${tap##*/}"
  printf -- '--- git status ---\n'
  local status
  status="$(git -C "${tap}" status --short)"
  printf '%s\n' "${status:-(clean)}"

  printf -- '--- git log (last 10) ---\n'
  git -C "${tap}" log --oneline -10

  printf -- '--- git tags ---\n'
  local tags
  tags="$(git -C "${tap}" tag --sort=-creatordate)"
  printf '%s\n' "${tags:-(none)}"

  printf -- '--- gh releases ---\n'
  if command -v gh >/dev/null 2>&1
  then
    gh release list --repo PeachlifeAB/homebrew-tap --limit 10 2>/dev/null ||
      warn "could not list tap releases (gh auth?)"
  else
    warn "gh not installed; tap release list unavailable"
  fi

  local tracking ahead
  if tracking="$(git -C "${tap}" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)"
  then
    ahead="$(git -C "${tap}" rev-list --count "${tracking}..HEAD")"
    printf 'tracking: %s (%s ahead)\n' "${tracking}" "${ahead}"
    [[ "${ahead}" -eq 0 ]] ||
      warn "tap has ${ahead} unpushed commit(s); push after the formula edit"
  fi
}
