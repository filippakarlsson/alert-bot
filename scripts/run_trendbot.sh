#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/filippakarlsson/Documents/Codex/2026-04-22-hur-kan-man-g-ra-en"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd "$PROJECT_DIR"
exec "$(command -v python3)" main.py
