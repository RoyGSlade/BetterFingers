# BetterFingers — The Design Paradigm

**The single source of truth for what BetterFingers is, what is shipped, and what remains
to reach a finished product.** This document consolidates and supersedes every previous
planning doc (`MASTER_PLAN`, `REMAINING_WORK`, `VOICE_CONTROL_PLAN`, `PERSONA_FOUNDRY_PLAN`,
`PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN`, `ELECTRON_MIGRATION_PLAN`, `BUGFIX_PLAN`,
`REVIEW_FINDINGS_FIXES`, `HANDOFF_REPORT`, `MANUAL_QA_CHECKLIST`, `HARDWARE_GUIDE`,
`MARKETING_PLAN`, and the external product audit of 2026-07). Historical detail lives in
git history; only what defines the product or remains to be done lives here.

Last reconciled against the codebase: **2026-07-14** (main @ `0770f9a`; this reconciliation
was done from the `fix/review-blockers` branch, which several sessions are landing P0/P1
review fixes onto concurrently — see the "in flight" note below). The cross-test state leak
that made `test_token_concepts.py::Phase2PassThroughTest` fail in the full run is **fixed**
(autouse reset of `server.transcriber`/`tts_engine` in
[`tests/conftest.py`](tests/conftest.py)).

**Do not hard-code test totals in this file.** The suite grows every week (it was ~600
in July, it is over 1000 now) and a stale number here is worse than no number — run
`python3 -m pytest -q --collect-only` for the current count and `cd app && npx playwright
test --list` for e2e.

**CI is currently RED.** The `ci` GitHub Actions job has failed on each of the last three
merged PRs (#48, #49, #50) on `main`; `codeql` is green. `ci-red-matrix` is actively
diagnosing root cause and tightening branch protection — until that lands, a green local
`pytest` run does not mean a green CI run, and the M1 gate (§6.1) cannot be claimed as
progressing while CI is red on main.

**In flight right now (2026-07-14):** this branch (`fix/review-blockers`) is a shared
working tree for multiple concurrent sessions closing out review findings — see §3.1 for
the live list. Sections below reflect what has actually landed in git, not what is
mid-edit; check `git log`/`git diff` for the authoritative current state of any file this
doc references.

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

**Known deviation, flagged not hidden:** real cloned-voice synthesis (Kokoro→Kanade voice
conversion, §10 M5 U6) shipped 2026-07-14 while the M1 reliability benchmark (§6.1) is
still `needs-hardware` — i.e. not green. That is exactly the class of work this rule exists
to defer. It shipped anyway because it closed a previously-spec'd, already-scoped U6 gap
rather than opening new surface area, but that is a judgment call, not an exemption written
into the rule as stated above. Recorded here so it can be explicitly ratified (amend the
rule to distinguish "finish a started, scoped item" from "new top-level mode") or treated
as a rule violation to walk back (flag it experimental-only, gate it behind a flag until M1
is green). Until one of those happens, treat the rule as **not currently being followed**,
not as a clean gate.

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
├─ preload/  contextBridge boundary      ├─ tts_engine.py    Kokoro (+blend/modulation)
│            (see note below)            ├─ recorder / audio_gate / hotkey_manager
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

**Preload boundary note (was stale — this diagram previously said the preload script
exposed the auth token directly to the renderer; that is no longer an accurate
description and is being actively tightened).** `sqlite-canon-ipc` is mid-refactor
replacing the renderer's generic `backendRequest` proxy: destructive/sensitive routes
(privacy wipe, model delete, voice delete, job cancel, draft send, health) are moving to
typed IPC channels with payload schema validation and a required `confirm: true` for
destructive ones; the remaining generic channel validates against an exact
(method, route) allowlist instead of prefix matching. Confirm the exact shape of
`preload.js`/`ipc.js` in git before restating a security claim about it here — it is
changing under active review right now.

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
requirement, provenance `.meta.json` sidecar). **Cloning synthesis is now real but
experimental** (Kokoro→Kanade voice conversion, shipped 2026-07-14, see §10 M5 U6 and the
stabilization-rule note in §1) — treat it as pre-M1 experimental scope, not a finished
1.0 feature; `clone-review-loop` is still working through its review findings (§3.1).

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

