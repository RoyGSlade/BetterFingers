# BetterFingers — The Design Paradigm

**The single source of truth for what BetterFingers is, what is shipped, and what remains
to reach a finished product.** This document consolidates and supersedes every previous
planning doc (`MASTER_PLAN`, `REMAINING_WORK`, `VOICE_CONTROL_PLAN`, `PERSONA_FOUNDRY_PLAN`,
`PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN`, `ELECTRON_MIGRATION_PLAN`, `BUGFIX_PLAN`,
`REVIEW_FINDINGS_FIXES`, `HANDOFF_REPORT`, `MANUAL_QA_CHECKLIST`, `HARDWARE_GUIDE`,
`MARKETING_PLAN`, and the external product audit of 2026-07). Historical detail lives in
git history; only what defines the product or remains to be done lives here.

Last reconciled against the codebase: **2026-07-09** (main @ `2e24c72`). The cross-test
state leak that made `test_token_concepts.py::Phase2PassThroughTest` fail in the full run
is **fixed** (autouse reset of `server.transcriber`/`tts_engine` in
[`tests/conftest.py`](tests/conftest.py)); the model-free subset that reproduced it now
runs fully green (600 passed). Plus 19+ Playwright e2e tests.

---

## 1. Identity — what this product is

> **A private desktop speech editor that lets you speak messy thoughts, visibly refine
> them, and safely place them anywhere.**

Everything in the app must reinforce one loop:

**activate → speak → transcribe → refine → review → inject → recover when anything fails.**

Every proposed feature is judged by whether it improves exactly one of:

| Dimension | Meaning |
|---|---|
| **Capture** | Getting speech in reliably (hotkeys, controller, wake word, long recordings) |
| **Refinement** | Turning raw speech into usable text (LLM personas, dictionary, commands, macros) |
| **Review** | Seeing and shaping the result before it lands (overlay, TTS read-back, confidence) |
| **Recovery** | Never losing work (raw audio retention, error drafts, retranscribe) |
| **Placement** | Putting text where it belongs (injection, clipboard, per-app behavior) |
| **Recall** | Finding what you said before (searchable history, future semantic search) |

A feature that improves none of these is out of scope until 1.0 ships. The app is
roughly 70% product / 20% laboratory today; the remaining work is the unglamorous
transformation from **impressive** to **dependable**.

### The stabilization rule (binding until the M1 benchmark passes)

> **No new top-level mode ships until the primary dictation loop passes the reliability
> benchmark in §6.** Meetings mode, brainstorm mode, MCP tool execution, further cloning
> polish, and large visual redesigns are all explicitly parked (§14).

### Positioning (from the marketing plan, kept as product constraints)

- **Private by design** — 100% local STT/LLM/TTS; only model downloads touch the network;
  the privacy dashboard proves it.
- **Free forever** — MIT licensed (LICENSE is in-repo), donation-supported, no paywall.
- **Works everywhere you do** — any app, hotkey or controller, mid-game.
- **Smart, not literal** — personas clean up what you say instead of dumping raw dictation.
- A **Source Arcanum** project (studio brand carries to future apps).
- Honest platform claims: Windows + Linux; macOS out of scope until explicitly funded.

---

## 2. Architecture spine (shipped, keep)

```
Electron (app/)                          Python sidecar (repo root)
├─ main/  windows, tray, overlays,       ├─ server.py        FastAPI, ~60 routes + WS
│         global hotkeys (uiohook-napi), ├─ transcriber      faster-whisper (+confidence)
│         sidecar spawn/health/restart,  ├─ llm_engine.py    llama-server client, personas,
│         clipboard + injection IPC      │                   chunking, stitching, foundry
├─ preload/  auth token + backendOrigin  ├─ tts_engine.py    Kokoro (+blend/modulation)
│            bridge                      ├─ recorder / audio_gate / hotkey_manager
└─ renderer/ dashboard (4 tabs today),   ├─ dictionary / macros / dictation_commands
   overlay.html, review-overlay.html     ├─ voice_commands / voice_edit_commands /
                                         │  utterance_history / voice_preview
   REST + WebSocket boundary             ├─ wake_word.py (service shell + fake detector)
   (Bearer token, schema_version         ├─ history_store (SQLite FTS5) / recordings
    handshake)                           ├─ model_manager / model_recommender /
                                         │  hardware_report / voice_presets / voice_clone_qa
                                         └─ mcp_client.py (read-only, feature-flagged)
```

Separation of concerns is non-negotiable: Electron owns windows/tray/overlays/hotkeys/
clipboard/injection; Python owns STT/LLM/TTS/models/recordings/personas/privacy/history.
The REST+WS boundary stays inspectable and version-gated (`schema_version` handshake gates
the renderer).

Packaging: electron-builder (NSIS / AppImage / DMG targets defined), PyInstaller backend
build stage (`app/scripts/build-backend.js`), pinned-Linux CI screenshot job
(`.github/workflows/e2e-screenshots.yml`), installer publish on tags
(`.github/workflows/build-installer.yml`).

---

## 3. What is shipped and verified (do not re-plan; regression-guard it)

