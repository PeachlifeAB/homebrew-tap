# Contributing

One owner per path. Change a path only through the way its row names.

| Path | Owner | Changed by |
| --- | --- | --- |
| `Formula/*.rb` | the release engine | `bin/release`, which rewrites the version, checksum and Python; Homebrew's `brew pr-pull` adds the bottle block |
| `Casks/hyprspace.rb` | the hyprspace-core repository | its generated bump, checked here with `bin/release --product hyprspace ... release X.Y.Z --check`; never hand-edited |
| `packages/<name>/` | that product | a pull request to this repository; each package has its own version and changelog |
| `release-products/*.toml` | the release engine | a pull request, one manifest per product |
| `src/`, `bin/release` | the release engine | a pull request; `uv run poe validate` must pass |
| `.github/workflows/` | the tap | a pull request; prove it with `act` where Linux can run it |
| `README.md` | the tap | a pull request; it lists every formula, the cask and the supported platforms |
| `CHANGELOG.md` | the release engine | `bin/release ... notes X.Y.Z`; the cask section holds one line per bump |

Before a release, run `bin/release ... release X.Y.Z --check`.
