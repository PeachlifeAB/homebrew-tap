# Published-artifact and formula-correctness gates.
#
# Sourced by bin/preflight.

# The pinned sha256 must match what users will actually download.
check_integrity() {
  local url="$1" sha_pinned="$2"

  printf '\n=== FORMULA INTEGRITY ===\n'
  printf 'url:    %s\n' "${url}"
  printf 'pinned: %s\n' "${sha_pinned}"

  local sha_live
  sha_live="$(curl -fsSL "${url}" 2>/dev/null | shasum -a 256 | cut -d' ' -f1 || true)"
  if [[ -z "${sha_live}" ]]
  then
    fail "could not fetch ${url}; the release asset or tag may not be published yet"
    return
  fi

  printf 'live:   %s\n' "${sha_live}"
  if [[ "${sha_live}" == "${sha_pinned}" ]]
  then
    printf 'sha256: OK\n'
  else
    fail "sha256 mismatch: formula pins ${sha_pinned} but the published artifact is ${sha_live}"
  fi
}

# Ruby syntax and Homebrew conventions. Commit a8f85d1 ("use bare symbol syntax
# for depends_on macos:") shipped a formula that `brew style` would have caught.
check_style_audit() {
  local formula="$1" formula_name="$2"

  printf '\n=== STYLE / AUDIT ===\n'
  if ! command -v brew >/dev/null 2>&1
  then
    warn "brew not installed; style and audit skipped"
    return
  fi

  local out
  out="$(mktemp)"

  if brew style "${formula}" >"${out}" 2>&1
  then
    printf 'brew style: OK\n'
  else
    sed -n '1,20p' "${out}"
    fail "brew style reported offenses in ${formula_name}.rb"
  fi

  # `brew audit` takes a formula NAME, not a path, and resolves it through the
  # installed tap -- which may lag this working copy. Audit therefore checks
  # what is published, while `brew style` above checks what is on disk here.
  local tap_ref="peachlifeab/tap/${formula_name}"
  if brew audit --strict "${tap_ref}" >"${out}" 2>&1
  then
    printf 'brew audit --strict: OK\n'
  else
    sed -n '1,20p' "${out}"
    fail "brew audit --strict reported problems in ${tap_ref}"
  fi

  mv -f "${out}" "${TMPDIR:-/tmp}/preflight-audit.last" 2>/dev/null || true
}

# DEVELOPMENT.md: "Always build and upload a bottle for every formula release."
check_bottle() {
  local formula="$1" formula_name="$2" tag="$3"

  if ! grep -q '^[[:space:]]*bottle do' "${formula}"
  then
    fail "no bottle block in ${formula_name}.rb; build and upload a bottle (docs/DEVELOPMENT.md 'Building and Releasing a Bottle')"
    return
  fi

  local bottle_root
  bottle_root="$(sed -n 's/^[[:space:]]*root_url "\(.*\)"[[:space:]]*$/\1/p' "${formula}")"
  bottle_root="${bottle_root%%$'\n'*}"
  printf 'bottle: present (%s)\n' "${bottle_root##*/}"
  [[ -z "${tag}" || "${bottle_root##*/}" == "${formula_name}-${tag#v}" ]] ||
    fail "bottle root_url points at ${bottle_root##*/}, expected ${formula_name}-${tag#v}"
}
