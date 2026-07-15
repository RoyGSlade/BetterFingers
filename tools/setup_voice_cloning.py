"""Provision the voice-cloning engine's side-runtime (DESIGN §10 M5/M6 U6).

Cloned-voice synthesis re-voices Kokoro output with the Kanade voice-
conversion model (the kokoclone approach). Its dependencies (torch,
torchaudio, kanade-tokenizer) are provisioned as a self-contained,
sha256-verified runtime rather than pip-installed into this interpreter:
kanade-tokenizer is git-only (pip-compile cannot hash it), and more to the
point, pip-install-into-sys.executable cannot work at all in a frozen
(PyInstaller) build — there is no writable site-packages to install into.
This mirrors how llama-server is provisioned: download, verify, extract; see
voice_clone_engine.provision_clone_runtime for the implementation.

If kanade-tokenizer/torchaudio are already importable in THIS interpreter
(e.g. a developer pip-installed them manually into the project venv), that
in-process path keeps working unchanged and this tool has nothing to do.

Run it with the project venv or the frozen app:
  .venv/bin/python tools/setup_voice_cloning.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_clone_engine import availability, provision_clone_runtime  # noqa: E402


def _progress(payload):
    percent = payload.get("percent")
    desc = payload.get("desc", "downloading")
    if percent is not None:
        print(f"[voice-cloning] {desc}: {percent:.0f}%", end="\r")


def main():
    status = availability()
    if status["available"]:
        print(f"[voice-cloning] already available (mechanism={status['mechanism']}).")
        return 0

    print(f"[voice-cloning] not available yet ({status['reason']}). Provisioning the clone runtime...")
    result = provision_clone_runtime(progress_callback=_progress)
    print()
    if not result.get("ok", False):
        print(f"[voice-cloning] provisioning failed: {result.get('message')}", file=sys.stderr)
        return 1

    if result.get("already_provisioned"):
        print("[voice-cloning] runtime was already provisioned.")
    else:
        print("[voice-cloning] ready. Cloned voices will now synthesize for real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
