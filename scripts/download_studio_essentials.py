#!/usr/bin/env python3
"""Download the default Studio model stack with resumable local state.

This is intentionally simple and sequential so it can survive flaky internet,
power loss, or app restarts. Re-run it and it resumes/continues from the local
model cache.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PID_PATH = Path("/tmp/betterfingers_downloads.pid")
DEFAULT_LOG_PATH = Path("/tmp/betterfingers_downloads.log")


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def main() -> int:
    from betterfingers_env import load_local_env

    load_local_env(ROOT)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    log(f"BetterFingers download worker started pid={os.getpid()}")

    import model_manager
    import studio_media_models

    jobs = [
        ("llm", "gemma-4-e4b-q4"),
        ("media", "chatterbox"),
        ("media", "ace-step-1-5"),
        ("media", "stable-audio-open-small"),
    ]

    last_progress_log = {}

    for kind, key in jobs:
        log(f"BEGIN {kind}:{key}")
        try:
            if kind == "llm":

                def progress(state):
                    now = time.time()
                    status = state.get("status", "")
                    percent = state.get("percent")
                    downloaded = state.get("downloaded_bytes") or state.get("partial_bytes") or 0
                    message = state.get("message", "")
                    should_log = status in {"starting", "complete", "error", "already_installed"}
                    should_log = should_log or (now - last_progress_log.get(key, 0) >= 30)
                    if should_log:
                        last_progress_log[key] = now
                        log(
                            f"STATE {key} status={status} "
                            f"percent={percent} bytes={downloaded} message={message}"
                        )

                result = model_manager.check_and_download_resources(key, progress_callback=progress)
                log(f"END {kind}:{key} result={result}")
            else:
                path = studio_media_models.ensure_model(
                    key,
                    progress=lambda msg: log(f"STATE {key} {msg}"),
                )
                state = studio_media_models.download_state(key)
                log(f"END {kind}:{key} path={path} state={state}")
        except Exception as exc:
            log(f"FAIL {kind}:{key} {type(exc).__name__}: {exc}")

    log("BetterFingers download worker finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
