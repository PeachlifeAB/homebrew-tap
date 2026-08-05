# Repository state study.
#
# Sourced by bin/preflight. Prints the current git status, log, and tags for
# the upstream repo and the tap, unconditionally, so the study happens even
# when every gate passes. Reading beats remembering: the tap's release history
# is a list of failures caused by acting on stale assumptions about this state.

# Gates the upstream repo. Sets: declared_version
study_upstream() {
    local repo="$1" slug="$2" tag="$3" expect_version="$4"

    printf '\n=== UPSTREAM %s ===\n' "${slug:-?}"
    if [[ ! -d "$repo/.git" ]]; then
        warn "upstream repo not checked out at $repo; upstream gates skipped"
        return
    fi

    printf -- '--- git status ---\n'
    local status
    status="$(git -C "$repo" status --short)"
    printf '%s\n' "${status:-(clean)}"

    printf -- '--- git log (last 10) ---\n'
    git -C "$repo" log --oneline -10

    printf -- '--- git tags (last 10) ---\n'
    git -C "$repo" tag --sort=-creatordate | head -10

    printf -- '--- branch / HEAD ---\n'
    local branch head
    branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD)"
    head="$(git -C "$repo" rev-parse --short HEAD)"
    printf '%s @ %s\n' "$branch" "$head"

    [[ -z "$status" ]] ||
        fail "upstream worktree is dirty; commit or stash before releasing"

    # Unpushed commits mean the tag you push may not be reachable by others.
    local tracking ahead
    if tracking="$(git -C "$repo" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)"; then
        ahead="$(git -C "$repo" rev-list --count "$tracking..HEAD")"
        printf 'tracking: %s (%s ahead)\n' "$tracking" "$ahead"
        [[ "$ahead" -eq 0 ]] ||
            fail "upstream has $ahead unpushed commit(s); push before releasing"
    else
        warn "upstream branch $branch has no tracking branch"
    fi

    # The tag must exist and point at the commit being released. A tag lagging
    # HEAD is what produces a formula pinning code that was never shipped.
    local tag_commit behind
    if [[ -n "$tag" ]]; then
        if git -C "$repo" rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
            tag_commit="$(git -C "$repo" rev-parse --short "refs/tags/$tag^{commit}")"
            behind="$(git -C "$repo" rev-list --count "refs/tags/$tag..HEAD")"
            printf 'tag %s -> %s (%s commit(s) behind HEAD)\n' "$tag" "$tag_commit" "$behind"
            [[ "$behind" -eq 0 ]] ||
                fail "tag $tag is $behind commit(s) behind HEAD; re-tag or release from the tagged commit"
        else
            fail "tag $tag referenced by the formula does not exist upstream"
        fi
    fi

    # Declared version must agree with the tag, or `brew test` fails after the
    # release is already public.
    declared_version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$repo/pyproject.toml" 2>/dev/null | head -1)"
    if [[ -n "$declared_version" ]]; then
        printf 'pyproject version: %s\n' "$declared_version"
        # Tags may or may not carry a leading "v"; compare on the bare number.
        if [[ -n "$tag" && "${tag#v}" != "$declared_version" ]]; then
            fail "pyproject version $declared_version != tag ${tag#v}"
        fi
    else
        warn "pyproject.toml has no static version (dynamic versioning); verify _version.py is committed"
    fi

    # uv.lock carries its own copy of the version and has been found stale in
    # git while pyproject.toml was correct. Regenerate with `uv lock`.
    local locked
    if [[ -n "$declared_version" && -f "$repo/uv.lock" ]]; then
        locked="$(awk '
            /^name = "'"${slug##*/}"'"$/ { found = 1; next }
            found && /^version = "/ { gsub(/^version = "|"$/, ""); print; exit }
        ' "$repo/uv.lock")"
        if [[ -n "$locked" ]]; then
            printf 'uv.lock version:   %s\n' "$locked"
            [[ "$locked" == "$declared_version" ]] ||
                fail "uv.lock pins $locked but pyproject declares $declared_version; run 'uv lock' and commit"
        fi
    fi

    if [[ -n "$expect_version" ]]; then
        [[ -n "$tag" && "${tag#v}" == "$expect_version" ]] ||
            fail "expected version $expect_version but formula pins tag ${tag:-<none>}"
    fi
}

study_tap() {
    local tap="$1"

    printf '\n=== TAP %s ===\n' "${tap##*/}"
    printf -- '--- git status ---\n'
    local status
    status="$(git -C "$tap" status --short)"
    printf '%s\n' "${status:-(clean)}"

    printf -- '--- git log (last 10) ---\n'
    git -C "$tap" log --oneline -10

    printf -- '--- git tags (last 10) ---\n'
    local tags
    tags="$(git -C "$tap" tag --sort=-creatordate | head -10)"
    printf '%s\n' "${tags:-(none)}"

    printf -- '--- gh releases ---\n'
    if command -v gh >/dev/null 2>&1; then
        gh release list --repo PeachlifeAB/homebrew-tap --limit 10 2>/dev/null ||
            warn "could not list tap releases (gh auth?)"
    else
        warn "gh not installed; tap release list unavailable"
    fi

    local tracking ahead
    if tracking="$(git -C "$tap" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null)"; then
        ahead="$(git -C "$tap" rev-list --count "$tracking..HEAD")"
        printf 'tracking: %s (%s ahead)\n' "$tracking" "$ahead"
        [[ "$ahead" -eq 0 ]] ||
            warn "tap has $ahead unpushed commit(s); push after the formula edit"
    fi
}