Condensed record of completed work. Every item below has tests and landed on `main`.

**Electron migration (complete).** Legacy tkinter/Flet stack deleted (~14k lines). Sidecar
hardening: unified config, version handshake, post-startup health monitor with bounded
auto-restart + `crashed` state, log retention, status banner. Push-to-talk via uiohook-napi
(key-down/key-up, auto-repeat suppression, Wayland degrades to toggle + honest capability
reporting). Injection backend matrix (pydirectinput → xdotool → wtype/ydotool → paste)
surfaced via `/capabilities`. Real `/models/unload`, XDG-aware export, pactl audio ducking
on Linux, platform-marked requirements. First-run onboarding (consent-gated, focus-trapped,
hardware-aware model recommendation step). Tray/dashboard lifecycle recoverable.

**Core dictation stack.** Personal dictionary (hotwords bias + difflib post-correction +
auto-learn from edits). Dictation formatting commands ("new paragraph", spoken punctuation,
casing). Voice macros (trigger→expansion). Confidence surfaced end-to-end (badge on drafts,
in overlay payloads). Never-lose-audio: raw WAV + sidecar JSON per utterance, pruned at 50,
recovery panel with retranscribe. Searchable history: SQLite FTS5 archive with retention
pruning (5000), search UI. Privacy dashboard: `GET /privacy` reports every touchpoint;
`/privacy/wipe` verifiably clears drafts, history DB, and on-disk recordings. Latency HUD:
per-stage timings (`stt_ms`, `llm_ms`, `post_ms`) via `/metrics`.

**Long-recording robustness (Phases 1–7).** Token concepts split
(`max_completion_tokens` 512–4096 / `long_draft_warning_words`); completion cap reaches
initial dictation; sentence/paragraph-aware chunking with overlap-as-context; chunk
progress statuses through engine→server→renderer/overlay/tray; optional seam-only stitch
pass (failure-safe); persona v2 fields drive inference (temperature override, format
rules, few-shot turns ≤5, per-persona token/chunk overrides); persona builder robustness
UI (output policy, safety mode, lint, test panel, few-shot editor).

**Personas.** Schema v2 (rich dict, `schema_version: 2`, defensive normalization,
legacy migration, partial-merge upserts) + editor with Advanced block that preserves
existing prompts. Persona Foundry (U12): deterministic 12-question interview with
vagueness pushback + contract-contradiction checks, LLM compile to prompt + character
card (deterministic fallbacks, never hard-fails), 7-category stress suite, save through
the standard route. 61 dedicated tests; verified end-to-end live.

**Voice Studio.** Kokoro voice blending wired to real style tensors (`blend_many`,
cache-keyed). Modulation DSP (pitch/energy/warmth/brightness, pause styles). Named voice
presets with API + UI. Persona-aware voice resolution (preset XOR inline, tested).
Clone QA gate (`voice_clone_qa.py`: duration/noise/clipping checks, hard consent
requirement, provenance `.meta.json` sidecar) — **no actual cloning synthesis engine is
installed** (see §11).

**Voice control (scopes 1–3 + shells).** `utterance_history.py` ring buffer;
`voice_commands.py` intent parser (context-gated, confidence-thresholded, hardcoded
confirmation floor for destructive actions, emergency-stop exempt from gating);
`voice_edit_commands.py` ("scratch that", replace X with Y, structural commands, literal
mode) incl. `apply_inline_edits`; `voice_preview.py` test-panel combinator; server pipeline
wiring (scratch-that early-exit, `editing_commands`/`app_commands` profile flags);
`wake_word.py` service shell + `FakeWakeDetector`; missed-release watchdog timer in
`hotkey_manager.py`.

**Model management.** Hardware tier classifier (cpu-only/igpu/dgpu-8g/dgpu-12g+),
model recommender with RAM-fit guarantees + informational alternatives catalog
(never silently downloadable), Gemma 4 family in the catalog, WER scoring core (`wer.py`,
stdlib Levenshtein) + golden-audio fixture format (§13).

**Quality infrastructure.** 639 Python tests; Playwright Electron suites (smoke walk +
review-overlay flows) that found real shipped bugs (review-overlay 401s, bootstrap
cold-start race — both fixed); packaged-app screenshot CI on pinned ubuntu-24.04;
all 22 findings of the post-merge gap review closed (privacy wipe completeness, persona
prompt preservation, window lifecycle, history retention, deepcopy hardening, dead deps
removed, race guards, HTML escaping, corrupt-store `.corrupt` quarantine, etc.).

**Known intentional behaviors (not bugs):**
- Initial dictation cleanup uses the **True Janitor** preset regardless of the profile's
  `current_preset` (wiring the active preset into dictation is M5 work — behavior change).
- Persona `model_hint` is stored metadata only; no model routing yet (M5).
- `load_personas*()` return live cache objects (hot path); callers treat as read-only.

---

## 4. Milestone map to 1.0

Order is binding. M0–M2 make the product **trustworthy**; M3–M5 make it **complete**;
M6–M7 make it **safe to extend**; M8+ is post-1.0.

