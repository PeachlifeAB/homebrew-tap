#!/usr/bin/env bash
# ETA: ~2s observed 2026-03-30
set -euo pipefail

echo "== repo =="
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short

echo
echo "== python/runtime =="
command -v python3 || true
python3 --version 2>/dev/null || true
command -v uv || true
uv --version 2>/dev/null || true

echo
echo "== package entrypoints =="
python3 - <<'PY'
from pathlib import Path
for p in [Path('pyproject.toml'), Path('setup.py'), Path('src/lgtvctrl/main.py'), Path('src/lgtvctrl/auth.py')]:
    print(f"{p}: {'present' if p.exists() else 'missing'}")
PY

echo
echo "== local network facts =="
(ifconfig 2>/dev/null | rg "inet " || true)
(route -n get default 2>/dev/null | rg "gateway|interface" || true)

echo
echo "== process =="
(ps aux | rg "tv auth|lgtvctrl|python3" || true)