**Quality infrastructure.** A large and growing Python test suite (see the note at the top
of this doc for how to get the current count — do not hard-code it); Playwright Electron
suites (smoke walk + review-overlay flows) that found real shipped bugs (review-overlay
401s, bootstrap cold-start race — both fixed); packaged-app screenshot CI on pinned
ubuntu-24.04. The post-merge gap review's original 22 findings are closed (privacy wipe
completeness, persona prompt preservation, window lifecycle, history retention, deepcopy
hardening, dead deps removed, race guards, HTML escaping, corrupt-store `.corrupt`
quarantine, etc.), but **that review has since reopened**: shipping voice cloning and
SQLite-canonical drafts surfaced a new round of findings that are not yet closed — see
§3.1. Do not restate "all findings closed" until §3.1 is empty.

### 3.1 Unresolved review findings (live as of 2026-07-14)

Tracked here instead of only in session chat so this file stays the single source of
truth. Remove a line only once its fix has actually landed in git (check the log, not the
session's self-report).

- **Voice-wipe postcondition** — `get_voices_dir` conflated "look up the path" with
  "create the directory," so a privacy wipe could recreate the directory it just deleted.
  Fix in progress (`voice-wipe-fix`): split into `get_voices_path` (pure lookup) /
  `ensure_voices_dir` (mkdir), used correctly by wipe vs. write paths.
- **Send/wipe race** — an in-flight draft send can re-persist history *after* a privacy
  wipe deletes it. Fix in progress (`wipe-send-race`): new `output_coordinator.py`
  (`OutputCoordinator`) with an active-send registry, cancellation event, and exclusive
  lease; wipe drains through it before deleting, aborting (not deleting) on timeout.
- **TTS unload race** — the TTS runtime's read lease doesn't cover worker-thread
  generation/playback, so an unload can race active speech. Fix in progress
  (`tts-lease-playback`): extend the lease to cover the whole worker-thread lifetime.
- **Privacy wipe doesn't drain TTS/cloning** — wipe needs to stop playback, cancel any
  in-flight voice-clone conversion, clear the TTS cache, and verify idle postconditions
  before it deletes. Fix in progress (`tts-wipe-drain`); sequenced after the lease fix
  above lands (same worker loop).
- **Voice-cloning review findings** — availability check, job-state surfacing (`speak()`
  currently returns `ok:true` at queue admission with no `queued→loading→synthesizing→
  converting→playing→completed|failed` visibility to the renderer), TTS cache key missing
  a reference fingerprint (sample SHA-256 + mtime + engine/model revision — otherwise
  re-cloning the same name can replay stale audio), atomic saves, voice ID validation, STT
  coordinator interaction. In progress (`clone-review-loop`, feeding job-state work to
  `tts-lease-playback` once its lease work is safe to build on).
- **Renderer IPC surface** — generic `backendRequest` proxy replaced with a typed IPC
  layer for destructive/sensitive routes (privacy wipe, model delete, voice delete, job
  cancel, draft send, health): payload schema validation, `confirm: true` required for
  destructive calls, exact `(method, route)` allowlist for the rest. In progress
  (`sqlite-canon-ipc`), see the preload note in §2.
- **SQLite as canonical draft store** — JSON draft storage becomes a one-time
  import/backup rather than the source of truth. In progress (`sqlite-canon-ipc`).
- **Windows dependency/release qualification** — `requirements-win.lock` needs
  `--require-hashes` in CI + a drift check + an optional-cloning-deps manifest; release
  qualification CI (NSIS install/upgrade/uninstall, AppImage, checksums, provenance) is
  not yet built. In progress (`win-lock-release`).
- **CI is red** — see the note at the top of this doc; `ci-red-matrix` is diagnosing root
  cause across the last three merged PRs.
- **Torch version drift** — `requirements-linux.lock` pins `torch==2.13.0` but the dev
  venv actually runs `2.12.1+cu130`; `tools/setup_voice_cloning.py` needs to stop being
  able to resolver-upgrade torch out from under the lock.

**LLM cleanup reliability (found + fixed live, 2026-07-10).** `_call_api` used a fixed 30s
HTTP read timeout with `DEFAULT_MAX_OUTPUT_TOKENS=1100`. On the CPU floor tier a longer
dictation's persona cleanup runs past 30s, so the request timed out and the engine
*silently returned the raw, uncleaned text* (while llama-server kept churning its single
slot). Now `compute_api_read_timeout()` scales the read timeout to the token budget
(pessimistic 8 tok/s, floored/ceilinged), so legitimate CPU cleanups finish. Verified end
to end against a live gemma-4 llama-server: a 94-word dictation that silently no-op'd at 30s
now cleans correctly in ~50s. Covered by `tests/test_api_timeout.py`.

**LLM cleanup empty-output guard (sibling bug, found + fixed 2026-07-10).** Working backward
from the timeout fix: `_call_api` returned the model's completion verbatim, so an *empty*
completion (`""`) for real speech was handed straight back. llama-server genuinely emits `""`
when its slot is still churning (e.g. right after a prior request timed out). The main
dictation path (`server.py`) has **no raw fallback** — that empty string became the draft and
would be injected, silently replacing the user's dictation with nothing (data loss, strictly
worse than returning raw). Now an empty/whitespace completion for non-empty input falls back
to the raw text at the source, protecting all four callers at once. Covered by
`tests/test_llm_empty_output_guard.py`.