| Milestone | Theme | Gate to advance |
|---|---|---|
| **M0** | Release baseline & repo front door | Clean-machine reproducible build; README/SECURITY exist |
| **M1** | Core-loop reliability + safety rails | Reliability benchmark (§6) passes |
| **M2** | Injection compatibility | Versioned matrix for the top-10 target apps |
| **M3** | Voice control completion | Wake→dictate→auto-stop→confirm loop, off by default, tested |
| **M4** | Data lifecycle & at-rest trust | DataRegistry drives privacy report/wipe/export |
| **M5** | Voice/persona/TTS completion | Deferred U5/U6/U7/U8 sub-parts closed or explicitly cut |
| **M6** | Architecture decomposition | server.py/main.js split; input/audio/model coordinators |
| **M7** | Automation & platform (MCP invoke, C3, U9) | Default-deny MCP writes; capability matrix published |
| **M8** | Knowledge features (U10/U11, Threads/Echo) | Post-1.0 only |
| **Launch** | Signed alpha → public release | §15 checklist |

Operational note: this file is the roadmap, but work items should be mirrored into GitHub
issues with milestone labels (`core-loop`, `data-safety`, `platform/*`, `security`,
`needs-hardware`, `needs-manual-qa`) — markdown plans drift; issues have owners and state.

---

## 5. M0 — Release baseline & repository front door

**Why first:** an unpinned build of an app combining audio drivers, native hooks,
PyInstaller, Electron, CTranslate2, ONNX, and GPU runtimes is a ritual sacrifice to the
dependency gods. A tagged release must be reproducibly buildable from a clean runner using
only committed configuration plus documented model downloads.

- [ ] **Two-layer dependency control.** Human-maintained ranges (`requirements.in`,
      `package.json`) + machine-generated exact locks (`requirements-linux.lock`,
      `requirements-win.lock`; committed `package-lock.json`). Currently `requirements.txt`
      is fully unpinned and Electron deps use caret ranges.
- [ ] **Pin the toolchain.** Python, Node, npm, PyInstaller, electron-builder, Electron
      itself; sidecar model/runtime versions; GitHub Actions by commit SHA.
- [ ] **Root `README.md`** (currently missing): one-paragraph description, 30-second
      workflow, feature matrix, supported OSes, hardware tiers (§12), privacy model,
      install steps, dev setup (§13), architecture diagram, known limitations, roadmap
      boundaries, license, screenshots, demo GIF, "A Source Arcanum project".
- [ ] **`SECURITY.md`** + a security-issue reporting channel.
- [ ] **`.github/FUNDING.yml`** (GitHub Sponsors + Ko-fi) — free-forever is the moat;
      the donate button is the sustainability model.
- [ ] **Release integrity:** SHA-256 checksums for artifacts; SBOM (CycloneDX or SPDX);
      GitHub artifact attestations/provenance.
- [ ] **Scanning:** CodeQL, Dependabot or Renovate, secret scanning.
- [ ] **Windows build verification end-to-end** on a real Windows box
      (`build-backend.js` → `npm run dist:win`); then Authenticode signing.
      (macOS signing/notarization deferred with the platform.)
- [ ] **Baseline measurements** recorded per tier: CPU, RAM, VRAM, startup time,
      end-to-end dictation latency. Every later perf claim is judged against these.

---

## 6. M1 — Core-loop reliability + safety rails

### 6.1 The reliability benchmark (the gate everything waits on)

Automate what can be automated; script the manual remainder. Track pass/fail per run:

- 100 consecutive dictations without unrecoverable failure.
- 50 app restarts with backend startup recovery (no stranded UI, profile select populated).
- Long-recording success at 5 / 15 / 30 / 60 minutes.
- Audio-device unplug/replug recovery; sleep/resume recovery.
- Model crash → restart recovery (bounded auto-restart already exists; verify under load).
- Clipboard restoration correctness after injection.
- No lost audio after interrupted processing (kill the sidecar mid-pipeline; recover).
- Injection success across the M2 top-10 matrix.

The core-loop suite (start → record → stop → transcribe → refine → review → edit → read
aloud → inject → restore clipboard → save history → recover from backend restart) runs
repeatedly, not once.

### 6.2 Finish the started safety rails (small, code-verified gaps)

- [x] **Missed-release watchdog** — *done end-to-end* (was mismarked pending). Timer +
      `on_watchdog_timeout_callback` in `hotkey_manager.py`; `server.py` passes
      `_broadcast_watchdog_timeout` which broadcasts the `watchdog_timeout_warning` status
      ("Recording stopped after max duration."); the renderer now surfaces it as a warning
      toast. Backend covered by `test_server_amplitude_watchdog.py` +
      `test_hotkey_manager_tts.py`.
