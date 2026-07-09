# Manual QA checklist

Manual verification steps for every feature shipped during the MASTER_PLAN
loop. The automated suites — `python3 -m pytest` (307 tests, pure logic) and
`cd app && npx playwright test` (19 e2e tests: dashboard walk, settings
dirty-state, review overlay flows) — cover a lot of ground now; this checklist
covers what still needs **human senses** (ears for audio, a real mic, real
target apps for injection) or judgment.

## Final human pass — priority order (~15 min)

The fastest high-value pass, ordered by risk. Items 1–2 exercise the two
bugs fixed on 2026-07-08; they were real shipped breakage.

1. ☐ **Review overlay end-to-end (auth fix).** Dictate an utterance, open the
   review overlay, then: **Read** (TTS audibly plays), **Change** with a spoken
   instruction (rewrite lands), **Send/Accept** (text injects). Until 2026-07-08
   every one of these silently 401'd — the Playwright suite now covers the
   plumbing 6/6, but audio quality and injection into a real target app need
   ears and eyes.
2. ☐ **Cold-start resilience (bootstrap retry fix).** Quit everything, start
   the app fresh (worst case: right after boot), and confirm the profile
   dropdown populates within ~10s without a manual reload — even if the
   backend is slow to come up.
3. ☐ **One full dictation round-trip** into a real app (record → draft →
   correction → inject).
4. ☐ **Push-to-talk while unfocused** (hold-to-talk from another app / tray).
5. ☐ **TTS normalization by ear** ("$5", "Dr.", a URL — natural, not
   character-by-character).

Everything below is per-feature detail if something above misbehaves or you
have more time.

How to run the app for QA:

```bash
# Terminal 1 — Python sidecar
python3 server.py            # or the packaged sidecar

# Terminal 2 — Electron renderer
cd app && npm run dev
```

Legend: ☐ = to verify. Each item notes the feature (MASTER_PLAN id) and the
files involved so a failure is easy to trace.

---

## Onboarding & first run (U3)

- ☐ Fresh profile (clear `localStorage` key `bf_onboarding_complete`) → the
  onboarding overlay appears on launch and blocks the app.
- ☐ Step 2 (data consent): **Next is disabled** until the checkbox is ticked.
- ☐ `Esc` does **not** dismiss the overlay; `Tab`/`Shift+Tab` stays trapped
  inside the modal.
- ☐ Step 4 "Speech models": the **hardware-aware recommendation box** appears
  with a detected tier + recommended LLM/Whisper (U4). If the sidecar is down,
  the box stays hidden and the step still works.
- ☐ "Decline" quits the app; finishing sets the flag so it does not reappear.
  _Files: `app/src/renderer/main.js` (`initOnboarding`, `onboardingSteps`,
  `populateOnboardingRecommendation`), `index.html` `#onboardingOverlay`._

## Hardware detection & model recommender (U2, U4, U8)

- ☐ `GET /hardware/tier` returns a tier in `{cpu-only, igpu, dgpu-8g, dgpu-12g+}`
  matching the machine.
- ☐ `GET /models/recommend` returns `llm`, `whisper`, and `alternatives`
  sections; the recommended LLM fits within RAM (never "insufficient").
- ☐ Models tab shows the recommendation callout (`#modelRecommendation`).
- ☐ `alternatives` lists FunctionGemma-270M / Qwen3.5-2B / Moonshine etc. and
  none of them appear as **downloadable** entries (they are informational only).
  _Files: `hardware_report.py`, `model_recommender.py`, `model_manager.py`._

## Personas — schema v2 + editor (U7)

- ☐ Existing (v1, flat-string) `personas.yaml` still loads; personas appear in
  the preset dropdown unchanged.
- ☐ Persona wizard → **Advanced** block: set temperature / preferred model /
  capitalization / punctuation / sign-off, save → success toast.
- ☐ Re-open the same persona by name (blur the name field) → Advanced fields
  **and its existing prompt** repopulate from the saved values
  (`GET /personas/{name}`) — the prompt is NOT silently replaced by a fresh
  wizard-generated one.
- ☐ Click **"Regenerate from wizard"** while editing an existing persona →
  prompt is replaced with the wizard-generated text as before.
- ☐ Save a **prompt-only** edit on that persona → the previously-set temperature
  is **preserved** (partial-merge).
- ☐ Temperature outside 0–2 → save fails with a 400 message.
- ☐ Delete a persona → name field, prompt preview, and Advanced fields all
  clear (no stale data left visible for the next persona created).
- ☐ On disk, `personas.yaml` now has `schema_version: 2` and nested dicts.
  _Files: `llm_engine.py`, `server.py` `/personas*`, `app/src/renderer/*`._

## Dictation pipeline add-ons (C1, C2, C4, C11)

- ☐ **Personal dictionary (C1):** add a term; speak a phrase that should map to
  it → the correction is applied in the draft. Terms persist across restart.
- ☐ **Voice editing commands (C2):** speak "new paragraph" / "all caps" style
  commands → formatting applied (only when Voice Commands enabled in the profile).
- ☐ **Confidence (C4):** speak clearly vs. mumble → low-confidence drafts render
  the confidence indicator; silent-inject threshold respected per profile.
- ☐ **Macros (C11):** define trigger→expansion; speak the trigger as a whole
  phrase → expands; a substring (e.g. "beta" for "eta") does **not** expand.
  Toggle "Voice Macros" off → no expansion.
