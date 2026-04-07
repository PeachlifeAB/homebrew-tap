# Debug Journal: 404 errors downloading GitHub release tarballs

**Reported**: 2026-04-07
**Symptom**: `brew install sive lgtvctrl` fails with 404 on source tarball downloads.
**Real-path reproduction**: `brew fetch sive lgtvctrl`
**Failing seam**: Formula source URLs pointed at nonexistent GitHub tag archives.
**Primary evidence**: curl 404 on `v0.1.0` and `v0.6.4` tag URLs; 200 on corrected URLs.
**Last failed assumption**: Remote tags existed with `v` prefix.
**Code red**: Off
**Current owner path**: `bin/repo-state`, `brew fetch`, `brew install --build-from-source`, `brew test`, `brew audit`
**Current verification target**: `brew update && brew upgrade sive lgtvctrl` exits 0.
**Open issue**: `lgtvctrl` `tv --version` reports `0.6.5.dev18+...` instead of `0.1.0` — stale `_version.py` in the commit tarball (setuptools_scm cannot regenerate without git metadata). Fix requires committing a correct `_version.py` to `lgtvctrl` before tagging, or pushing the `0.1.0` tag to remote so `sive` can also use a proper tag URL.

---

## Entry 1

**Timestamp**: 2026-04-07 08:09
**Phase**: Patch

### Hypothesis

Both formula failures caused by wrong/nonexistent source URLs: `sive` used `v0.1.0` tag (not pushed to remote), `lgtvctrl` pointed at old `v0.6.4` URL which never existed on the 0.1.0-era project.

### Experiment or reconnaissance

- curl'd all candidate URLs; checked GitHub tags API for both repos.
- Ran `git ls-remote --tags origin` and `git tag --points-at HEAD` in both local repos.

### Observation

- `sive`: remote tags API returns `[]`; only commit archive resolves (200). SHA256: `55a15976cfeb2f47b592af3c3a79d69611a5a3db0b6bff3e2470a0e6039d1b3b`.
- `lgtvctrl`: remote tag `0.1.0` exists and resolves (200). SHA256: `748fc418e617ecfc1c32ceac6ff15affeae88128c5b64365575b3de5c27408f0`.

### Conclusion

Confirmed. Patched `sive.rb` to commit archive + explicit `version "0.1.0"`. Patched `lgtvctrl.rb` to `0.1.0` tag URL with correct SHA256.

### Next action

Commit, push, run `brew update && brew upgrade sive lgtvctrl`.

---

## Entry 2

**Timestamp**: 2026-04-07 10:35
**Phase**: Verify

### Hypothesis

After pushing corrected formula URLs to GitHub, `brew update && brew upgrade` would download and install both packages without 404 errors.

### Experiment or reconnaissance

Committed and pushed formula fixes + bootstrap files. Ran `brew update && brew upgrade sive lgtvctrl`. Then ran `sive --version` and `tv --version`.

### Observation

- `sive --version` → `sive 0.1.0 (36205c4)` ✓
- `tv --version` → `tv 0.6.5.dev18+g7157926f5.d20260330` ⚠️
- `lgtvctrl 0.1.0` was already installed; `brew upgrade` did not reinstall it.
- `brew upgrade` exit 0.

### Conclusion

Download 404s are resolved. `sive` is correct. `lgtvctrl` installs without error but `tv --version` reports the wrong version string because `src/lgtvctrl/_version.py` in the tarball contains a stale dev version — setuptools_scm cannot regenerate it from a tarball with no git metadata. Formula test `assert_match version.to_s` would fail.

### Next action

Fix `lgtvctrl` upstream: commit `__version__ = "0.1.0"` to `_version.py` before tagging, then re-tag and push `0.1.0`. Also push the `sive` `0.1.0` tag to remote so the formula can use a clean tag URL instead of a commit archive.