- [x] **Auto-stop after trailing silence** — *done*. Pure
      `audio_gate.TrailingSilenceDetector` (only counts silence after speech; a louder
      chunk resets it, so mid-sentence pauses don't trip it; fires once after
      `min_recording_ms` + `silence_ms`). The recorder builds it per-recording from the
      profile and feeds per-chunk rms/peak on its worker thread, firing
      `on_auto_stop("trailing_silence")` on a fresh thread (never stops from the worker
      that would join itself); `hotkey_manager._on_auto_stop` routes it through the normal
      idempotent stop path, so the reason lands in recording metadata via the existing
      `stop_reason` plumbing. Profile fields `auto_stop_after_silence_enabled` (default
      false), `auto_stop_silence_ms` (900, 250–5000), `auto_stop_min_recording_ms`
      (700, 0–10000); silence thresholds reuse the no-audio gate values unless the optional
      `auto_stop_rms_threshold`/`auto_stop_peak_threshold` overrides are set. Settings UI +
      client/server validation. Covered by `tests/test_auto_stop_silence.py`. Off by
      default; end-to-end hands-free behavior needs a live mic, so verified by unit tests.
- [x] **Confidence-gated send policy** — *done*. Profile fields
      `confidence_force_review_enabled` (default true), `confidence_force_review_below`
      (0.55), `confidence_auto_send_above` (0.85) in `utils.py` (sanitized + validated).
      Pure `server.evaluate_confidence_send_policy()` returns
      `{auto_send_ok, force_review, reason}`: missing/low confidence → review; long draft →
      review; no-audio gate fired → review; auto-send only when high-confidence + short.
      Stamped onto every draft by `update_draft_review_fields` and included in the
      `preview_ready` payload; the review overlay only auto-sends on accept when
      `auto_send_ok` (else shows the withhold reason). Settings UI added (enable toggle +
      two thresholds with client + server validation). Covered by
      `tests/test_confidence_send_policy.py`. Completes C4's deferred silent-inject
      threshold. Not browser-preview-verifiable end-to-end (needs a real ASR-confidence
      draft + native send), so verified by unit tests + `node --check`.
- [ ] **Review overlay draft summary** (Phase 8 remnant): token/word count summary on the
      final draft in `review-overlay.html`; optional heartbeat so a long non-chunked LLM
      call keeps status fresh past ~8s.
- [x] **Cross-test state leak fixed** — `server.transcriber`/`tts_engine` module globals
      leaked across tests, so `test_token_concepts.py::Phase2PassThroughTest` failed only in
      the full run. An autouse fixture in `tests/conftest.py` now resets both around every
      test (centralizing what four test files already did by hand). Verified: the model-free
      subset that reproduced it is green (600 passed).

### 6.3 Cancellation, queueing, and job management (product-level)

Long recordings, TTS, cloning, Whisper, LLM, and model downloads compete for VRAM/RAM/
disk/CPU/audio devices. Build a central job manager:

```
queued → loading → capturing → transcribing → refining → stitching →
review-ready → injecting → completed | failed | cancelled
```

Every job: stable ID, progress, cancellation, recoverable artifacts, resource estimate,
user-visible status, clear retry semantics. Explicit answers required for: cancel STT;
cancel LLM cleanup without losing raw transcript; second dictation while first refines;
TTS during Whisper GPU use; model switch unloads predecessor; low-disk behavior; queued
long recordings; abandoned-task cleanup. Model-download cancel + concurrent LLM/Whisper
download progress UI (an old migration-plan leftover) fold in here.

---

## 7. M2 — Injection compatibility harness

"Works anywhere" is the product promise and the most OS-fragile claim in it. Build a
harness, not tribal memory: for each target record app/version, OS, injection method,
plain-text / multiline / Unicode / punctuation success, selection replacement, clipboard
restoration, focus-loss behavior, elevated-window behavior, average latency.

Starting matrix (versioned in-repo, updated per release): Chrome text input, Google Docs,
Outlook, Word, VS Code, Discord, Slack, Notepad, a terminal, one EHR-like web form, one
remote-desktop environment. Known failure surfaces to probe: elevated windows, secure
fields, browser/Electron editors, games, RDP/Citrix, Wayland, full-screen apps, clipboard
managers, IMEs, rich-text editors, apps that modify selection during injection.

Publish results as the per-platform capability matrix (§10, M7) — support promises must
not outrun reality.

---

## 8. M3 — Voice control completion (wake → speak → stop → confirm)

The backend logic layer is shipped (§3). What remains is the service/UI/dependency layer:

