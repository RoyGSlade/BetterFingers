#!/usr/bin/env bash
# Generate a desktop launcher for BetterFingers with this repo's real path.
# Safe to re-run; it overwrites the generated entry in place.
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$APP_DIR/BetterFingers.desktop"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DEST="$DEST_DIR/betterfingers.desktop"

if [[ ! -f "$TEMPLATE" ]]; then
  printf 'Template not found: %s\n' "$TEMPLATE" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
# Substitute the @APP_DIR@ placeholder with the resolved repo path.
sed "s|@APP_DIR@|$APP_DIR|g" "$TEMPLATE" > "$DEST"
chmod +x "$DEST" 2>/dev/null || true

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DEST_DIR" >/dev/null 2>&1 || true
fi

printf 'Installed launcher: %s\n' "$DEST"
printf 'App directory: %s\n' "$APP_DIR"
