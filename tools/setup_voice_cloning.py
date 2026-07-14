"""Provision the optional voice-cloning engine (DESIGN §10 M5 U6).

Cloned-voice synthesis re-voices Kokoro output with the Kanade voice-conversion
model (the kokoclone approach). Its dependencies stay OUT of the hashed lock
files on purpose — kanade-tokenizer is a git-only package pip-compile cannot
hash — so, like llama-server, the capability is provisioned on demand by this
script, pinned to exact versions:

  1. pip-installs torchaudio and kanade-tokenizer @ a pinned commit into the
     current interpreter's environment,
  2. pre-downloads the Kanade model + vocoder from Hugging Face at a pinned
     revision (otherwise the first cloned-voice playback pays the download).

Run it with the project venv:  .venv/bin/python tools/setup_voice_cloning.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_clone_engine import (  # noqa: E402
    KANADE_MODEL_REPO,
    KANADE_MODEL_REVISION,
    KANADE_TOKENIZER_COMMIT,
    KANADE_TOKENIZER_REPO,
    availability,
)


def main():
    status = availability()
    if status["available"]:
        print("[voice-cloning] dependencies already installed.")
    else:
        print(f"[voice-cloning] installing: {status['reason']}")
        cmd = [
            sys.executable, "-m", "pip", "install",
            "torchaudio",
            f"git+{KANADE_TOKENIZER_REPO}@{KANADE_TOKENIZER_COMMIT}",
        ]
        print("[voice-cloning] $", " ".join(cmd))
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("[voice-cloning] pip install failed.", file=sys.stderr)
            return result.returncode

    print(f"[voice-cloning] pre-downloading {KANADE_MODEL_REPO}@{KANADE_MODEL_REVISION[:12]} ...")
    from kanade_tokenizer import KanadeModel, load_vocoder

    model = KanadeModel.from_pretrained(KANADE_MODEL_REPO, revision=KANADE_MODEL_REVISION)
    vocoder_name = getattr(model.config, "vocoder_name", "vocos")
    load_vocoder(vocoder_name)
    print(f"[voice-cloning] ready (model + {vocoder_name} vocoder cached). "
          f"Cloned voices will now synthesize for real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