- [ ] **Wake-word MVP server integration** (spec'd, not wired): `/runtime/wake-word/status`
      + `/start` + `/stop` routes; profile fields `wake_word_enabled` (default **false**),
      `wake_word_engine` ("openwakeword"), `wake_word_model_path`, `wake_word_threshold`
      (0.55), `wake_word_cooldown_ms` (2500), `wake_word_requires_vad` (true). Detection
      calls `HotkeyManager.request_start(reason="wake_word")`; disabling fully releases
      the mic stream; listener errors surface in `/runtime/status` + dashboard.
- [ ] **Real openWakeWord integration** (dependency not installed) behind the existing
      adapter interface; self-trained "hey fingers" model (pre-trained models are
      CC-BY-NC — train our own); Silero VAD gating.
- [ ] **Wake-word test harness**: `tools/wakeword_probe.py` (scores/detections/cooldown,
      JSONL logs), `tests/wake_fixtures/{positive,negative}/`, fixture-based
      false-accept/false-reject tests with the fake detector in CI; real-model tests
      opt-in. **A custom wake phrase is not "done" without fixture-based FA/FR testing.**
- [ ] **Voice Control settings UI + review-overlay wiring** (scope 4 frontend — zero of it
      exists in `index.html` today): wake toggle/sensitivity/cooldown, auto-stop fields,
      `app_commands_enabled`, editing-commands toggle, confirmation policy, command prefix,
      and a **test panel** that runs `voice_commands`/`voice_edit_commands` against typed
      or spoken text showing the resolved intent *without executing it* (`voice_preview.py`
      exists for exactly this). Overlay badges: idle / listening / recording /
      `Command: <action>` / `Needs confirmation — say "confirm" or "cancel"` riding the
      existing `broadcast_status_threadsafe` channel (`command_detected`,
      `command_needs_confirmation`).
- [ ] **Training/calibration (Phase 2, after real-world use):** command-phrase recording +
      `observed_transcripts` alias learning; wake-phrase calibration (5–20 samples +
      negatives → personalized threshold + reliable/noisy verdict); optional local
      embedding verifier; Voice Training panel (train, sensitivity test, false-trigger
      log, delete training data, export/import profile).

**Safety invariants (hardcoded, not configurable down):** `send`, `delete_history`, and
anything destructive always require confirmation; training improves recognition but never
lowers the confirmation floor; `emergency_stop` resolves regardless of context gating or
confidence; no silent execution while the app is hidden; an unmistakable audible/visual
armed state whenever always-listening is active; wake + VAD gating; replay
protection/cooldowns; hardware/keyboard kill switch. Naming: `app_commands_enabled`
(app-control layer) is distinct from `voice_commands_enabled` (formatting layer) —
toggling one must never toggle the other.

---

## 9. M4 — Data lifecycle, at-rest protection, log hygiene

### 9.1 DataRegistry (one registry, one wipe path, one export path)

The privacy-wipe bug (transcripts + WAVs survived "wipe my data" until fixed) is what
scattered storage logic produces. Create a single `DataRegistry` service that knows every
persistent category — recordings, raw transcripts, refined drafts, history index,
personas, dictionaries, macros, voices, model metadata, logs, diagnostics, screenshots,
temporary audio, MCP configuration — and for each defines: storage path, retention rule,
encryption status, included-in-export, included-in-wipe, included-in-diagnostics, and
may-contain-sensitive-text. **Generate the privacy report from the registry** instead of
maintaining parallel path lists. Precise answers required for: when raw audio is saved/
deleted; what survives successful injection / crash / rejected draft; whether intermediate
LLM chunks persist; whether waveform previews cache; whether deleting a persona deletes
its voice; whether history stores raw, refined, or both; what private mode changes;
whether transcripts can reach crash reports; whether MCP execution logs user text.

### 9.2 At-rest protection

Local-first ≠ secure-at-rest; recordings and transcripts may be the most sensitive files
on a machine (patient info, legal work, journals). Do **not** invent cryptography:

- Document reliance on full-disk encryption as the default posture.
- Optional encrypted vault for history + recordings, keyed via OS key storage
  (Windows Credential Manager/DPAPI, macOS Keychain, Linux Secret Service); keys separate
  from content.
- "Do not persist raw audio" mode.
- Configurable retention: never / until-accepted / 24 h / 7 days / manual-only.
- Do **not** position the app as HIPAA-ready merely because it runs locally.

### 9.3 Logging and diagnostics hygiene

Dictated text, prompts, filenames, MCP arguments, and clone metadata can leak into Python
tracebacks, Electron console, sidecar logs, CI artifacts, screenshot artifacts, and
diagnostic exports. Audit all of them; redact user content by default; emit injection
*audit events* without storing the injected text; make diagnostics exports list exactly
what they contain before the user sends them anywhere.

### 9.4 Model & binary provenance (supply-chain boundary)

Every managed model/runtime gets a manifest: stable ID, source repo, revision/commit,
file hashes, expected sizes, license, compatibility requirements, install date,
verification status, and the user-visible actual runtime path. Verify downloads by hash.
Label **managed vs. externally discovered** in the UI — the app currently auto-discovers
legacy-path Gemma/llama-server binaries, which must never be silently treated as trusted
managed assets. Track model licenses in-repo (`LICENSES-MODELS.md`) and re-check weight
licenses at integration time (known: Piper went GPL — rejected; pre-trained openWakeWord
models are CC-BY-NC — self-train instead).

### 9.5 Config migration discipline

Every persisted store (profiles, personas, history, models, macros, dictionaries,
settings): `schema_version`, idempotent migrations, backup before migration, atomic
writes, corruption recovery (the `.corrupt` quarantine pattern is already shipped for
dictionary/macros — extend everywhere), downgrade behavior, and tests from historical
fixture versions.

---

## 10. M5–M7 — Completion, decomposition, platform

### M5 — Voice / persona / TTS completion (close or cut every deferred sub-part)

- [ ] **TTS audio DSP remainder (U5):** streaming playback, BS.1770/RMS loudness
      normalization, chunk crossfade (utterance LRU cache exists). Needs tuning by ear.
- [ ] **Cloning (U6):** pick and integrate an actual synthesis engine — candidate:
      kokoclone (Apache-2.0, builds on Kokoro-ONNX; pulls torch+torchaudio — a deliberate
      dependency-weight decision, not a silent one). `DELETE`/export routes for cloned
      voices. Native (non-ONNX) backend blending (currently falls back to base voice,
      logged). **Consent + abuse controls carried forward:** explicit consent
      acknowledgement (shipped), cloned-voice labels + provenance metadata (shipped),
      immediate deletion (route missing — required), never upload samples, warn against
      cloning third parties, consider an optional audible disclosure marker for exports.
- [ ] **Persona editor polish (U7):** live prompt preview; full voice base/blend/speed +
      few-shot raw→out list UI inside the persona editor (Voice Studio schema is proven);
      `dictionary_scope` control.
- [ ] **Wire the active preset into dictation** (today: True Janitor hardcoded by design)
      and **model routing from `model_hint`** (gated so it never triggers surprise
      downloads).
- [ ] **Model catalog remainder (U8):** verified GGUF URLs for FunctionGemma-270M /
      Qwen3.5-2B; real non-Whisper STT integration (Moonshine / Parakeet-ONNX) behind the
      transcriber interface. Golden-audio WER gate (§13) must accept each model before it
      becomes a default.
- [ ] **Golden audio suite completion (C9):** check in real `.wav`/`.txt` fixtures +
      `test_golden_audio.py` runner that skips without a model; CI job per configured STT
      model.
- [ ] **Screenshot QA completion (U1):** wire `review-overlay.spec.js` into CI (needs
      provisioned model/TTS in the runner); check in baseline screenshots; reg-actions
      PR diffing.

### M6 — Architecture decomposition (extract one domain at a time, tests stay green)

- [ ] **`server.py` split** (routes reference line numbers >2,900 — an architectural
      warning): `backend/api/routes/{dictation,history,privacy,personas,voices,models,
      commands,mcp}.py`; `services/{dictation_pipeline,retention,injection_context,
      voice_service,model_service}.py`; `stores/`, `domain/`, `runtime/`. Thin handlers;
      pipeline behavior in FastAPI-independent services. Start with personas+voices, then
      history+recordings, then commands+macros, then models.
- [ ] **`renderer/main.js` split** the same way (bootstrap, personas, models, settings,
      stream/draft rendering as modules; no framework migration — vanilla + web
      components per card type is enough at this size).
- [ ] **`InputCoordinator`:** the dependency set includes `keyboard`, uiohook-napi,
      `pygame`, and Electron shortcuts. Centralize so duplicate PTT events, missed key-ups
      after focus changes, hotkeys firing during rebind, gamepad+keyboard double-starts,
      and hooks surviving shutdown are structurally impossible.
- [ ] **Audio device ownership manager:** STT capture, TTS playback, wake monitoring, and
      preview must negotiate one owner per device; unplug/replug and default-device-change
      recovery live here.
- [ ] **Model resource manager:** loaded models, RAM/VRAM estimates, last-used, pinned vs.
      evictable, current pipeline needs, CPU fallbacks, load-requires-unload decisions.
      Without it, "local-first" becomes "locally discover what an OOM crash looks like."

### M7 — Automation & platform

- [ ] **MCP tool invocation (C12 remainder)** — read-only client is shipped and stays the
      posture until this lands deliberately: llama-server `tools` bridge, per-persona tool
      allowlist (persona schema gains `tools: []`), permission-prompt UX in the review
      surface, visible command transcripts, **default-deny for write actions**, per-tool
      allowlists, confirmation for destructive calls. Voice commands + MCP together create
      a path from ambient sound to tool execution — all §8 safety invariants apply
      compounded.
- [ ] **Per-app injection profiles (C3):** `get-windows` in Electron main → active-app
      context to sidecar → per-app profile switching; Wayland via per-compositor adapters
      (kdotool/KDE, D-Bus extension/GNOME, wlr-foreign-toplevel/Sway) with graceful
      default-profile fallback. Nobody fully solves Wayland — don't promise parity.
- [ ] **Cross-vendor GPU builds (U9):** build matrix producing Vulkan llama-server/
      whisper.cpp as universal default + CUDA variant on NVIDIA detect; KV-cache q8_0;
      llama-server prompt/prefix caching (big win for persistent persona prompts);
      llama-swap hot-switching. Skip speculative decoding below ~8B targets. Needs real
      GPU build infrastructure — not a code-in-this-repo task until binaries exist.
- [ ] **electron-updater** rollout channel (NSIS differential + AppImage) with update
      signature verification.
- [ ] **Published capability matrix** (replaces binary supported/unsupported claims):

| Capability | Windows | Linux X11 | Linux Wayland | macOS |
|---|---:|---:|---:|---:|
| Global PTT | Stable | Stable | Limited (portal/toggle) | Needs permission (unsupported today) |
| Text injection | Stable | Stable | Best effort | Needs accessibility (unsupported today) |
| Audio ducking | Stable | PipeWire/Pulse | PipeWire/Pulse | TBD |
| Gamepad | Stable | Tested | Tested | TBD |
| Active-app profile | Planned (M7) | Planned (M7) | Limited | Planned |
| Wake word | M3 | M3 | M3 | TBD |

---

## 11. UI paradigm — "Speech is material" (design north star)

Current state: 4-tab renderer (Dashboard / Settings / Models / Diagnostics) with the
review overlay and status overlay. The overhaul below is the committed direction; it lands
**incrementally during M5–M6** (design tokens → status rail → Stream → three-space
navigation), each view locked by screenshot QA as it lands. It is not a prerequisite for
1.0 reliability gates.

One idea drives it: **everything you say becomes a visible, solid, manipulable object.**

- **The Stream:** a chronological feed of utterance cards; each card shows raw transcript
  morphing into refined text, carries its audio (replayable), confidence, destination app,
  and actions (send / rewrite / speak / pin / macro-ify). Confidence is *rendered*: solid
  ink for high-confidence words, translucent + soft underline for low — corrections feed
  the dictionary and the user watches the app learn. The recovery bin is just the Stream's
  "unprocessed" filter.
- **Three spaces + a rail:** **Talk** (Stream + live mic state, the 90% view), **Library**
  (history search; later Meetings/Brainstorms), **Studio** (Personas & Voices, Models &
  Hardware, Macros, Tools/MCP, Privacy). Persistent bottom **status rail**: mic level,
  loaded models w/ RAM-VRAM gauge, active persona, target app, latency readout — every
  piece of hidden state permanently glanceable, click-to-jump.
- **Design language "solid":** tactile not glassy; strong grotesque for UI + serif for
  transcript ink; hard edges, real shadows, springy 120–200 ms motion; dark "desk" theme
  default + paper-light; three optional earcons (record start / refined / sent); calm
  breathing waveform ring while recording. Plain CSS formalized into `tokens.css`
  (color/space/type/motion/elevation) — **no framework migration**.
- **Accessibility as identity:** full keyboard nav, visible focus, reduced motion,
  ≥4.5:1 contrast, and complete voice operability — the app itself drivable hands-free.

**Persona paradigm (shipped schema, restated):** a persona is *a way of speaking*, the
app's central object — prompt, temperature, few-shot, voice (preset or inline
blend/modulation), format rules, dictionary scope, output policy, safety mode, per-persona
token/chunk caps, `persona_card`, future `tools` allowlist, `model_hint`. Foundry is the
guided path; the manual wizard is the expert path; both save through one route.

