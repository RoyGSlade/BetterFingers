# Handoff Report — Long-Recording & Persona Robustness Work

**Date:** 2026-07-08
**Branch (at time of writing):** `master-plan` (pushed to `origin/master-plan`)
**Test status (at time of writing):** `python3 -m pytest -q` → **350 passing**, tree clean.

> **Update:** `master-plan` has since been merged into `main` and deleted; there
> is no longer a `master-plan` branch to check out. `main` also picked up the
> MCP client step (`b98c1b3`) after this report was written. Current state:
> **361 passing** on `main`. The "Resume" instructions below are kept for
> historical context — use `main` instead of `master-plan`.

This report lets you pick the work back up from your main PC.

## Resume on your main PC

```bash
git fetch origin
git checkout main
git pull            # fast-forwards to the pushed state
python3 -m pytest -q   # expect 361 passing
```

The roadmap and per-phase status live in
[`docs/PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN.md`](PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN.md).
Each completed phase has a `> **Status: ✅ DONE**` block annotated inline above
its "### Problem" section — that is the source of truth for what's finished.

To continue the autonomous build loop from where it stopped, run:

```
/loop continue docs/PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN.md — work through the
plan's phases in Suggested Order, implementing each and annotating ✅ DONE back
into the md; commit per phase; keep pytest green. Phases 1-7 done; NEXT: Phase 8.
```

## What shipped this session

### Pre-plan bug fixes (commit `3c4982a`, and `77782e0` / `3c6fad4` earlier)
- Review overlay now sends the sidecar auth token (was 401-ing).
- Dashboard reopens from tray after being closed.
- Backend host/port unified through a `backendOrigin` preload bridge (works on
  non-default `BETTERFINGERS_PORT`).
- `confidence` included in the live overlay payload.
- Linux audio ducking honored (Windows-or-Linux+pactl), not Windows-only.
- Electron Playwright test env fixed (`ELECTRON_RUN_AS_NODE` stripped, onboarding
  dismissed); doc test count corrected 262 → 307.

### Long-recording + persona plan — Phases 1–7 (all committed)

| Phase | Commit | Summary |
|-------|--------|---------|
| 1 + 2 | `628b3d5` | Split `output_token_limit` into `max_completion_tokens` (512–4096, default 1600) + `long_draft_warning_words` (300–10000, default 1200); legacy alias preserved; initial dictation passes the completion cap into the engine. |
| 3 | `2af07cb` | `split_text_for_llm_chunks()` — sentence/paragraph-aware chunking with overlap context (replaces raw word-count splitting). |
| 4 | `7bf70c6` | Long-recording progress notifications (`long_recording_detected` / `chunking_started` / `chunking_progress`) through engine → server → renderer/overlay/tray; review overlay stays closed until ready. |
| 5 | `ba8d845` | Optional stitch pass (`_stitch_chunks`, seam-only prompt, failure-safe) + `long_recording_stitch_pass_enabled` toggle. |
| 6 | `430dc7f` | Persona v2 fields used during inference: `get_persona_runtime`, `compose_persona_system_prompt`, `compose_persona_messages`; temperature override, format rules, few-shot turns, dictionary scope. Prompt-only personas unchanged. |
| 7 | `2ddae7a` | Persona builder robustness UI: output-policy / safety-mode / per-persona max-tokens + chunk-size, few-shot pair editor, prompt-lint (`lint_persona`, 5 rules), test panel (`run_persona_preview`); new `POST /personas/lint` + `POST /personas/test` routes. |

Test count grew 307 → 350 across these phases; each phase was verified at runtime
where observable (custom-port launch, CDP renderer inspection, chunker/compose/lint
demos) and the full suite kept green.

## Remaining work — Phases 8–13 (NOT started)

Follow the plan's **Suggested Order**. Brief scope:

- **Phase 8 — Review & Notification Behavior** (mostly already covered by 4/5).
  Remaining gaps: (a) show a **token/word summary on the final draft** in
  `review-overlay.html` (currently `renderDraft` shows Draft # + text but no
  count summary — a summary element still needs adding); (b) optional heartbeat
  so a long *non-chunked* LLM call keeps status fresh past ~8s (the `rewriting`
  status already stays visible, so this is a nice-to-have). Files: `server.py`,
  `app/src/renderer/main.js`, `review-overlay.html`, `app/src/main/ipc.js`.
  *(This was in progress when work paused — nothing committed for it yet.)*
- **Phase 12 — Confidence-gated send policy** (Suggested Order does this next):
  `confidence_force_review_enabled/below`, `confidence_auto_send_above` profile
  fields; force review when confidence is missing/low/long/gated.
- **Phase 11 — Missed-release watchdog**: `max_recording_seconds` + a timer in
  `hotkey_manager.py` that stops a stranded PTT recording.
- **Phase 10 — Auto-stop-after-silence**: streaming silence state machine in
  `recorder.py` / `audio_gate.py`, `auto_stop_*` profile fields.
- **Phase 9 — Wake-word MVP**: new `wake_word.py` service + adapter interface
  (openWakeWord first), `wake_word_*` profile fields, `/runtime/wake-word/*`
  endpoints. Disabled by default. (Adds a `requirements.txt` dep.)
- **Phase 13 — Wake-word test harness**: `tools/wakeword_probe.py`, fixture
  folders, fake-detector tests.

## Notes / gotchas
- `master-plan` was **18 commits ahead of `origin/master-plan`** as of this push
  (now pushed, so origin was up to date). It has since been merged into `main`
  and the branch no longer exists.
- Initial dictation still uses the **True Janitor** preset by design; the active
  profile's `current_preset` drives the settings UI, not dictation cleanup
  (wiring it in would change behavior + break tests — deferred, see Phase 6 note).
- Persona `model_hint` is stored/metadata only — no model routing yet (deferred).
- A session-local `/loop` wakeup may still be scheduled on the laptop; it only
  runs while this laptop session is open and will not follow you to the main PC.
