#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NODE_DIR="$APP_DIR/app"
HOST="${BETTERFINGERS_HOST:-127.0.0.1}"
PORT="${BETTERFINGERS_PORT:-8000}"

STATE_DIR="${XDG_RUNTIME_DIR:-/tmp}/betterfingers-launcher-${UID}"
STATE_FILE="$STATE_DIR/current.env"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/BetterFingers"
RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"

mkdir -p "$STATE_DIR" "$LOG_DIR"

resolve_python() {
  if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$APP_DIR/.venv/bin/python"
    return
  fi
  command -v python3
}

PYTHON_BIN="${BETTERFINGERS_PYTHON:-$(resolve_python)}"
BACKEND_LOG="$LOG_DIR/backend-$RUN_ID.log"
ELECTRON_LOG="$LOG_DIR/electron-$RUN_ID.log"

current_pgid() {
  ps -o pgid= "$$" | tr -d '[:space:]'
}

kill_group() {
  local label="$1"
  local pgid="${2:-}"
  local self_pgid
  self_pgid="$(current_pgid)"

  if [[ -z "$pgid" || "$pgid" == "$self_pgid" ]]; then
    return 0
  fi

  if sudo kill -0 -- "-$pgid" 2>/dev/null; then
    printf 'Stopping previous %s process group %s...\n' "$label" "$pgid"
    sudo kill -TERM -- "-$pgid" 2>/dev/null || true
    sleep 2
  fi

  if sudo kill -0 -- "-$pgid" 2>/dev/null; then
    printf 'Force-stopping previous %s process group %s...\n' "$label" "$pgid"
    sudo kill -KILL -- "-$pgid" 2>/dev/null || true
  fi
}

kill_matching_processes() {
  local label="$1"
  local pattern="$2"
  local self_pgid pgid
  self_pgid="$(current_pgid)"

  while read -r pgid; do
    pgid="$(echo "$pgid" | tr -d '[:space:]')"
    if [[ -z "$pgid" || "$pgid" == "$self_pgid" ]]; then
      continue
    fi
    kill_group "$label" "$pgid"
  done < <(
    pgrep -f "$pattern" 2>/dev/null \
      | xargs -r -n1 ps -o pgid= -p 2>/dev/null \
      | sort -u
  )
}

kill_stale_betterfingers_runtime() {
  kill_matching_processes "BetterFingers backend" "$APP_DIR/server.py.*--host $HOST.*--port $PORT"
  kill_matching_processes "BetterFingers llama server" "$APP_DIR/.betterfingers/llama-server/bin/llama-server"
  kill_matching_processes "BetterFingers Electron" "$APP_NODE_DIR/node_modules/electron/dist/electron"
  kill_matching_processes "BetterFingers Electron dev server" "$APP_NODE_DIR/node_modules/.bin/electron-vite.*dev"
}

kill_previous_launch() {
  if [[ ! -f "$STATE_FILE" ]]; then
    kill_stale_betterfingers_runtime
    return 0
  fi

  # shellcheck disable=SC1090
  source "$STATE_FILE" || true
  kill_group "Electron" "${ELECTRON_PGID:-}"
  kill_group "backend" "${BACKEND_PGID:-}"
  rm -f "$STATE_FILE"
  kill_stale_betterfingers_runtime
}

write_state() {
  cat > "$STATE_FILE" <<EOF
RUN_ID='$RUN_ID'
BACKEND_PGID='${BACKEND_PID:-}'
ELECTRON_PGID='${ELECTRON_PID:-}'
EOF
}

resolve_backend_pgid() {
  pgrep -f "$APP_DIR/server.py.*--host $HOST.*--port $PORT" 2>/dev/null \
    | head -n 1 \
    | xargs -r ps -o pgid= -p 2>/dev/null \
    | tr -d '[:space:]'
}