---

## 12. Hardware tiers (user-facing guidance)

| Tier | CPU | RAM | GPU | Default models |
|---|---|---|---|---|
| Minimum | 6c/12t | 16 GB | none (CPU-only supported) | Gemma 4B Q4, Whisper `base.en` |
| Recommended | 8c/16t | 32 GB | RTX 3060 12 GB class | Gemma 4B Q6/Q8, Whisper `small/medium.en` |
| High-perf | 12c+ | 64 GB | RTX 4080/4090 class | Gemma 12B variants, Whisper `large-v3` |

Every default must pass on the low-end tier (floor stack: small-model LLM + Kokoro +
`base.en`); bigger models are opt-in through the recommender's tradeoff UI. Disable
keep-loaded on low-memory systems. `tools/performance_benchmark.py` produces machine-local
measurements before selecting larger models. The in-app tier classifier
(`hardware_report.py`) + recommender (`model_recommender.py`) are the runtime versions of
this table — this table changes only when they do.

---

## 13. Development, testing, and QA

### Dev setup (Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
cd app && npm install && npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

`BETTERFINGERS_PYTHON` overrides the sidecar Python (falls back to platform default with a
warning). The shell starts the FastAPI backend on port 8000 (`BETTERFINGERS_HOST`/`PORT`
env respected end-to-end). Linux llama-server lives at
`.betterfingers/llama-server/bin/llama-server` — provision with
`python tools/setup_linux_llama_server.py --from /path/to/llama-server` (or
`--source .betterfingers/llama.cpp`, `--cmake-arg=-DGGML_CUDA=ON` for CUDA). Overrides:
`BETTERFINGERS_LLAMA_SERVER`, `BETTERFINGERS_MODEL_PATH`.