**Active preset now drives dictation (wired 2026-07-10, was M5).** The 'current preset'
settings dropdown lets the user pick a dictation persona and persists it (`current_preset`),
but the dictation pipeline hardcoded **True Janitor** and ignored the choice — a dead control.
`llm_engine.resolve_dictation_preset()` now maps the profile's `current_preset` to the preset
used for cleanup, honoring internal presets and existing personas, and falling back to True
Janitor when the value is empty or names a persona that was deleted/renamed after selection —
so a stale choice never breaks the core loop. Resolved off the single hot-path profile read
(`get_pipeline_flags`), no extra disk I/O. Covered by `tests/test_dictation_preset_resolution.py`.

**Known intentional behaviors (not bugs):**
- Persona `model_hint` is stored metadata only; no model routing yet (M5).
- `load_personas*()` return live cache objects (hot path); callers treat as read-only.

---

## 4. Milestone map to 1.0

Order is binding. M0–M2 make the product **trustworthy**; M3–M5 make it **complete**;
M6–M7 make it **safe to extend**; M8+ is post-1.0.

| Milestone | Theme | Gate to advance |
|---|---|---|
| **M0** | Release baseline & repo front door | Clean-machine reproducible build; README/SECURITY exist |
| **M1** | Core-loop reliability + safety rails | Reliability benchmark (§6) passes — *safety rails (§6.2), job-manager core + dictation integration (§6.3), and the benchmark harness (§6.1) are all built & tested; the remaining gate is running the harness to green on real hardware (`needs-hardware`)* |
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

### 4.1 Scope split — what gates what

The milestone table above is the binding *order*; this is the same work grouped by
*release stage*, so a "why isn't X done yet" question has one answer instead of a
milestone-number lookup.

**Public-alpha blockers** (must be true before anyone outside the team runs a build):
CI green on `main` (currently red, §3.1); all §3.1 findings closed; M0 release-integrity
baseline (checksums, SBOM, provenance, Windows build verified end-to-end); M1 reliability
benchmark run to a green gate on real hardware; M2 injection matrix filled for the top-10
apps on at least one platform; the privacy wipe verifiably leaves nothing behind
(the send/wipe race and TTS/cloning drain findings in §3.1 block this specifically).

**Beta work** (needed before a wider public release, not before a signed alpha): M3 voice
control completion (wake word, settings UI, safety invariants); M4 DataRegistry +
at-rest protection; remainder of M5 (persona editor polish, model catalog remainder,
golden-audio WER gate, screenshot QA baselines); cloning promoted from experimental to
supported (export routes, native backend blending, audible disclosure marker — see the
stabilization-rule note in §1 for why it shipped early).

