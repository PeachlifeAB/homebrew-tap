# homebrew-tap

Homebrew formulae and casks for Peachlife software, installable through the
[Homebrew](https://brew.sh/) package manager.

## Installation

Since [Homebrew 6.0.0](https://brew.sh/2026/06/11/homebrew-6.0.0/) a
non-official tap must be trusted before Homebrew will load it. Installing by
fully qualified name trusts only that item, so no separate tap or trust step is
needed:

```
brew install PeachlifeAB/tap/<FORMULA>
brew install --cask PeachlifeAB/tap/<CASK>
```

To install by short name instead, trust the item first — or the whole tap,
which accepts every current and future item from it:

```
brew tap PeachlifeAB/tap
brew trust --formula PeachlifeAB/tap/<FORMULA>
brew install <FORMULA>
```

## Formulae

| Repository | Formula | Description |
| ---------- | ------- | ----------- |
| [bgtail](https://github.com/PeachlifeAB/bgtail) | [formula](Formula/bgtail.rb) | Run long-running commands detached with minimal heartbeat |
| [lgtvctrl](https://github.com/PeachlifeAB/lgtvctrl) | [formula](Formula/lgtvctrl.rb) | Command-line control for LG WebOS TVs |
| [sive](https://github.com/PeachlifeAB/sive) | [formula](Formula/sive.rb) | Sync secrets from your vault into your shell |

## Casks

| Repository | Cask | Description |
| ---------- | ---- | ----------- |
| [hyprspace](https://hyprspace.net/) | [cask](Casks/hyprspace.rb) | Tiling window manager based on AeroSpace |

All formulae currently require macOS.

## Updating and uninstalling

```
brew upgrade <FORMULA>
brew uninstall <FORMULA>
brew untap PeachlifeAB/tap
```

## Hyprspace release artifacts

Source is open at
[hyprspace-core](https://github.com/PeachlifeAB/hyprspace-core). Releases,
[legal disclosure](https://github.com/PeachlifeAB/hyprspace-releases/blob/main/LEGAL.md)
and [licence](https://github.com/PeachlifeAB/hyprspace-releases/blob/main/LICENSE)
are published in
[hyprspace-releases](https://github.com/PeachlifeAB/hyprspace-releases).

## Documentation

`brew help`, `man brew`, or [Homebrew's documentation](https://docs.brew.sh/).