### Automated gates (every session)

- `python3 -m pytest -q` — full Python suite green (639 tests as of this writing).
- `cd app && npx playwright test` — 19+ e2e (review-overlay spec needs a local LLM +
  llama-server; close any running instance first — single-instance lock).
- `node --check` on touched renderer JS.
- Golden audio fixtures: `tests/golden_audio/<name>.wav` (16 kHz mono PCM) +
  `<name>.txt` (natural reference; `compare_transcripts` normalizes case/punct/space);
  runner asserts WER ≤ per-model threshold, skips gracefully with no model. *(Fixtures +
  runner are M5 work; the format is fixed now.)*

### Manual QA — the human-senses pass (~15 min, priority order)

1. **Review overlay end-to-end:** dictate → Read (TTS audibly plays) → Change with a
   spoken instruction (rewrite lands) → Send/Accept (text injects into a real app).
2. **Cold-start resilience:** fresh boot, profile dropdown populates within ~10 s, no
   manual reload.
3. **Full dictation round-trip** into a real app (record → draft → correction → inject).
4. **PTT while unfocused** (hold-to-talk from another app / tray).
5. **TTS normalization by ear** ("$5", "Dr.", a URL — natural, not character-by-character).

Extended per-feature checks (run when the area changes): onboarding gates (consent
checkbox blocks Next, Esc blocked, focus trap, decline quits); hardware tier + recommender
sanity (`/hardware/tier`, `/models/recommend`, alternatives never downloadable); persona
v2 editing (existing prompt preserved on reopen, partial-merge keeps temperature, 400 on
bad temperature, delete clears all fields, `schema_version: 2` on disk); full Foundry
walkthrough (vague answer → one pushback; expand+preserve-length → contradiction re-ask;
3-example minimum enforced; stress suite renders 7 cards; character card + reliability
score; saved persona appears everywhere and actually drives dictation); dictionary
correction applies + persists; formatting commands fire only when enabled; macros expand
whole-phrase only and survive restart; corrupted `dictionary.json`/`macros.json` →
`.corrupt` quarantine + clean start; recovery card re-runs failed audio; `/privacy` wipe
clears recordings+drafts+history; FTS search survives restart; latency HUD shows
STT/post/LLM rows; blend/modulated voices play; tray reopen after dashboard close; second
instance focuses the first; quit leaves no orphaned `server.py`; hidden window pauses
polling; error text with `<`/`&` renders as text, not HTML.

