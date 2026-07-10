# BetterFingers

**A private desktop speech editor.** Speak messy thoughts, watch them get refined by a
local LLM, review the result, and place clean text into any application — all running
100% on your own machine. No cloud, no account, no subscription, no telemetry.

> A [Source Arcanum](#about) project · MIT licensed · Windows + Linux
> ⚠️ **Status: pre-release (alpha in progress).** The core dictation loop works; see
> [Project status](#project-status) for what is and isn't ready.

<!-- TODO(M0): 15-second demo GIF here — voice → clean text landing in a real app. -->

---

## What it does

Hold a hotkey (or a game-controller button), talk, and BetterFingers:

1. **Transcribes** your speech locally with Whisper (faster-whisper / CTranslate2).
2. **Refines** it with a local LLM (Gemma via llama.cpp) through a swappable **persona** —
   cleaning up grammar, tone, and formatting instead of dumping raw dictation.
3. **Shows you the draft** in a review overlay you can edit, re-run, or have read back
   aloud (Kokoro TTS) before anything lands.
4. **Injects** the final text into whatever app has focus, and restores your clipboard.
5. **Never loses audio** — every utterance's raw recording is kept so a failed run is
   recoverable, not gone.

The whole product is built around one loop:
**activate → speak → transcribe → refine → review → inject → recover when anything fails.**

## Why it's different

- **Private by design.** STT, LLM, and TTS all run locally; the only outbound network
  traffic is model downloads. A built-in privacy dashboard enumerates every touchpoint
  and wipes your data on demand.
- **Smart, not literal.** LLM personas (Formal, Polished, Unhinged, and your own) rewrite
  what you say. Build new ones with a guided interview (**Persona Foundry**).
- **Works everywhere you type.** Any app, via global hotkey or game controller — even
  mid-game, with audio ducking.
- **Respects your hardware.** Automatic hardware-tier detection recommends models that
  actually fit your machine, from CPU-only laptops to high-end GPUs.
- **Free forever.** MIT-licensed and donation-supported. No paywall waiting to appear.

## Feature highlights

| Area | What's there |
|---|---|
| Capture | Global push-to-talk (uiohook), controller trigger, long-recording chunking with progress |
| Refinement | Local LLM personas (schema v2), personal dictionary, spoken formatting commands, text macros |
| Review | Editable review overlay, TTS read-back, per-utterance confidence surfaced honestly |
| Recovery | Raw-audio retention + re-transcribe, recoverable error drafts |
| Placement | Cross-app text injection (typing/paste backends), clipboard restore |
| Recall | Full-text searchable history (SQLite FTS5) |
| Trust | Privacy dashboard, one-button data wipe, hardware-aware model recommender |

## Project status

BetterFingers is a real application with a coherent local-first architecture, packaging,
extensive tests (600+ Python unit tests, Playwright end-to-end coverage), and a deep
feature set. It is **not yet a tagged public release.** The remaining work to 1.0 — release
signing/reproducibility, a core-loop reliability benchmark, an injection-compatibility
matrix, hands-free wake word, and a unified data-lifecycle model — is tracked in
[DESIGN.md](DESIGN.md), the single source of truth for the roadmap.

**Platforms:** Windows and Linux (X11 fully; Wayland degrades global hotkeys/injection to
best-effort with honest capability reporting). **macOS is not supported yet.**

## Hardware tiers

| Tier | CPU | RAM | GPU | Suggested models |
|---|---|---|---|---|
| Minimum | 6c/12t | 16 GB | none (CPU-only OK) | Gemma 4B Q4, Whisper `base.en` |
| Recommended | 8c/16t | 32 GB | RTX 3060 12 GB class | Gemma 4B Q6/Q8, Whisper `small`/`medium.en` |
| High-perf | 12c+ | 64 GB | RTX 4080/4090 class | Gemma 12B, Whisper `large-v3` |

The in-app recommender detects your tier and never suggests a model that won't fit your
RAM. Bigger models are always opt-in.

## Privacy model

Everything runs on-device. The **only** outbound requests are model/runtime downloads you
initiate. No accounts, no analytics, no cloud inference. The Privacy dashboard
(`GET /privacy`) lists every data location on disk with sizes and retention, and
`POST /privacy/wipe` verifiably clears drafts, the searchable-history database, and raw
recordings. See [DESIGN.md §9](DESIGN.md) for the full data-lifecycle model (a unified
`DataRegistry` and optional at-rest encryption are on the roadmap).

## Install

> Packaged installers (Windows NSIS, Linux AppImage) are produced by CI on release tags
> but a **signed public release has not shipped yet**. For now, run from source.

## Run from source (Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
cd app && npm install && npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

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

- **Tests:** `python3 -m pytest -q` (full suite loads real Whisper/TTS models and peaks
  around 11 GB RAM — see the OOM note in [`tests/conftest.py`](tests/conftest.py); for
  fast iteration use `python3 -m pytest -q -k "not transcriber and not tts_engine"`).
- **End-to-end:** `cd app && npx playwright test` (needs a local LLM + `llama-server` on
  disk for the review-overlay spec; close any running instance first).
- **JS syntax check:** `node --check app/src/renderer/main.js`.
- Architecture and the full roadmap live in **[DESIGN.md](DESIGN.md)**.

## Architecture

```
Electron (app/)                      Python sidecar (repo root)
├─ main:    windows, tray,           ├─ server.py    FastAPI (~60 routes) + WebSocket
│           overlays, global         ├─ transcriber  faster-whisper (+ confidence)
│           hotkeys, injection       ├─ llm_engine   llama-server client, personas, chunking
├─ preload: auth + origin bridge     ├─ tts_engine   Kokoro (+ blend / modulation)
└─ renderer: dashboard, overlays     ├─ recorder / hotkey_manager / dictionary / macros
                                     ├─ history_store (FTS5) / recordings / model_manager
   REST + WebSocket boundary  <────> └─ hardware_report / model_recommender / privacy
   (Bearer token, versioned)
```

Electron owns the desktop surface (windows, tray, overlays, hotkeys, clipboard,
injection); Python owns everything model- and data-related (STT, LLM, TTS, personas,
recordings, history, privacy). The boundary is an inspectable, version-gated REST + WS API.

## Known limitations

- No macOS build.
- No signed installer / auto-update channel yet.
- Wayland global hotkeys and text injection are best-effort (OS limitation, not a bug).
- A local LLM has a real resource footprint on weak hardware — use the tier recommender.
- Voice cloning ships a consent + QA gate but **no synthesis engine is bundled yet**.

## Contributing & security

Found a bug or a security issue? See [SECURITY.md](SECURITY.md) for how to report
vulnerabilities privately. Roadmap and design rationale: [DESIGN.md](DESIGN.md).

## About

BetterFingers is the first release from **Source Arcanum** — private, local-first tools
that respect you. By Donaven Crenshaw.

## License

[MIT](LICENSE) © 2026 Donaven Crenshaw.