**1.0 work**: M6 architecture decomposition (`server.py`/`main.js` split, input/audio/model
coordinators); M7 automation & platform (MCP tool invocation, per-app injection profiles,
cross-vendor GPU builds, electron-updater, published capability matrix); the full §11 UI
paradigm land (design tokens → status rail → Stream → three-space navigation).

**Post-1.0 experiments** (§14, explicitly parked — do not build before the M1 gate is
actually green, not just "harness built"): Meetings mode (U10), Brainstorm mode (U11),
Threads/Echo cards, sqlite-vec semantic search, MCP write automation beyond M7's gated
core, further cloning polish beyond the M5 engine integration, large visual redesigns
beyond §11's incremental path.

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
- [x] **Root `README.md`** — *done* (description, 30-second workflow, feature matrix,
      supported OSes, hardware tiers (§12), privacy model, install + dev setup (§13),
      architecture diagram, known limitations, roadmap boundaries, MIT license, "A Source
      Arcanum project"). *Remaining:* screenshots + demo GIF (`needs-manual-qa` — real
      captures of the running app).
- [x] **`SECURITY.md`** + a security-issue reporting channel — *done*.
- [x] **`.github/FUNDING.yml`** (GitHub Sponsors + Ko-fi) — *done*. Free-forever is the moat;
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

- [x] **Harness built** — `reliability_benchmark.py` (pure, unit-tested runner + report:
      `run_repeated`/`run_once` never raise, they *record* failures; `BenchmarkReport`
      computes one pass/fail gate where an unperformed manual check counts as *incomplete*,
      not passed — silence is not success) + `tools/reliability_benchmark.py` (HTTP glue to
      drive a live sidecar: a headless dictation core-loop over mock-draft → review →
      accept → decline, backend-health-stability, recovery-bin + job-registry reachability;
      emits a summary + JSON, exit 0 iff the gate passes). Covered by
      `tests/test_reliability_benchmark.py` (15) incl. a fake-backend `build_report`.
- [ ] **Run it to a green gate** — `needs-hardware`. The harness automates the plumbing,
      but the full gate is only satisfiable on a provisioned machine (real mic + models +
      target apps + sleep/resume). Track pass/fail per run for: 100 consecutive dictations;
      50 app restarts with backend startup recovery; long-recording success at 5/15/30/60
      min; audio-device unplug/replug; sleep/resume; model crash → restart recovery;
      clipboard restoration; no lost audio after an interrupted pipeline; injection across
      the M2 top-10 matrix. The manual checklist is enumerated in `MANUAL_CHECKS`.

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
- [x] **Review overlay draft summary** — *done*. A word-count summary (with a "long draft"
      flag past the warning threshold) renders under the draft in `review-overlay.html` and
      updates live as the user edits. The pure formatter lives in
      `app/src/renderer/lib/draftSummary.mjs` (vite-bundled into the overlay, unit-tested
      with `node --test` via `npm run test:unit`); a Playwright assertion in
      `review-overlay.spec.js` covers the rendered DOM.
- [x] **Long non-chunked LLM heartbeat** — *done*. `server._StatusHeartbeat` re-broadcasts
      the `rewriting` status (with `elapsed_ms`) on a 4s interval while a non-chunked LLM
      cleanup runs, so a long single-utterance rewrite doesn't look frozen (chunked work
      already emits per-chunk progress). Covered by `tests/test_status_heartbeat.py`.
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
user-visible status, clear retry semantics.

