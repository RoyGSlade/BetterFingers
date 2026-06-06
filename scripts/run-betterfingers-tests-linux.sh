#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/BetterFingers"
RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"
TEST_LOG="$LOG_DIR/tests-$RUN_ID.log"

mkdir -p "$LOG_DIR"

resolve_python() {
  if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$APP_DIR/.venv/bin/python"
    return
  fi
  command -v python3
}

pause_if_interactive() {
  if [[ -t 0 ]]; then
    printf '\nPress Enter to close this window...'
    read -r _ || true
  elif { exec 3</dev/tty; } 2>/dev/null; then
    printf '\nPress Enter to close this window...'
    read -r _ <&3 || true
    exec 3<&-
  fi
}

ensure_pytest() {
  if "$PYTHON_BIN" -c "import pytest" >/dev/null 2>&1; then
    return 0
  fi

  printf 'pytest is not installed for %s.\n' "$PYTHON_BIN" >&2

  if [[ "$PYTHON_BIN" == "$APP_DIR/.venv/bin/python" && -t 0 ]]; then
    printf 'Install pytest into the project venv now? [Y/n] '
    read -r reply || reply="n"
    case "${reply:-Y}" in
      [Yy]|[Yy][Ee][Ss])
        "$PYTHON_BIN" -m pip install pytest
        return
        ;;
    esac
  fi

  printf 'Run this first: %s -m pip install pytest\n' "$PYTHON_BIN" >&2
  return 1
}

PYTHON_BIN="${BETTERFINGERS_PYTHON:-$(resolve_python)}"

cd "$APP_DIR"

printf 'BetterFingers test runner\n'
printf 'App: %s\n' "$APP_DIR"
printf 'Python: %s\n' "$PYTHON_BIN"
printf 'Log: %s\n\n' "$TEST_LOG"

if ! ensure_pytest; then
  pause_if_interactive
  exit 1
fi

if [[ "$#" -gt 0 ]]; then
  TEST_TARGETS=("$@")
else
  TEST_TARGETS=(tests)
fi

printf 'Running: %s -m pytest' "$PYTHON_BIN"
printf ' %q' "${TEST_TARGETS[@]}"
printf '\n\n'

set +e
"$PYTHON_BIN" -m pytest "${TEST_TARGETS[@]}" 2>&1 | tee "$TEST_LOG"
status=${PIPESTATUS[0]}
set -e

printf '\nTest command exited with status %s.\n' "$status"
printf 'Saved log: %s\n' "$TEST_LOG"
pause_if_interactive
exit "$status"
