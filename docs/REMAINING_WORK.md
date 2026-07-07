# Remaining work — honest scoping

As of the MASTER_PLAN loop pause. The suite is at **262 passing**. Sixteen
roadmap items are complete or advanced: **C1, C2, C4, C6, C7, C8, C9, C10, C11,
U2, U3, U4, U5, U6, U7, U8** (see the "Implementation progress" log at the top
of `MASTER_PLAN.md` for per-item detail and deferred sub-parts).

The loop paused here because **every remaining item needs something this
environment can't provide** — real GPUs, uninstalled heavy ML dependencies, a
running packaged app, or per-OS window/native APIs. Continuing autonomously
would mean writing code that can't be verified, which the loop is explicitly
directed not to do. Each item below states exactly what's blocking it and the
first concrete step for a human (or a suitably-provisioned environment).

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

- **U1 — Screenshot QA of every page.** Needs a Playwright `_electron` harness, a
  **pinned Linux CI image**, and `reg-actions` for PR diffs, plus stubs for
  tray/native dialogs. Cannot be verified without a running Electron app in CI.
  _First step: add a `playwright.config`, a smoke spec that launches the app and
  screenshots the main view, and a GitHub Actions job on a pinned image._

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