- [x] **Job registry core + dictation integration** — *done*. `job_manager.py`: pure,
      thread-safe `JobManager`/`Job` with the state machine above, stable 12-char ids,
      clamped progress, cooperative cancellation (`request_cancel` → worker observes →
      `mark_cancelled`) plus immediate `cancel`, terminal-state guards, bounded retention
      (oldest finished jobs pruned, active never dropped), and a `subscribe` hook. The
      dictation pipeline is the first consumer: `process_recording_result` registers a job
      and drives it QUEUED → TRANSCRIBING → REFINING → REVIEW_READY → COMPLETED (or
      FAILED / CANCELLED), with `check_cancelled()` also honoring the job's cancel flag and
      a `finally` that guarantees a terminal state. REST-only surface (no WS pollution):
      `GET /jobs[?active=1]`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` (trips the
      pipeline's cancellation event for the active dictation job); `emergency_stop_runtime`
      also cancels it. Diagnostics "Active jobs" panel lists running work with a Cancel
      button. Covered by `tests/test_job_manager.py` (14) + `tests/test_server_jobs.py`
      (7, incl. lifecycle + endpoints + cancel-trips-event); renderer via `node --check` +
      production build.
- [ ] **Remaining job-manager breadth** (incremental, on the same foundation): register
      TTS, voice cloning, model loads, and model downloads as jobs; resource-estimate
      population; retry semantics wired to the existing recording-recovery path;
      model-download cancel + concurrent LLM/Whisper download progress UI. Explicit answers
      still owed for: cancel LLM cleanup without losing the raw transcript; second dictation
      while the first refines; TTS during Whisper GPU use; model switch unloads predecessor;
      low-disk behavior; abandoned-task cleanup sweep.

---

## 7. M2 — Injection compatibility harness

"Works anywhere" is the product promise and the most OS-fragile claim in it. Build a
harness, not tribal memory: for each target record app/version, OS, injection method,
plain-text / multiline / Unicode / punctuation success, selection replacement, clipboard
restoration, focus-loss behavior, elevated-window behavior, average latency.

- [x] **Matrix framework + probe** — *done*. `injection_matrix.py` (pure, tested): per
      target (app × platform) tracks each dimension as pass/fail/partial/untested, with
      method/version/latency; `overall` requires the load-bearing dimensions (plain_text +
      clipboard_restore) and fails if any dimension fails; coverage stats, JSON round-trip,
      Markdown capability-table rendering; `DEFAULT_TARGETS` = the starting app list,
      `TEST_STRINGS` = the injection battery. `tools/injection_probe.py` is the interactive
      operator harness (inject battery via the real `InputInjector`, time it, record
      verdicts, merge into a versioned matrix JSON; `--render` prints the table). Covered by
      `tests/test_injection_matrix.py` (10).
- [x] **Clipboard restoration** — *done* (found missing during M2). The paste-injection
      path (`injector._paste_raw`) previously clobbered the clipboard permanently. It now
      snapshots the prior clipboard and restores it shortly after the paste
      (`clipboard_capture.schedule_text_clipboard_restore`), but only if the injected text
      is still on the clipboard — so a fresh copy is never overwritten. Profile field
      `restore_clipboard_after_paste` (default true, sanitized) + settings toggle. Covered
      by `tests/test_clipboard_restore.py` (8). This satisfies the §6.1 clipboard-restoration
      reliability check for the paste path (Windows rich-format restore remains a follow-on).
- [x] **Injection capability now detected honestly** — *done* (found by an end-to-end test:
      real YouTube audio → Whisper → attempt injection). On a stock Linux box without
      `xclip`/`xsel`/`wl-clipboard`, `pyperclip` has no clipboard backend and the `keyboard`
      fallback needs root — so injection fails at runtime, yet the app used to report
      `injection_method: "paste"` and `supports_basic_clipboard: True` unconditionally for
      all Linux. `platform_capabilities` now actually detects a clipboard backend
      (`_detect_clipboard_backend`), so `supports_basic_clipboard`/`injection_method` are
      truthful (`"none"` here), and `injection_hint()` + a renderer warning tell the user to
      install `xclip`/`wl-clipboard`. Covered by `tests/test_injection_method_selection.py`
      (backend detection + hint). This is exactly the class of gap the matrix exists to
      surface — the app no longer promises injection it can't deliver.
- [x] **End-to-end injection verified on Linux X11** — the full loop was proven live: real
      YouTube audio → Whisper → the real `InputInjector` → `xdotool` XTEST → **exact**
      readback in a live window, for both plain text and Unicode/punctuation
      (`It's been great… café—naïve, 50% "done" (test) — Ω≈ç.`). First real data point
      recorded in `injection-matrix.json` (Terminal, linux-x11, xdotool:
      plain/punctuation/unicode/clipboard_restore all pass — xdotool types directly and
      never touches the clipboard). Note: xdotool typing needs no root; the clipboard-paste
      path's `keyboard` Ctrl+V *does* need root on Linux, so xdotool is the real Linux path.
