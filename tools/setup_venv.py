#!/usr/bin/env python3
"""
Hardware-aware Python environment bootstrap for BetterFingers.

The runtime deps pull in ``torch`` (via ``kokoro``, the TTS backend). On Linux
the default PyPI ``torch`` wheel is the CUDA build, which drags in ~3.9 GB of
``nvidia-*`` wheels. On a machine with no NVIDIA GPU those are dead weight — the
llama.cpp server we ship is CPU-only there anyway (see hardware_report.py). This
script detects the GPU and installs the matching ``torch`` build *before* the
rest of ``requirements.txt``, so kokoro's ``torch`` dependency is already
satisfied and pip never fetches the CUDA stack on hardware that can't use it.

Typical setup (auto-detects hardware, creates ./.venv):
  python tools/setup_venv.py

Force a variant:
  python tools/setup_venv.py --torch cpu     # never fetch CUDA wheels
  python tools/setup_venv.py --torch cuda     # force the CUDA build

Install into the current interpreter instead of a venv (used by CI):
  python tools/setup_venv.py --no-venv

Detection is a pure function of ``nvidia-smi`` presence, mirroring
hardware_report._detect_gpu() but kept import-free so this runs on a bare
interpreter before any dependency is installed.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = REPO_ROOT / ".venv"
DEFAULT_REQUIREMENTS = REPO_ROOT / "requirements.txt"

# PyTorch's CPU-only wheel index. Installing torch from here (instead of default
# PyPI) skips the bundled CUDA runtime and every nvidia-* wheel.
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def detect_cuda():
    """True when an NVIDIA CUDA GPU is present.

    Mirrors hardware_report._detect_gpu()'s nvidia-smi probe, but self-contained
    so it works before psutil / model_manager are importable.
    """
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False
    try:
        result = subprocess.run(
            [smi, "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0 and bool((result.stdout or "").strip())


def resolve_torch_channel(system, torch_arg, cuda_present):
    """Decide which torch build to install. Pure function for unit testing.

    Returns "cpu" (install from the CPU wheel index) or "default" (let pip
    resolve torch normally from PyPI, as a transitive dep of the requirements).

    Only Linux has the CUDA-bloat problem: the default macOS/Windows torch
    wheels are already CPU/MPS builds without the nvidia-* payload, so "auto"
    there defers to the normal requirements resolution.
    """
    if torch_arg == "cpu":
        return "cpu"
    if torch_arg == "cuda":
        return "default"
    # auto
    if system == "Linux" and not cuda_present:
        return "cpu"
    return "default"


def _venv_python(venv_dir):
    """Path to the interpreter inside a venv, cross-platform."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(cmd, dry_run):
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable}", flush=True)
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Hardware-aware venv bootstrap for BetterFingers."
    )
    parser.add_argument(
        "--torch",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Which torch build to install (default: auto-detect via nvidia-smi).",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=DEFAULT_VENV,
        help="Virtualenv directory to create/use (default: ./.venv).",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help="Requirements file to install (default: ./requirements.txt).",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Install into the current interpreter instead of a venv (for CI).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the pip commands without running them.",
    )
    args = parser.parse_args(argv)

    system = platform.system()
    cuda_present = detect_cuda()
    channel = resolve_torch_channel(system, args.torch, cuda_present)

    print(f"Platform: {system}  |  CUDA GPU detected: {cuda_present}")
    if channel == "cpu":
        reason = "forced" if args.torch == "cpu" else "no CUDA GPU"
        print(f"torch build: CPU-only ({reason}) — skipping the ~3.9 GB CUDA stack")
    else:
        reason = "forced" if args.torch == "cuda" else "default resolution"
        print(f"torch build: default ({reason})")

    # Resolve the interpreter to install into.
    if args.no_venv:
        python = Path(sys.executable)
    else:
        venv_dir = args.venv
        python = _venv_python(venv_dir)
        if not python.exists():
            print(f"Creating virtualenv at {venv_dir} ...")
            rc = _run([sys.executable, "-m", "venv", str(venv_dir)], args.dry_run)
            if rc != 0 and not args.dry_run:
                print("ERROR: failed to create virtualenv", file=sys.stderr)
                return rc
        else:
            print(f"Reusing existing virtualenv at {venv_dir}")

    pip = [str(python), "-m", "pip"]

    print("Upgrading pip ...")
    rc = _run(pip + ["install", "--upgrade", "pip"], args.dry_run)
    if rc != 0:
        return rc

    # Install the CPU torch wheel first so kokoro's torch dep is already
    # satisfied when the requirements resolve — otherwise pip pulls CUDA torch.
    if channel == "cpu":
        print("Installing CPU-only torch ...")
        rc = _run(
            pip + ["install", "torch", "--index-url", TORCH_CPU_INDEX], args.dry_run
        )
        if rc != 0:
            return rc

    if not args.requirements.exists() and not args.dry_run:
        print(f"ERROR: requirements file not found: {args.requirements}", file=sys.stderr)
        return 1

    print(f"Installing {args.requirements} ...")
    rc = _run(pip + ["install", "-r", str(args.requirements)], args.dry_run)
    if rc != 0:
        return rc

    # Confirm the resulting torch build so a mistaken CUDA pull is loud, not silent.
    if not args.dry_run:
        probe = _run(
            [
                str(python),
                "-c",
                "import torch; print('torch', torch.__version__, "
                "'cuda?', torch.cuda.is_available())",
            ],
            False,
        )
        if probe != 0:
            print("WARNING: torch import probe failed (see output above).", file=sys.stderr)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
