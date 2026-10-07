# BetterFingers

**A private desktop speech editor.** Speak messy thoughts, watch them get refined by a
local LLM, review the result, and place clean text into a focused target when the
configured platform/backend supports it. Core speech processing runs on your machine:
no cloud inference, account, subscription, or telemetry.

> A [Donaven Crenshaw](#about) project · MIT licensed · Windows + Linux
> **Status: public alpha.** [v1.1.0-alpha.4](https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.4)
> includes an Authenticode-signed Windows x64 installer and an experimental Linux
> AppImage. It is still alpha software; see [Project status](#project-status) for the
> honest boundaries.

---

## What it does

Hold a hotkey (or a game-controller button), talk, and BetterFingers:

1. **Transcribes** your speech locally with Whisper (faster-whisper / CTranslate2).
2. **Refines** it with a local LLM (Gemma via llama.cpp) through a swappable **persona** —
   cleaning up grammar, tone, and formatting instead of dumping raw dictation.
3. **Shows you the draft** in a review overlay you can edit, re-run, or have read back
   aloud (Kokoro TTS) before anything lands.
4. **Injects** final text into the focused target when the configured injection path
   supports it, and restores your clipboard. With the review overlay open, the Primary
   Action key (F9 by default) accepts and places exactly the draft it is showing.
5. **Keeps captured audio for recovery** — when recording succeeds, the raw utterance is
   retained so a later transcription or refinement failure can be retried.

The whole product is built around one loop:
**activate → speak → transcribe → refine → review → inject → recover from later-stage failures.**

## Why it's different

- **Private by design.** STT, LLM, and TTS run locally. Network access is limited to
  update checks (none before you consent; automatic checks are opt-in on a fresh
  install), user-initiated model/runtime downloads, and an explicitly reviewed bug
  report when a relay has been configured; it is never used for cloud inference. A
  built-in privacy dashboard enumerates data locations and wipes your data on demand.
- **Smart, not literal.** LLM personas (Formal, Polished, Unhinged, and your own) rewrite
  what you say. Build new ones with a guided interview (**Persona Foundry**).
- **Cross-app when supported.** Hotkeys, selection capture, and injection depend on the
  desktop/platform path; Wayland is best-effort with honest capability reporting.
- **Respects your hardware.** The recommender reports model tiers from detected hardware;
  hardware compatibility remains subject to operator qualification.
- **MIT licensed.** No account, subscription, or paywall.

## Feature highlights

| Area | What's there |
|---|---|
| Capture | Global push-to-talk (uiohook), controller trigger, long-recording chunking with progress |
| Refinement | Local LLM personas (schema v2), personal dictionary, spoken formatting commands, text macros |
| Review | Editable review overlay, TTS read-back, F9 accepts and places the shown draft, per-utterance confidence surfaced honestly |
| Recovery | Raw-audio retention + re-transcribe, recoverable error drafts |
| Placement | Text injection through supported typing/paste backends; clipboard restore; qualification varies by desktop/platform path |
| Recall | Full-text searchable history (SQLite FTS5) |
| Trust | Privacy dashboard, one-button data wipe, hardware-aware model recommender |

## Project status

BetterFingers is a real local-first application with automated tests and a deep feature
set. **v1.1.0-alpha.4 is a public prerelease with a signed Windows x64 installer and a
Linux AppImage.** It is not a stable release: hardware/model compatibility, desktop
injection paths, microphone behavior, and platform-specific selection still need broader
outside testing. The release page and its CI-built assets are the public source of truth,
and its [release notes](docs/release/notes/1.1.0-alpha.4.md) list what changed since
Alpha 3. Anything merged after the Alpha 4 tag is not part of Alpha 4 until a later tag
is built, qualified, and published.

**Platforms:** Windows is the primary packaged target. The Linux AppImage has an automated
launch smoke on its release runner, while distribution and desktop-session compatibility
remain experimental. The source `Ctrl+Alt+R` selection-rewrite workflow is qualified on
X11; Wayland paths remain compositor-dependent and best-effort. **macOS is not supported.**

## Hardware tiers

| Tier | CPU | RAM | GPU | Suggested models |
|---|---|---|---|---|
| Minimum | 6c/12t | 16 GB | none (CPU-only OK) | Gemma 4B Q4, Whisper `base.en` |
| Recommended | 8c/16t | 32 GB | RTX 3060 12 GB class | Gemma 4B Q6/Q8, Whisper `small`/`medium.en` |
| High-perf | 12c+ | 64 GB | RTX 4080/4090 class | Gemma 12B, Whisper `large-v3` |

The in-app recommender uses detected hardware to estimate a suitable tier. Those fit
estimates are guidance, not a guarantee; bigger models remain opt-in.

## Privacy model

Speech processing runs on-device. No update checks run before durable privacy consent.
Fresh installs leave automatic checks off; Settings lets you opt in or manually check
GitHub releases for newer versions. Existing accepted v1 onboarding records without an
update preference retain automatic checks; explicit preferences are preserved, and
unreadable/future records fail closed. Network requests are limited to these checks,
user-initiated model/runtime downloads, and an explicitly confirmed bug report when an
operator-configured relay exists. No accounts, analytics, or cloud inference. The
Privacy dashboard
(`GET /privacy`) lists every data location on disk with sizes and retention, and
`POST /privacy/wipe` verifiably clears drafts, the searchable-history database, and raw
recordings, including the backup and quarantine copies the app keeps for recovery.
Deleting a single item (a draft or history entry, a persona or persona example, a
contact, a dictionary or macro entry, a voice preset) removes it from those recovery
copies too, and the Windows uninstaller's "remove my data" option deletes them as well.
See [DESIGN.md §9](DESIGN.md) for the full data-lifecycle model (a unified
`DataRegistry` and optional at-rest encryption are on the roadmap).

Bug reports are review-first: the app shows the bounded diagnostic payload before asking
permission to send it. The relay code can deliver to Discord and/or email without placing
provider secrets in the desktop app, but **no relay endpoint is deployed or enabled by
this release**; until one exists, the in-app flow copies the reviewed report and opens
your email client or the Discord invite, and never claims it was delivered.

## Install

### Windows

Download the installer from the
**[v1.1.0-alpha.4 release](https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.4)**.
The published Windows installer is Authenticode-signed. Windows SmartScreen can still
warn on a new, low-reputation alpha; verify the signature and release URL instead of
downloading copies from third-party mirrors. You can install
Alpha 4 over an existing Alpha 3 copy; your data is kept unless you choose to remove it
at uninstall.

### Linux

The same release contains an experimental AppImage with a SHA-256 sidecar. Its automated
runner launch smoke is useful package evidence, not a promise that every distribution,
Wayland compositor, audio stack, or injection tool works. You can also run from source:


```bash
# Hardware-aware bootstrap: creates ./.venv and installs the torch build that
# matches your machine. On a GPU-less box it installs CPU-only torch, skipping
# the ~3.9 GB of CUDA/nvidia wheels the default install would pull in.
python3 tools/setup_venv.py
cd app && npm install && npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

The bootstrap auto-detects an NVIDIA GPU via `nvidia-smi`. Override with
`--torch cpu` or `--torch cuda` if you want to force a build. The old manual
path still works (`python3 -m venv .venv && source .venv/bin/activate &&
pip install -r requirements.txt`) but on Linux it always pulls the CUDA stack.

The Electron shell starts the FastAPI backend automatically on port 8000
(`BETTERFINGERS_HOST` / `BETTERFINGERS_PORT` are honored end-to-end).

You also need a local `llama-server` binary for LLM cleanup. BetterFingers looks for it at
`.betterfingers/llama-server/bin/llama-server`; provision one with:

```bash
python tools/setup_linux_llama_server.py --from /path/to/llama-server
# or build from a llama.cpp checkout:
python tools/setup_linux_llama_server.py --source .betterfingers/llama.cpp
# CUDA build:
python tools/setup_linux_llama_server.py --source .betterfingers/llama.cpp --cmake-arg=-DGGML_CUDA=ON
```

Overrides: `BETTERFINGERS_LLAMA_SERVER=/path/to/llama-server`,
`BETTERFINGERS_MODEL_PATH=/path/to/model.gguf`.

## Development

- **Tests:** `python3 -m pytest -q` (the full suite loads real Whisper/TTS models and peaks
  around 11 GB RAM — see the OOM note in [`tests/conftest.py`](tests/conftest.py)); for
  fast iteration use the roughly 40-second loop in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
- **End-to-end:** `cd app && npx playwright test` (needs a local LLM + `llama-server` on
  disk for the review-overlay spec; close any running instance first).
- **JS syntax check:** `node --check app/src/renderer/main.js`.
- Platform boundaries are documented in
  [SUPPORTED_PLATFORMS.md](docs/release/SUPPORTED_PLATFORMS.md); Windows release signing
  lives in [WINDOWS_SIGNING.md](docs/release/WINDOWS_SIGNING.md), and
  [DESIGN.md](DESIGN.md) remains the product/architecture reference.

## Architecture

```
Electron (app/)                      Python sidecar (server.py + backend/)
├─ main:    windows, tray,           ├─ server.py        FastAPI app, auth, startup (no routes)
│           overlays, global         ├─ backend/api      one router per domain + WebSocket
│           hotkeys, injection       ├─ backend/stt      faster-whisper (+ confidence)
├─ preload: auth + origin bridge     ├─ backend/llm      llama-server client, personas, chunking
└─ renderer: dashboard, overlays     ├─ backend/tts      Kokoro (+ blend / modulation)
                                     ├─ backend/audio / input / commands / output
   REST + WebSocket boundary  <────> ├─ backend/stores   history (FTS5), recordings, dictionary, macros
   (Bearer token, versioned)         └─ backend/models / platform / privacy
```

Electron owns the desktop surface (windows, tray, overlays, hotkeys, clipboard,
injection); Python owns everything model- and data-related (STT, LLM, TTS, personas,
recordings, history, privacy). The boundary is an inspectable, version-gated REST + WS API.

## Known limitations

- No macOS build.
- The signed Windows installer is still an alpha and may trigger SmartScreen reputation
  warnings.
- On X11, selection/copy and typing paths require `DISPLAY`, `xclip` (or `xsel`), and
  `xdotool` where those paths are used. Wayland best-effort paths use `WAYLAND_DISPLAY`,
  `wl-copy`/`wl-paste` from `wl-clipboard`, and `wtype` or `ydotool` where the
  compositor permits them; tool presence alone is not qualification.
- Wayland global hotkeys and text injection are best-effort (OS limitation, not a bug),
  and Wayland is not qualified on the current host.
- Selected-text TTS, injection/PTT, audio devices, and model performance still vary by
  desktop, hardware, and target application.
- A local LLM has a real resource footprint on weak hardware — use the tier recommender.
- Speech-to-text runs on the CPU in the installed app. NVIDIA GPU transcription needs
  CUDA libraries the installer does not ship, so it is a developer-only option for now
  (see [DEVELOPMENT.md](docs/DEVELOPMENT.md)); AMD/Intel GPU transcription is not offered.
- Voice-cloning synthesis is implemented through an optional, pinned runtime; that large
  runtime is not bundled and remains hardware/performance dependent.
- The Kokoro read-aloud runtime ships in the installer, but its voice files (about 354 MB)
  download automatically the first time you use read-aloud, with no separate prompt in
  this release. They are checked against a pinned size and SHA-256 before use.
- Production-grade at-rest encryption is not included. Raw recordings are retained for
  recovery until the user deletes or wipes them.
- The Discord/email relay is code-complete but not a live service until its operator
  deploys the endpoint and server-side credentials.

## Report a bug

Use **Utilities → Diagnostics → Report a Bug** in the app (review-first: you see exactly
what would be shared and must confirm), or open
[GitHub Issues](https://github.com/RoyGSlade/BetterFingers/issues) or the
[BetterFingers Discord](https://discord.gg/m3HH45CFwz) yourself. Automatic delivery stays
disabled until a private relay is deployed and configured, so the in-app flow hands the
reviewed report to your email client or Discord rather than sending it. Security
vulnerabilities belong in the private process in [SECURITY.md](SECURITY.md), not a public
issue or Discord post.

## Contributing & security

See [SECURITY.md](SECURITY.md) for private vulnerability reporting. Roadmap and design
rationale: [DESIGN.md](DESIGN.md).

## About

BetterFingers is a project by **Donaven Crenshaw** — private, local-first software that
respects you.

## License

[MIT](LICENSE) © 2026 Donaven Crenshaw.
