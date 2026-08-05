# Formula parsing and failure accumulation.
#
# Sourced by bin/preflight. Each tap target has a different release shape
# (archive tarball vs published release asset, tag prefixed or not), so every
# fact is derived from the formula rather than assumed.

# These globals are outputs consumed by the sourcing preflight script.
# shellcheck disable=SC2034
FAILURES=()
WARNINGS=()

fail() { FAILURES+=("$1"); }
warn() { WARNINGS+=("$1"); }

die() {
  printf 'preflight: %s\n' "$1" >&2
  exit 2
}

# Populates globals consumed by the sourcing preflight script.
# shellcheck disable=SC2034
parse_formula() {
  local formula="$1"

  url="$(sed -n 's/^[[:space:]]*url "\(.*\)"[[:space:]]*$/\1/p' "${formula}")"
  url="${url%%$'\n'*}"
  sha_pinned="$(sed -n 's/^[[:space:]]*sha256 "\([0-9a-f]\{64\}\)"[[:space:]]*$/\1/p' "${formula}")"
  sha_pinned="${sha_pinned%%$'\n'*}"
  [[ -n "${url}" ]] || die "could not parse url from ${formula}"
  [[ -n "${sha_pinned}" ]] || die "could not parse top-level sha256 from ${formula}"

  # The tag is the parent path segment for release assets, or the basename
  # minus .tar.gz for archive tarballs.
  case "${url}" in
    */archive/refs/tags/*)
      url_kind="archive tarball"
      tag="$(basename "${url}" .tar.gz)"
      ;;
    */releases/download/*)
      url_kind="release asset"
      tag="$(basename "$(dirname "${url}")")"
      ;;
    *)
      url_kind="unrecognized"
      tag=""
      ;;
  esac

  local upstream_path upstream_owner upstream_repo
  upstream_path="${url#https://github.com/}"
  upstream_owner="${upstream_path%%/*}"
  upstream_path="${upstream_path#*/}"
  upstream_repo="${upstream_path%%/*}"
  upstream_slug="${upstream_owner}/${upstream_repo}"
}

# Prints accumulated warnings and failures; exits non-zero when any failure was
# recorded.
report_verdict() {
  local formula_name="$1"

  printf '\n=== VERDICT ===\n'
  for w in "${WARNINGS[@]+"${WARNINGS[@]}"}"
  do
    printf 'WARN: %s\n' "${w}"
  done
  for f in "${FAILURES[@]+"${FAILURES[@]}"}"
  do
    printf 'FAIL: %s\n' "${f}"
  done

  if [[ ${#FAILURES[@]} -gt 0 ]]
  then
    printf '\n%s release BLOCKED (%d failure(s)). Fix the above, then re-run.\n' \
      "${formula_name}" "${#FAILURES[@]}"
    return 1
  fi

  printf '\n%s preflight PASSED. State above was read just now — release from it.\n' \
    "${formula_name}"
}
