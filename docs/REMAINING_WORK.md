# Remaining work — honest scoping

As of the MASTER_PLAN loop pause. The suite is at **276 passing**. Sixteen
roadmap items are complete or advanced: **C1, C2, C4, C6, C7, C8, C9, C10, C11,
U2, U3, U4, U5, U6, U7, U8** (see the "Implementation progress" log at the top
of `MASTER_PLAN.md` for per-item detail and deferred sub-parts).

The loop originally paused here because most remaining items need something the
**autonomous CI-style loop environment can't provision** — a real GPU, heavy ML
dependencies, a packaged app, or per-OS window/native APIs — and writing code
that can't be verified is explicitly out of bounds. Note this is about the loop's
provisioning, not hardware limits in general: on a suitably-equipped local
machine (e.g. an RTX 4060 Ti with a live display and the deps installed),
Playwright + Electron drive the real app end-to-end, and U1 has since been
advanced that way (see below). Each item below states exactly what's blocking it
and the first concrete step for a human (or a suitably-provisioned environment).

---

## Deferred sub-parts of shipped items

These items are marked done for their testable core; the remainder needs a real
environment:

- **U6 — Kokoro voice blending.** Math core (`voice_blend.py`) is shipped and
  tested. TODO: extract real voice tensors from `voices-v1.0.bin` (downloaded on
  demand, not in-repo), a slider editor UI, and saving blended voicepacks to
  disk. Needs the Kokoro asset + a running app to hear the result.
- **U7 — Persona editor.** Schema v2, migration, routes, and the Advanced editor
  are shipped. TODO (polish): live prompt preview, full voice base/blend/speed +
  few-shot raw→out list UI, `dictionary_scope` control.
- **U5 — TTS.** Normalization + smart-split shipped. TODO: loudness/BS.1770
  normalization, chunk crossfade, utterance cache — all need audio output to
  tune by ear.
- **C9 — Golden audio suite.** WER scoring core (`wer.py`) + fixture format
  shipped. TODO: check in real `.wav`/`.txt` fixtures and a CI job that runs them
  per configured STT model. Needs recorded audio + a model download in CI.

## Not started — blocked

