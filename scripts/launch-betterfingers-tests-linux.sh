#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/BetterFingers"
LAUNCH_LOG="$LOG_DIR/test-shortcut-launch.log"
RUNNER="$APP_DIR/scripts/run-betterfingers-tests-linux.sh"

mkdir -p "$LOG_DIR"

{
  printf '\n[%s] Launch requested\n' "$(date -Iseconds)"
  printf 'App: %s\n' "$APP_DIR"
  printf 'Runner: %s\n' "$RUNNER"
  printf 'DISPLAY=%s WAYLAND_DISPLAY=%s XDG_SESSION_TYPE=%s XDG_CURRENT_DESKTOP=%s\n' \
    "${DISPLAY:-}" "${WAYLAND_DISPLAY:-}" "${XDG_SESSION_TYPE:-}" "${XDG_CURRENT_DESKTOP:-}"
} >>"$LAUNCH_LOG"

if ! command -v gnome-terminal >/dev/null 2>&1; then
  printf '[%s] gnome-terminal not found\n' "$(date -Iseconds)" >>"$LAUNCH_LOG"
  exit 1
fi

systemd-run --scope --user --collect --quiet -- \
  gnome-terminal --wait --title "BetterFingers Tests" -- \
  bash -lc 'cd "$1" && exec "$2"' bash "$APP_DIR" "$RUNNER" &
terminal_scope_pid=$!

sleep 1
if command -v wmctrl >/dev/null 2>&1; then
  wmctrl -a "BetterFingers Tests" 2>/dev/null || true
fi

wait "$terminal_scope_pid"