- ☐ **Macros persistence (bugfix Phase 6 regression):** add a macro, then
  reopen the Voice Macros settings section (or restart the app) — the macro
  list still loads correctly (previously: `get_macros()` crashed on any read
  after a save, so the list would silently fail to populate / the endpoint
  would 500).
- ☐ **Corrupted dictionary/macros files (bugfix Phase 6):** manually put
  invalid JSON in `dictionary.json` or `macros.json` in the user-data folder,
  then launch — app starts normally with an empty list (not a crash); the
  corrupted file is renamed to `*.corrupt` next to the original (check the
  logs for a warning), and adding a new term/macro saves correctly afterward.
- ☐ **Latency HUD post-processing row (bugfix Phase 6):** after an utterance,
  the HUD/`/metrics` shows a "Dictionary/commands/macros" row between
  Transcribe and LLM cleanup (previously that time was silently folded into
  the Transcribe number).

## Audio, history, privacy (C6, C7, C8, C10)

- ☐ **Never lose audio (C6):** record, then simulate a pipeline error → the raw
  audio is retained and a recovery card lets you re-run it.
- ☐ **Privacy dashboard (C7):** `/privacy` lists only local touchpoints;
  "wipe" removes recordings/drafts/history.
- ☐ **Searchable history (C8):** past drafts are searchable in the Library;
  FTS matches partial words. Survives restart (SQLite store).
- ☐ **Latency HUD (C10):** after an utterance, the debug HUD shows STT + LLM
  stage timings; `/metrics` returns the same numbers.

## TTS (U5, U6)

- ☐ **Normalization (U5):** TTS reads "$5", "Dr.", "3.14", a URL, and a code
  symbol naturally (not character-by-character).
- ☐ **Smart-split (U5):** a long multi-sentence draft is chunked at sentence
  boundaries with no mid-word cuts; playback is continuous.
- ☐ **Voice blend (U6, math core only):** `voice_blend.blend_voices/blend_many`
  are unit-tested; the **slider editor + saving blended voicepacks is not yet
  wired** (see REMAINING_WORK). Confirm base voices still play.

## Review overlay (2026-07-08 auth fix)

Context: the overlay's hand-rolled fetch never sent `Authorization`, so every
backend call from it 401'd whenever the auth token was set (always, under
Electron). Fixed in `app/src/renderer/review-overlay.html`; the Playwright
suite (`app/tests/review-overlay.spec.js`, 6/6) now guards the flows, but
verify the human-perceivable parts once:

- ☐ **Read:** TTS audio actually plays and matches the draft text.
- ☐ **Change (voice) / Instruct (typed):** the rewrite visibly updates the
  final text and "rewriting" state resolves.
- ☐ **Send / Accept:** accepted text is injected into the focused app.
- ☐ **Cancel:** overlay hides, nothing injects.

## Global hotkey / push-to-talk (migration)

- ☐ Hold-to-talk: audio records only while the key is held (key-up ends it).
- ☐ Press-to-toggle: one press starts, another stops.
- ☐ Works when the app is unfocused / in the tray.
  _Files: `app/src/main/hotkeys.js` (uiohook-napi)._

## Window lifecycle / tray

- ☐ Close the main dashboard window (X button) — the app keeps running (tray
  icon stays; sidecar keeps recording via hotkeys).
- ☐ With the dashboard closed, click the tray icon (or "Open Dashboard" from
  its menu) — **the dashboard reopens** instead of doing nothing.
- ☐ Launch a second instance of the app while one is running — the existing
  dashboard is focused/reopened instead of a second instance starting.
- ☐ Quit from the tray menu — the sidecar process and hotkey listeners are
  torn down cleanly (check for orphaned `server.py` processes after quit).
  _Files: `app/src/main/main.js`, `app/src/main/windows.js`._

## Renderer polish (bugfix Phase 5)

- ☐ Minimize/switch away from the app for >3s, then switch back — the health/
  runtime badges resolve immediately (no stale "offline" flash while backend
  is actually fine); poll doesn't run while the window is hidden (check no
  console spam / network calls in devtools while minimized).
- ☐ Persona name field: type an existing persona's name, then quickly retype
  a different name before the Advanced-fields fetch resolves — the loaded
  fields match the LAST name typed, not a stale response.
- ☐ Trigger a history search / macros / dictionary error (e.g. stop the
  sidecar) with a name containing `<`, `>`, or `&` in the error text — the
  error renders as plain text, not broken/executed HTML.
- ☐ Built-in personas (True Janitor, Formal, Polished, Unhinged, Pompous
  1800s Lord) still can't be deleted without the allow-builtin override; this
  list now comes from `GET /personas-builtins` instead of a hardcoded set.
  _Files: `app/src/renderer/main.js`, `server.py` `/personas-builtins`._

---

## Regression sanity (every session)

- ☐ `python3 -m pytest -q` → 307+ passing.
- ☐ `cd app && npx playwright test` → 19+ passing (needs a local LLM model +
  llama-server on disk for the review-overlay spec; close any running
  BetterFingers instance first — it holds the Electron single-instance lock).
- ☐ `node --check app/src/renderer/main.js && node --check app/src/renderer/api/backend.js`.
- ☐ App launches, records one utterance end-to-end (record → draft → send).