- **U1 — Screenshot QA of every page.** First step done: `app/playwright.config.js`,
  an `app/tests/electron-smoke.spec.js` smoke spec (launches the packaged app,
  walks Dashboard/Settings/Models/Diagnostics, screenshots every top-level page),
  and `.github/workflows/e2e-screenshots.yml` on a pinned `ubuntu-24.04` image
  with `xvfb-run`. The smoke spec is 13/13 green locally.
  Along the way, fixed real bugs the specs surfaced:
  - A first-run onboarding modal that blocked every click on a fresh profile
    (now dismissed via `tests/helpers/onboarding.js`).
  - A cold-start race in `bootstrap()` (`app/src/renderer/main.js`) where the
    one-shot profiles/doctor/models fetch could lose the race against the
    Python backend finishing startup and fail with no retry — only `/health`
    was re-polled — permanently stranding `#profileSelect` empty for the rest
    of the session (silently no-opping Discard). **Fixed**: the bootstrap
    fetches now live in `runBootstrapFetches()`, and the existing 3s
    health-poll timer re-runs them once if any failed and the backend has
    since become reachable, via a `bootstrapNeedsRetry` flag. Verified it
    self-heals within ~3-8s of a racy cold start with no reload needed.
  - **A real, shipped bug in the review overlay**: `app/src/renderer/review-overlay.html`
    has its own hand-rolled `fetchJson`/`postJson` (separate from the shared
    `src/renderer/api/backend.js` the main dashboard uses) that never attached
    an `Authorization` header, even though `window.betterFingers.authToken` is
    available in that window via the shared preload script. Every backend call
    from the review overlay — Read/TTS, Change/Instruct rewrite, Send, Accept —
    was silently 401ing whenever `BETTERFINGERS_AUTH_TOKEN` is set, which
    Electron's main process always sets. This made the entire review overlay
    non-functional for real users, not just in tests. **Fixed**: added the same
    `Authorization: Bearer` header pattern used in `backend.js`. With that one
    fix, `app/tests/review-overlay.spec.js` went from 2/6 to a clean 6/6,
    including the Read/TTS flow — no TTS voice or model download was ever
    actually missing; everything was just failing auth.
  Both specs together: 19/19 green, ~27s full run.
  Remaining for full U1 scope: `review-overlay.spec.js` isn't wired into the
  CI job yet — it passes *locally* because this dev machine happens to already
  have a Gemma 4 12B model + `llama-server` on disk at a legacy install path
  (auto-discovered by `model_manager.py`'s search paths), but a bare CI
  checkout has neither that model nor a TTS voice, so it would fail there on
  provisioning grounds alone. `reg-actions` PR-diffing is also still
  deferred — no baseline screenshots are checked in yet to diff against.

- **U9 — Cross-vendor efficiency (Vulkan/CUDA builds).** Ship Vulkan
  llama-server/whisper.cpp as default with a CUDA variant on NVIDIA detect;
  KV-cache q8_0, prompt caching, llama-swap hot-switching. Needs **native build
  infrastructure and real GPUs** (NVIDIA/AMD/Intel) to build and validate.
  _First step: a build matrix that produces Vulkan + CUDA sidecar binaries; not a
  code-in-this-repo task until binaries exist._

- **U10 — Meetings mode.** Loopback + mic capture → chunked STT → offline
  diarization (pyannote/NeMo) → LLM notes/action items → Library timeline UI. A
  multi-week feature; **pyannote/NeMo are not installed** and diarization needs
  real multi-speaker audio + a GPU to be usable. _First step: prototype loopback
  capture on one OS and a diarization spike behind a feature flag._

- **U11 — Brainstorm mode.** Streaming STT + VAD turn-taking + a
  question-generating LLM loop + a "constellation" UI + export. Large new
  surface; needs streaming infra and a running app to feel out the interaction.
  _First step: a design doc + a VAD turn-taking spike._

- **C3 — Per-app injection profiles.** `get-windows` npm in Electron main →
  active-app context to the sidecar → per-app profile switching; Wayland needs
  per-compositor adapters. Needs the **npm dependency installed** and per-OS
  window APIs (and even then Wayland is best-effort). _First step:
  `npm i get-windows` in `app/`, expose active-window to the sidecar, switch the
  active profile on app change with a graceful default fallback._

- **C5 — Wake word / hands-free.** openWakeWord (a self-trained "hey fingers"
  model) + Silero VAD v6 gating + a hands-free toggle. Needs the **openWakeWord
  dependency + a trained model file**, neither present. _First step: add the dep,
  ship a stock wake model behind a toggle, then train the custom phrase._

- **C12 — MCP client.** An `mcp` SDK client in the sidecar + `mcpServers` config
  + a llama-server tools bridge + per-persona tool allowlist & permission
  prompts. **`python3 -c "import mcp"` fails** — the SDK isn't installed.
  _First step: add `mcp` to `requirements.txt`, then a minimal client that lists
  a configured server's tools behind a settings flag._

---

## Recommended next actions (for a human)

1. **Pick a verifiable environment.** Most of the above unblocks the moment there
   is (a) a machine that can launch the packaged app, and/or (b) a GPU box.
2. **Cheapest high-value wins first:** C3 (per-app profiles) and C5 (wake word)
   are self-contained once their deps are installed; C12 (MCP) is a bounded
   backend feature once `mcp` is available.
3. **Infra track:** U1 (screenshot CI) and U9 (Vulkan/CUDA builds) are CI/build
   tasks, best done together on a provisioned runner.
4. **Big features last:** U10 (meetings) and U11 (brainstorm) each warrant their
   own design doc before code.

Use `docs/MANUAL_QA_CHECKLIST.md` to confirm the 16 shipped items still work
whenever the app is run in a real environment.