cleanup_this_launch() {
  local saved_run_id=""
  if [[ -f "$STATE_FILE" ]]; then
    saved_run_id="$(sed -n "s/^RUN_ID='\\(.*\\)'$/\\1/p" "$STATE_FILE" 2>/dev/null || true)"
  fi

  if [[ "$saved_run_id" == "$RUN_ID" ]]; then
    kill_group "Electron" "${ELECTRON_PID:-}"
    kill_group "backend" "${BACKEND_PID:-}"
    rm -f "$STATE_FILE"
  fi
}

wait_for_backend() {
  "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import sys
import time
import urllib.request

host = sys.argv[1]
port = sys.argv[2]
url = f"http://{host}:{port}/health"
deadline = time.time() + 45
last_error = ""

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            if 200 <= response.status < 300:
                print(f"Backend is healthy at {url}")
                raise SystemExit(0)
    except Exception as exc:
        last_error = str(exc)
    time.sleep(0.5)

print(f"Timed out waiting for backend at {url}: {last_error}", file=sys.stderr)
raise SystemExit(1)
PY
}

user_site_pythonpath() {
  python3 - <<'PY' 2>/dev/null || true
import site
paths = []
try:
    paths.append(site.getusersitepackages())
except Exception:
    pass
print(":".join(path for path in paths if path))
PY
}

if [[ ! -d "$APP_NODE_DIR/node_modules" ]]; then
  printf 'Missing Electron dependencies at %s/node_modules.\n' "$APP_NODE_DIR" >&2
  printf 'Run: cd %s && npm install && npm run fix:electron\n' "$APP_NODE_DIR" >&2
  exit 1
fi

printf 'BetterFingers Linux launcher\n'
printf 'App: %s\n' "$APP_DIR"
printf 'Python: %s\n' "$PYTHON_BIN"
printf 'Logs: %s\n\n' "$LOG_DIR"

printf 'Requesting sudo now so Linux keyboard hooks can access input devices...\n'
sudo -v

kill_previous_launch
trap cleanup_this_launch EXIT INT TERM

PYTHONPATH_EXTRA="$(user_site_pythonpath)"
if [[ -n "${PYTHONPATH:-}" ]]; then
  PYTHONPATH_EXTRA="${PYTHONPATH_EXTRA:+$PYTHONPATH_EXTRA:}$PYTHONPATH"
fi

printf 'Starting root backend from current code...\n'
sudo -E setsid env \
  HOME="$HOME" \
  USER="${USER:-}" \
  LOGNAME="${LOGNAME:-${USER:-}}" \
  PATH="$PATH" \
  PYTHONPATH="$PYTHONPATH_EXTRA" \
  BETTERFINGERS_LAZY_STARTUP=1 \
  BETTERFINGERS_ENV=development \
  "$PYTHON_BIN" "$APP_DIR/server.py" --host "$HOST" --port "$PORT" --log-level INFO \
  >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
write_state

if ! wait_for_backend; then
  printf 'Backend failed to become healthy. Last backend log lines:\n' >&2
  tail -n 80 "$BACKEND_LOG" >&2 || true
  exit 1
fi
BACKEND_PID="$(resolve_backend_pgid || true)"
BACKEND_PID="${BACKEND_PID:-}"
write_state

printf 'Starting Electron UI from current code...\n'
(
  cd "$APP_NODE_DIR"
  setsid env \
    BETTERFINGERS_PYTHON="$PYTHON_BIN" \
    BETTERFINGERS_HOST="$HOST" \
    BETTERFINGERS_PORT="$PORT" \
    npm run dev
) >>"$ELECTRON_LOG" 2>&1 &
ELECTRON_PID=$!
write_state

printf '\nBetterFingers is running. Click the shortcut again for a full restart.\n'
printf 'Backend log: %s\n' "$BACKEND_LOG"
printf 'Electron log: %s\n\n' "$ELECTRON_LOG"

wait "$ELECTRON_PID"
