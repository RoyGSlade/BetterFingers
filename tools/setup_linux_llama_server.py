#!/usr/bin/env python3
"""
Install a Linux/macOS llama-server binary into the repo-local BetterFingers runtime path.

Typical Linux flow:
  python tools/setup_linux_llama_server.py --from /path/to/llama-server

Optional local llama.cpp build flow:
  python tools/setup_linux_llama_server.py --source .betterfingers/llama.cpp
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_DIR = REPO_ROOT / ".betterfingers" / "llama-server" / "bin"
SERVER_NAME = "llama-server.exe" if sys.platform.startswith("win") else "llama-server"
INSTALL_PATH = INSTALL_DIR / SERVER_NAME


def _make_executable(path):
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(command, cwd=None):
    print(f"+ {' '.join(str(part) for part in command)}")
    subprocess.run(command, cwd=cwd, check=True)


def install_from_binary(source):
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"llama-server binary not found: {source_path}")
    if source_path.is_dir():
        raise IsADirectoryError(f"Expected a file, got directory: {source_path}")

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, INSTALL_PATH)
    _make_executable(INSTALL_PATH)
    return INSTALL_PATH


def build_from_source(source, build_dir=None, cmake_args=None):
    source_dir = Path(source).expanduser().resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"llama.cpp source directory not found: {source_dir}")

    cmake = shutil.which("cmake")
    if not cmake:
        raise RuntimeError("cmake is required to build llama-server from source.")

    resolved_build_dir = Path(build_dir).expanduser().resolve() if build_dir else source_dir / "build"
    configure_command = [
        cmake,
        "-S",
        str(source_dir),
        "-B",
        str(resolved_build_dir),
        "-DLLAMA_BUILD_SERVER=ON",
    ]
    configure_command.extend(cmake_args or [])
    _run(configure_command)
    _run([cmake, "--build", str(resolved_build_dir), "--target", "llama-server", "-j"])

    candidates = [
        resolved_build_dir / "bin" / SERVER_NAME,
        resolved_build_dir / "bin" / "llama-server",
        resolved_build_dir / "llama-server",
    ]
    for candidate in candidates:
        if candidate.exists():
            return install_from_binary(candidate)

    raise FileNotFoundError(f"Build completed, but llama-server was not found under {resolved_build_dir}")


def print_status(path=INSTALL_PATH):
    print(f"Repo-local llama-server path: {path}")
    print(f"Exists: {'yes' if path.exists() else 'no'}")
    if path.exists():
        print(f"Use this if you want an explicit override:")
        print(f"export BETTERFINGERS_LLAMA_SERVER={path}")
    else:
        print("Install one with --from /path/to/llama-server or --source /path/to/llama.cpp")


def parse_args():
    parser = argparse.ArgumentParser(description="Set up repo-local llama-server for BetterFingers Linux development.")
    parser.add_argument("--from", dest="source_binary", help="Copy an existing llama-server binary into the repo.")
    parser.add_argument("--source", dest="source_dir", help="Build llama-server from a local llama.cpp source checkout.")
    parser.add_argument("--build-dir", help="Optional CMake build directory when using --source.")
    parser.add_argument(
        "--cmake-arg",
        action="append",
        default=[],
        help="Extra CMake argument, for example --cmake-arg=-DGGML_CUDA=ON. Can be repeated.",
    )
    parser.add_argument("--print-env", action="store_true", help="Print the BETTERFINGERS_LLAMA_SERVER export line.")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.source_binary and args.source_dir:
        raise SystemExit("Use either --from or --source, not both.")

    installed_path = None
    if args.source_binary:
        installed_path = install_from_binary(args.source_binary)
        print(f"Installed llama-server to {installed_path}")
    elif args.source_dir:
        installed_path = build_from_source(args.source_dir, build_dir=args.build_dir, cmake_args=args.cmake_arg)
        print(f"Built and installed llama-server to {installed_path}")

    if args.print_env:
        print(f"export BETTERFINGERS_LLAMA_SERVER={installed_path or INSTALL_PATH}")
    else:
        print_status(installed_path or INSTALL_PATH)


if __name__ == "__main__":
    main()