- [ ] **Fill the rest of the matrix against real apps** — `needs-hardware`. Run the probe
      across the starting matrix (Chrome, Google Docs, Outlook, Word, VS Code, Discord,
      Slack, Notepad, an EHR-like web form, a remote-desktop environment) on each platform.
      Known failure surfaces to probe: elevated windows, secure fields, browser/Electron
      editors, games, RDP/Citrix, Wayland, full-screen apps, clipboard managers, IMEs,
      rich-text editors, apps that modify selection during injection. Publish results as the
      per-platform capability matrix (§10, M7) — support promises must not outrun reality.

---

## 8. M3 — Voice control completion (wake → speak → stop → confirm)

The backend logic layer is shipped (§3). What remains is the service/UI/dependency layer:

- [x] **Wake-word MVP server integration** — *SHIPPED 2026-07-15*. Routes landed as
      `/wake/status` + `/wake/enable` + `/wake/disable` (+ `/wake/models*`, `/wake/test`)
      in `routes_wake.py`; profile fields `wake_word_enabled` (default **false**),
      `wake_word_model`, `wake_word_sensitivity` (0.55-equiv), `wake_word_cooldown_ms`,
      `wake_word_max_recording_s`. Detection calls the shared start path; disabling fully
      releases the mic stream (idempotent, quiesced before privacy-wipe **before** the
      recorder drain); `/privacy` carries a live-truthful `wake_listener` entry.
- [~] **Real openWakeWord integration** — *engine SHIPPED 2026-07-15, zero new deps*.
      Direct-ONNX pipeline in `wake_models.py` (melspec → embedding → classifier), verified
      against real v0.5.1 assets, running on the already-shipped `onnxruntime`; VAD reuses
      the existing energy gate. **Ships with NO bundled wake-phrase classifier**: all 6
      official openWakeWord phrase models are CC-BY-NC-SA (§9.4 gate) — excluded. A
      user-import path (`/wake/models/import`, sha256-pinned, 20 MB cap) makes it usable
      today; the self-trained "hey fingers" model is still the path to a shippable default
      classifier. See `LICENSES-MODELS.md`.
- [~] **Wake-word test harness**: fixture-based FA/FR test is a **skipped skeleton**
      (`@skipUnless(BETTERFINGERS_WAKE_FIXTURES)`) — the `tests/wake_fixtures/` audio does
      not exist yet, so **a custom wake phrase is still not "done"** per this milestone's own
      rule. `tools/wakeword_probe.py` not built; the `/wake/test` route (arm a window, report
      score peaks) covers the interactive-probe need instead.
- [ ] **Voice Control settings UI + review-overlay wiring** (scope 4 frontend — zero of it
      exists in `index.html` today): wake toggle/sensitivity/cooldown, auto-stop fields,
      `app_commands_enabled`, editing-commands toggle, confirmation policy, command prefix,
      and a **test panel** that runs `voice_commands`/`voice_edit_commands` against typed
      or spoken text showing the resolved intent *without executing it* (`voice_preview.py`
      exists for exactly this). Overlay badges: idle / listening / recording /
      `Command: <action>` / `Needs confirmation — say "confirm" or "cancel"` riding the
      existing `broadcast_status_threadsafe` channel (`command_detected`,
      `command_needs_confirmation`).