---

## 14. Explicitly parked (do not build before the M1 gate passes)

Meetings mode (U10: loopback+mic capture, offline diarization via pyannote/NeMo, notes/
action items, Library timeline). Brainstorm mode (U11: streaming STT, VAD turn-taking,
question-generating loop, constellation UI, `project_generator.py` export). Threads +
Echo cards. sqlite-vec semantic search. Full MCP write automation beyond M7's gated core.
Additional command modes. Large visual redesigns beyond §11's incremental path. More
voice-cloning polish beyond M5's engine integration. Each of these increases the number of
ways the app can surprise a user while holding their clipboard, microphone, and unfinished
thoughts. They return to the table one at a time, each with its own design doc, after the
reliability benchmark holds.

---

## 15. Launch plan (condensed from the marketing plan; execute at first public alpha)

**Assets before launch:** 15-second demo GIF (voice → clean text in a real app; top of
README); 60–90 s demo video (everyday dictation + in-game chat — over-invest here);
marketing README; screenshots (dashboard, privacy panel, persona picker); FUNDING.yml +
Ko-fi (+ optional itch.io pay-what-you-want); Source Arcanum Discord (studio-level,
channels per app) + one-page site + mailing list/announce channel; launch copy written
natively per platform; a few early testers seeded for honest day-one comments.

**Sequence (stagger, don't blast):** Show HN (candid architecture + limitations) →
r/LocalLLaMA + r/selfhosted (technical tone, lead with the privacy dashboard) → Product
Hunt → gaming communities (the in-game clip; casual tone; respect each sub's self-promo
rules) → accessibility/RSI communities (empathetic, free-forever, no medical overclaiming)
→ Lemmy/X/Bluesky + AlternativeTo + awesome-lists. Post-launch: reply to everything, ship
one visible fast-follow inside two weeks, pitch 3–5 local-AI/accessibility creators.

**Narrative:** lead *why it exists* with privacy + accessibility; lead *demos* with the
gamer angle. **Donations framing:** "Free forever. Donations fund model testing, hardware,
and development." One link in README + About; no in-app prompts, ever. **Honest caveats
in every post:** no macOS, solo maintainer, local LLM resource footprint (point at the
tier recommender).

**Metrics that matter:** demo views, stars, release downloads, Discord weekly actives,
median first-response time on issues, recurring sponsors. The real win is a retained
community that follows Source Arcanum to app #2.

---

## 16. The finish line

BetterFingers 1.0 is done when:

1. A tagged release builds reproducibly from a clean runner, signed, checksummed, with
   SBOM and provenance (M0).
2. The reliability benchmark passes and keeps passing in CI + scheduled manual runs (M1).
3. The injection matrix shows green for the top-10 apps on Windows + X11 with honest
   Wayland labeling (M2).
4. Wake→speak→auto-stop→confirm works, off by default, with fixture-tested FA/FR rates
   (M3).
5. The privacy report is generated from the DataRegistry, retention is configurable, and
   a wipe verifiably leaves nothing behind (M4).
6. Every deferred sub-part in M5 is shipped or has a written "cut" decision in this file.
7. `server.py` and `main.js` no longer exist as monoliths; input, audio, and model
   ownership each have exactly one coordinator (M6).
8. MCP writes are default-deny with per-persona allowlists and visible confirmations (M7).
9. A stranger can go from the README to a working, private, first dictation in under ten
   minutes — and the app never surprises them while holding their clipboard, microphone,
   or unfinished thoughts.

The app has enough features. Ship the trustworthy version of the ones it has.
