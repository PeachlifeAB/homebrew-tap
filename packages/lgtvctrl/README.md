# lgtvctrl

> Command-line control for LG WebOS TVs — brightness, volume, input, power, and more.

`lgtvctrl` exposes a single `tv` command that talks directly to your LG TV over the local network via the WebOS API. It is designed to be scripted: clean output, proper exit codes, and a file lock that prevents concurrent commands from interfering.

On macOS it also integrates with [BetterDisplay](https://github.com/waydabber/BetterDisplay) for display reinitialization after wake.

## Why this instead of other tools?

Most LG control tools expose only panel backlight. `lgtvctrl` implements a **three-tier brightness cascade** that gives you a single, consistent 1–100 scale across the TV's full perceived brightness range — spanning the `brightness`, `contrast`, and `backlight`/`oledLight` hardware parameters in sequence. It also adjusts `darkMode` in sync for maximum range at the low end.

The tool auto-detects OLED vs LCD panel keys at runtime and verifies that each brightness change was actually applied before returning.

## Requirements

- Python 3.10+
- An LG WebOS TV on the same local network
- macOS or Linux
- Homebrew (macOS only, for BetterDisplay installation)

> [!NOTE]
> The `power on` command (Wake-on-LAN) requires the TV's MAC address, which is auto-detected during `tv auth`.

## Installation

```bash
brew tap PeachlifeAB/tap
brew install lgtvctrl
```

Or via pip:

```bash
pip install git+https://github.com/PeachlifeAB/lgtvctrl.git
```

Or clone and install in editable mode for development:

```bash
git clone https://github.com/PeachlifeAB/lgtvctrl.git
cd lgtvctrl
pip install -e ".[dev]"
```

### First-time setup

Run the auth wizard once to pair with your TV and write the config:

```bash
tv auth
```

This will:
1. Install [BetterDisplay](https://betterdisplay.pro) via Homebrew if not already installed (macOS only)
2. Discover LG TVs on your network via SSDP
3. Prompt you to accept the pairing dialog on the TV
4. Auto-detect the MAC address (for Wake-on-LAN) and default PC input
5. Write config to `~/.config/lgtvctrl/config.json`

> [!IMPORTANT]
> After `tv auth` completes, open BetterDisplay and enable its HTTP API:
> **BetterDisplay → Settings → Advanced → Enable HTTP API (port 55777)**
>
> This is required for `tv power on` to recover the HDMI signal after wake.

## Usage

```
tv COMMAND [OPTIONS]
```

### Brightness

```bash
tv dim up [amount]        # Increase brightness (default: 5 steps)
tv dim down [amount]      # Decrease brightness (default: 5 steps)
tv dim set <level>        # Set brightness to 1–100
tv dim get                # Print current brightness level

tv dim up --dynamic       # Use 3-tier cascade mode
tv dim set 40 --dynamic
```

The default (simple) mode adjusts only the panel backlight. `--dynamic` mode cascades across all three picture parameters for finer control at extremes.

### Volume

```bash
tv volume up [amount]     # Increase volume (default: 1 step)
tv volume down [amount]   # Decrease volume (default: 1 step)
tv volume set <level>     # Set volume to an absolute level
tv volume get             # Print current volume
```

### Input

```bash
tv input list             # List all available inputs
tv input list --json      # Same, as JSON
tv input set <input_id>   # Switch to a specific input
tv input favorite         # Switch to the configured PC input
```

The `favorite` input is auto-detected during `tv auth` and stored in config as `pc_input`.

### Screen

```bash
tv screen on              # Turn screen on (while TV stays on)
tv screen off             # Turn screen off
tv screen status          # Print current screen state
```

### Power

```bash
tv power on               # Wake TV and recover display signal
tv power off              # Put TV in standby
```

`tv power on` runs a multi-step wake sequence:

1. Sends a Wake-on-LAN magic packet to the TV's MAC address
2. Asks BetterDisplay to reconnect all displays (macOS)
3. Checks for an HDMI signal on the configured `pc_input`
4. If no signal, cycles the Mac's display sleep and retries
5. As a last resort, reinitializes the display through BetterDisplay's API using the TV's UUID

The full sequence retries up to 3 times. On Linux (or without BetterDisplay), it sends the WOL packet only.

### Status and diagnostics

```bash
tv status                 # Print JSON status snapshot (power, signal, app, etc.)
tv query [setting]        # Query picture settings (default), inputs, apps, system, update-status
tv picture-all            # Dump all picture settings
tv raw <command> [args]   # Send a raw WebOS SSAP command
```

## Configuration

Config is stored at `~/.config/lgtvctrl/config.json`:

```json
{
  "ip": "192.168.1.42",
  "mac": "a1:b2:c3:d4:e5:f6",
  "pc_input": "HDMI_3"
}
```

| Key | Description |
|---|---|
| `ip` | TV IP address (required) |
| `mac` | TV MAC address, used for Wake-on-LAN |
| `pc_input` | Default input label for `tv input favorite` |
| `uuid` | BetterDisplay display UUID (auto-managed) |

State files (client key, display identifier cache, lock file) are kept in `~/.local/state/lgtvctrl/`.

## BetterDisplay integration (macOS)

`tv power on` uses BetterDisplay's HTTP API (port 55777) to recover the HDMI signal after wake — macOS often fails to re-detect the display on its own. If BetterDisplay is not running or the HTTP API is disabled, the command falls back to WOL only (steps 2–5 of the wake sequence are skipped).

## Scripting

All commands exit with `0` on success and `1` on error. Output is plain text or JSON, suitable for piping. A file lock at `~/.local/state/lgtvctrl/lgtvctrl.lock` prevents concurrent invocations from racing.

Example — bind brightness to a hotkey with [skhd](https://github.com/koekeishiya/skhd):

```
ctrl + alt - up   : tv dim up 5
ctrl + alt - down : tv dim down 5
```