- [~] **Training/calibration (Phase 2)** — *builder SHIPPED 2026-07-15*. On-device
      wake/command-phrase trainer with no torch and no GPL/NC dependencies:
      `wake_trainer.py` trains a NumPy classifier head on the shipped Apache-2.0 backbone
      (plugs into `WakeScorer` via a duck-typed `NumpyClassifierSession`, saved as `.npz`);
      `wake_training_data.py` generates positives from the app's own **Kokoro** voices
      (Apache/MIT — the GPL-free replacement for openWakeWord's Piper) plus the user's
      recordings, and negatives from decoy phrases; `wake_training_service.py` orchestrates,
      calibrates a personalised threshold, and emits a **reliable / noisy / unusable**
      verdict. `POST /wake/train` (background) + `GET /wake/train/status`; a "Build a Wake
      Phrase" panel in Voice Control. Trained models register in the wake manifest
      (`origin="trained"`) and are selectable like any classifier. *Remaining:* FA/FR
      validation against **real recorded** `tests/wake_fixtures/` audio (the pipeline is
      tested against the real backbone + stubs, but genuine field recordings don't exist
      yet — the milestone's "not done without fixture-based FA/FR testing" bar); plus the
      sensitivity-test/false-trigger-log/export-import polish and `observed_transcripts`
      alias learning. The trainer is the shared foundation for command-phrase models.

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

- [x] **Redaction primitive + known dictation/TTS leaks** — *done*. `log_redaction.py`
      (`redact_user_text`): user content logs as `<redacted N chars>` by default (length
      kept for debugging, content never written); opt into raw with
      `BETTERFINGERS_LOG_RAW_TEXT=1`. Wired into the sites that leaked dictated/TTS text by
      default: `intent_engine.process_input` (logged the **full** utterance at INFO) and the
      three `server.py` TTS log lines (leaked a 20–30 char preview). Covered by
      `tests/test_log_redaction.py`.
- [x] **Remaining audit** — *done 2026-07-15*. Full sweep in `docs/redaction-audit.md`:
      8 REDACT sites wrapped (`redact_exc` for user-text-bearing exceptions; a **line-level**
      `redact_stderr_lines` filter for llama-server stderr in both the log line and
      `/doctor`'s `last_error_details.stderr` — preserving loader/system lines while
      redacting content). A **standing lint gate** (`LoggingLeakGateTests`, content-keyed
      allowlist) greps server-side sources on every run and already caught 2 leaks the
      manual sweep missed (`transcriber.py`, the `/transcribe` route); an Electron twin
      (`redact.js` + `app/tests/redact.test.mjs`) guards the renderer. MCP: no tool-*invocation*
      path exists yet, so nothing carries user content there today (re-audit when C12 lands).

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

- [x] **Discipline extended everywhere** — *done 2026-07-15*. `store_migration.py`
      (`load_versioned_store` / `write_atomic` / backup-per-version-step / `.corrupt`
      quarantine) now backs **personas, voice presets, profiles, and app_state**. Downgrade
      behavior is defined and proven **byte-for-byte non-destructive** (file newer than the
      code's schema → read-only in-memory defaults, zero writes). Quarantine/downgrade
      events surface at `GET /doctor`'s new `store_warnings` field + startup log. Persona
      adoption fixed a real latent bug (genuine v1 flat-file personas were silently
      discarded). The 3 pre-existing unconditional profile value-migrations are deliberately
      kept outside the version ladder (mixed pre/post-merge timing; commented at each site).

---

## 10. M5–M7 — Completion, decomposition, platform

### M5 — Voice / persona / TTS completion (close or cut every deferred sub-part)

- [ ] **TTS audio DSP remainder (U5):** streaming playback, BS.1770/RMS loudness
      normalization, chunk crossfade (utterance LRU cache exists). Needs tuning by ear.
- [~] **Cloning (U6):** *engine integration SHIPPED (2026-07-14)* — the kokoclone
      pipeline (Apache-2.0): Kokoro synthesizes, then Kanade voice conversion
      (`frothywater/kanade-tokenizer`, MIT, pinned commit + pinned HF model revision)
      re-voices to the stored reference sample (`voice_clone_engine.py`; RoPE-safe ~9s
      chunking). Deps are optional/on-demand (`tools/setup_voice_cloning.py` — git-only
      package can't live in the hashed locks; torch was already a dep, torchaudio added
      by the setup tool). **Frozen-build provisioning SHIPPED 2026-07-15:** the
      pip-install-into-`sys.executable` approach (impossible in a PyInstaller build) is
      replaced by a verified-artifact **side-runtime** — a pinned python-build-standalone
      3.12 + torch/torchaudio/kanade wheels, download-verify-extract like llama-server
      (directory-preserving PEP 706 extractor), cloning dispatched as a subprocess;
      `availability()` now reports truthfully in dev *and* frozen contexts. WavLM-base-plus
      weights (CC BY-SA 3.0, not MIT) are pinned to their upstream URL + our sha256 rather
      than re-hosted. *Integration dependency:* the `clone-runtime-v1` artifacts still need
      publishing (catalog/provisioning built + tested against the final URL shape). ONNX
      export of the Kanade pipeline is a tracked follow-up (source notes in code). Cloned
      voices fail HONESTLY when the engine/sample is missing
      (never a silent base-voice substitute). `DELETE /tts/voices/{id}` shipped
      (immediate deletion requirement met). *Remaining:* export routes, native
      (non-ONNX) backend blending (still falls back to base voice, logged), optional
      audible disclosure marker for exports. **Consent + abuse controls carried
      forward:** explicit consent acknowledgement (shipped), cloned-voice labels +
      provenance metadata (shipped), never upload samples, warn against cloning third
      parties.
- [ ] **Persona editor polish (U7):** live prompt preview; full voice base/blend/speed +
      few-shot raw→out list UI inside the persona editor (Voice Studio schema is proven);
      `dictionary_scope` control.
- [x] **Wire the active preset into dictation** — *done* (`resolve_dictation_preset`,
      honors `current_preset` with a True-Janitor fallback for empty/stale selections).
      Remaining in this item: **model routing from `model_hint`** (gated so it never
      triggers surprise downloads).
- [ ] **Model catalog remainder (U8):** verified GGUF URLs for FunctionGemma-270M /
      Qwen3.5-2B; real non-Whisper STT integration (Moonshine / Parakeet-ONNX) behind the
      transcriber interface. Golden-audio WER gate (§13) must accept each model before it
      becomes a default.
- [ ] **Golden audio suite completion (C9):** check in real `.wav`/`.txt` fixtures +
      `test_golden_audio.py` runner that skips without a model; CI job per configured STT
      model.
- [~] **Screenshot QA completion (U1):** *`review-overlay.spec.js` now wired into CI.* Its
      TTS/LLM tests (Read/Change/Instruct) are gated behind `BETTERFINGERS_E2E_MODEL=1`; the
      model-free subset (overlay open, badges/buttons, live word-count summary, cancel,
      dashboard-after) runs from the mock-draft endpoint with no model, and the workflow now
      runs the full Playwright suite. Verified locally: smoke 14/14 + overlay 4 passed / 3
      gated, with real dashboard/settings/models/diagnostics/overlay screenshots. *Remaining:*
      check in curated baselines under a deliberate path (not the gitignored per-run
      `app/artifacts/`) + reg-actions PR diffing — a cohesive visual-regression unit.

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
- [~] **Model resource manager:** *backend SHIPPED 2026-07-15, UI pending*.
      `ModelRuntimeCoordinator` now holds a per-component ledger (model_id / estimated_mb /
      last_used / pinned), **admission control** with LRU eviction through the same unload
      path manual unload uses (self-credit on same-component replacement, real RAM
      re-sampling after eviction, RAM-floor refusals that surface cleanly via `_mark_error`
      instead of OOM-crashing, CPU-fallback model *suggestion* in the refusal payload), and a
      300 s idle sweep (llm/stt; tts keeps its own). Wired into all three load sites via DI;
      `GET /models/resources` exposes the ledger. **Gap (flagged by QA):** no Diagnostics UI
      consumes `/models/resources` or the admission-refusal payload yet — backend + contract
      are done and scenario-tested, DOM wiring is the remaining piece. Audio-device ownership
      manager (above) still separate.

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

- `python3 -m pytest -q` — full Python suite green. **CI is currently red on `main`** (see
  the top of this doc and §3.1) — a green local run does not mean this gate is met.
- `cd app && npm run test:unit` — Node's built-in runner over `app/tests/**/*.test.mjs`
  (pure renderer-helper units, e.g. the draft-summary formatter). Fast, no Electron.
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
