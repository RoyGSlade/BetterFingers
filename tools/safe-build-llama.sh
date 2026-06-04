#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="${1:-.betterfingers/llama.cpp/build}"
TARGET="${2:-llama-server}"
JOBS="${BUILD_JOBS:-1}"

if ! [[ "$JOBS" =~ ^[0-9]+$ ]] || [[ "$JOBS" -lt 1 ]]; then
  echo "BUILD_JOBS must be a positive integer; defaulting to 1."
  JOBS=1
fi

echo "BetterFingers safe llama build"
echo "Build dir: $BUILD_DIR"
echo "Target: $TARGET"
echo "Parallel jobs: $JOBS"
echo

echo "+ free -h"
free -h || true
echo

echo "+ swapon --show"
swapon --show || true
echo

echo "+ nproc"
nproc || true
echo

echo "+ pgrep active build processes"
ACTIVE="$(pgrep -a 'cmake|ninja|make|cc1plus|g\+\+|clang\+\+' || true)"
if [[ -n "$ACTIVE" ]]; then
  echo "$ACTIVE"
  echo
  echo "Another build process appears to be active. Refusing to start a second llama build."
  exit 2
fi

if [[ ! -d "$BUILD_DIR" ]]; then
  echo "Build directory does not exist: $BUILD_DIR"
  echo "Create it with tools/setup_linux_llama_server.py --source .betterfingers/llama.cpp first."
  exit 1
fi

if command -v ionice >/dev/null 2>&1; then
  IO_PREFIX=(ionice -c2 -n7)
else
  IO_PREFIX=()
fi

if command -v nice >/dev/null 2>&1; then
  NICE_PREFIX=(nice -n 10)
else
  NICE_PREFIX=()
fi

"${NICE_PREFIX[@]}" "${IO_PREFIX[@]}" \
  cmake --build "$BUILD_DIR" --target "$TARGET" --parallel "$JOBS"

echo
echo "Built llama-server candidates:"
find "$BUILD_DIR" -type f \( -name "llama-server" -o -name "server" \) -executable | sort
