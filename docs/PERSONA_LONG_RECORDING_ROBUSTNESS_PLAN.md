# Persona + Long Recording Robustness Plan

## Purpose

Make BetterFingers more tolerant of long dictation and make persona settings matter more during Gemma cleanup.

The current app already has several useful pieces:

- `llama-server` starts with a large context window (`--ctx-size 16384`).
- `LLMEngine._call_api()` already clamps completion tokens up to `4096`.
- Long input is already chunked by word count in `LLMEngine._process_chunked()`.
- Persona schema v2 already stores rich fields such as `temperature`, `few_shot`, `format`, `dictionary_scope`, `voice`, and `model_hint`.
- `AudioRecorder` already streams chunks through `chunk_callback`, which is a useful hook for trailing-silence logic.
- `HotkeyManager` already has explicit `request_start()` / `request_stop()` paths that wake word and watchdog features can reuse.
- The pipeline already stores confidence scores on drafts and broadcasts voice status updates.

The gaps are mostly wiring and UX:

- Profile/UI validation caps `output_token_limit` at `1200`.
- Initial dictation cleanup does not pass the active token limit into `process_fast_lane()`, so it falls back to `DEFAULT_MAX_OUTPUT_TOKENS = 1100`.
- `output_token_limit` is used as both a completion cap and a long-draft warning threshold.
- The chunker splits by raw word count, not sentence/paragraph boundaries.
- Chunk processing has no progress notifications.
- Persona v2 fields are saved but most are not used by the inference path.
- No wake word listener exists yet.
- No auto-stop-after-silence mode exists yet.
- Push-to-talk can still be stranded if the OS or controller misses a release event.
- Confidence is visible but does not yet drive safety policy.

## Goals

1. Let Gemma use more completion tokens when the user explicitly allows it.
2. Process long recordings in batches without making the user feel interrupted.
3. Show clear progress notifications for long recordings.
4. Make persona builder output more robust and more directly connected to model behavior.
5. Add a practical hands-free path without weakening the existing hotkey flow.
6. Add small safety rails that prevent stuck recording and accidental low-confidence sending.
7. Keep short dictation fast and conservative.

## Non-Goals

- Do not remove the review flow.
- Do not make auto-send the default for long recordings.
- Do not raise context size blindly beyond current `16384`.
- Do not require Gemma 4 or larger models to use the feature.
- Do not change model downloads as part of this plan.
- Do not ship a custom wake phrase as "done" without fixture-based false-accept and false-reject testing.
- Do not make the app always-listening unless the user explicitly enables hands-free mode.

## Phase 1: Separate Token Concepts

> **Status: ✅ DONE (2026-07-08).** Added `max_completion_tokens` (512–4096, default
> 1600) and `long_draft_warning_words` (300–10000, default 1200) to profile
> defaults, `_sanitize_profile_values()`, and `validate_profile_settings()`.
> `output_token_limit` is kept as a legacy alias — `_apply_completion_token_alias()`
> maps it onto `max_completion_tokens` for pre-split profiles (its own 900–1200
> clamp/validation preserved for back-compat). Renderer replaced the single 900–1200
> "Output Token Limit" input with two inputs (`settingMaxCompletionTokens`,
> `settingLongDraftWarningWords`) wired through `settingEls` + `runValidation`.
> Server split into `get_active_completion_tokens()` (per-call cap, used by the
> rewrite path) and `get_active_long_draft_warning_words()` (drives draft
> `long_text`/`token_limit`). Tests: `tests/test_token_concepts.py`. Suite 314 green.
> Files touched: `utils.py`, `server.py`, `app/src/renderer/index.html`,
> `app/src/renderer/main.js`, `tests/test_server_drafts.py` (dummy signature).

### Problem

`output_token_limit` is currently described as the LLM completion ceiling, capped at `900-1200`, and also used for long-draft warnings.

That conflates two different concepts:

- `max_completion_tokens_per_call`: how much Gemma may generate for a single LLM request.
- `long_draft_warning_words`: when the UI should warn that a final draft may be unwieldy.

### Changes

Add or rename profile fields:

- `max_completion_tokens`: default `1600`, range `512-4096`.
- `long_draft_warning_words`: default `1200`, range `300-10000`.
- Keep `output_token_limit` as a migration alias for existing profiles.

Files:

- `utils.py`
- `server.py`
- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- `tests/test_profile_migration.py`
- `tests/test_settings_redesign.py`
- `tests/test_server_drafts.py`

### Implementation Notes

- In `utils._profile_defaults()`, add the new fields.
- In `_sanitize_profile_values()`, coerce both new fields.
- In `_migrate_legacy_output_settings()`, map old `output_token_limit` to `max_completion_tokens`.
- Keep accepting `output_token_limit` on import/export for compatibility, but prefer the new name internally.
- Update draft review fields so long-text warnings use `long_draft_warning_words`, not completion tokens.

### Acceptance Criteria

- Existing profiles still load.
- UI accepts `max_completion_tokens=2048`.
- `_call_api()` receives the configured value for initial dictation cleanup.
- A 2000-word final draft can warn without limiting Gemma's per-call completion cap.

## Phase 2: Pass Token Limit Into Initial Dictation

> **Status: ✅ DONE (2026-07-08).** `server.process_recording_result()` now reads
> `max_completion_tokens` (falling back to the `output_token_limit` alias, then
> 1600) from the active profile and passes it as `max_output_tokens` to
> `engine.process_fast_lane()`. Initial dictation cleanup now uses the same
> completion cap as rewrites instead of the engine's 1100 default. Verified by
> `Phase2PassThroughTest` in `tests/test_token_concepts.py`, which asserts a
> configured cap of 2222 reaches the engine call.

### Problem

Initial recording cleanup calls:

```python
engine.process_fast_lane(raw_text, preset, chunk_size=llm_chunk_size)
```

It does not pass `max_output_tokens`, so `_call_api()` defaults to `1100`.

### Changes

In `server.process_recording_result()`:

- Load `max_completion_tokens`.
- Pass it as `max_output_tokens` to `engine.process_fast_lane()`.

Files:

- `server.py`
- `tests/test_server_drafts.py` or a new focused pipeline test

### Acceptance Criteria

- Initial dictation cleanup uses the active profile's completion token cap.
- Rewrite actions continue using the same cap.
- Tests verify the configured value reaches the engine call.

## Phase 3: Sentence-Aware Chunking

> **Status: ✅ DONE (2026-07-08).** Added module-level
> `split_text_for_llm_chunks(text, target_words, overlap_words=40)` in
> `llm_engine.py`: splits on paragraph → sentence boundaries, falls back to a
> single oversized chunk only when one sentence exceeds the target, and returns
> `{"text", "context"}` dicts. The `text` fields form a clean partition (joining
> per-chunk output never duplicates), while `context` carries the previous
> chunk's trailing `overlap_words` for continuity — passed to the model as
> context, never emitted. `_process_chunked()` now uses it and injects the
> overlap as a "do not repeat" context preamble. Tests:
> `tests/test_llm_chunking.py` (8 tests); runtime-checked on real prose (every
> chunk ends on a sentence boundary, ≤target words, no tokens lost/duplicated).

### Problem

Current chunking splits on word count only. This can break paragraphs, lists, and sentences in awkward places.

### Changes

Replace or extend `_process_chunked()` with a helper:

- `split_text_for_llm_chunks(text, target_words, overlap_words=40)`

Behavior:

- Prefer paragraph boundaries.
- Then sentence boundaries.
- Fall back to word count only when necessary.
- Add small overlap context between chunks.
- Preserve ordered chunks.

Files:

- `llm_engine.py`
- `tests/test_llm_engine_token_limits.py` or new `tests/test_llm_chunking.py`

### Acceptance Criteria

- Chunks do not exceed the configured target by much unless a single sentence is longer.
- Sentence endings are preserved.
- Overlap is included only as context and not duplicated in final output.

## Phase 4: Long Recording Progress Notifications

### Problem

The user gets statuses such as `transcribing`, `rewriting`, and `preview_ready`, but not "long recording detected" or chunk progress.

### Changes

Add optional progress callback support to `process_fast_lane()` and `_process_chunked()`:

```python
progress_callback({
    "status": "chunking_progress",
    "chunk_index": 2,
    "chunk_count": 5,
})
```

Broadcast statuses:

- `long_recording_detected`
- `chunking_started`
- `chunking_progress`
- `chunking_stitching`
- `preview_ready`

Renderer behavior:

- Show overlay/status rail message: "Long recording detected. Processing chunk 2 of 5."
- Keep review overlay closed until the draft is ready.
- If chunking fails, create a draft error with the raw audio still recoverable.

Files:

- `llm_engine.py`
- `server.py`
- `app/src/renderer/main.js`
- `app/src/main/ipc.js` if tray/overlay status needs a new transient state
- `app/src/renderer/overlay.html`
- `tests/test_server_drafts.py`

### Acceptance Criteria

- Long recordings visibly show progress.
- The user is not asked to intervene before chunking completes.
- A failed chunk produces a recoverable draft/error state.

## Phase 5: Optional Stitch Pass

### Problem

Chunked output can be locally correct but globally uneven at boundaries.

### Changes

Add a final lightweight stitch pass when there is more than one chunk:

- Input: joined chunk outputs.
- Prompt: "Smooth only transitions and remove duplicate overlap. Do not summarize or add ideas."
- Use a smaller max token cap or the same profile cap depending on output size.

Add profile flag:

- `long_recording_stitch_pass_enabled`: default `true`.

Files:

- `llm_engine.py`
- `utils.py`
- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- tests for stitch prompt invocation

### Acceptance Criteria

- Multi-chunk drafts read naturally.
- Stitch pass can be disabled.
- If stitch pass fails, the app returns the joined chunk output instead of losing work.

## Phase 6: Use Persona v2 Fields During Inference

### Problem

Persona v2 fields are persisted, but `process_fast_lane()` mostly uses `load_personas()`, the legacy `{name: prompt}` view.

### Changes

Add:

- `get_persona_runtime(name)`: returns normalized v2 persona plus default prompt fallback.
- `compose_persona_system_prompt(persona)`: combines prompt, format, dictionary scope, and guardrails.
- `compose_persona_messages(persona, user_text)`: returns chat messages with optional few-shot examples.

Use:

- `persona.temperature` to override generation temperature.
- `persona.format.caps`, `punctuation`, and `signoff` in system instructions.
- `persona.few_shot` as actual assistant/user example turns when calling the API.
- `persona.model_hint` later for model routing, but initially expose it as metadata only unless the model exists and is installed.

Files:

- `llm_engine.py`
- `server.py`
- `tests/test_llm_persona_management.py`
- `tests/test_server_persona_routes.py`

### Acceptance Criteria

- A persona with `temperature=0.8` causes `_call_api()` to receive `0.8`.
- Few-shot examples appear as separate chat messages, not only text in the system prompt.
- Prompt-only legacy personas behave the same as today.
- Invalid rich persona fields still normalize safely.

## Phase 7: Persona Builder Robustness UI

### Add Builder Controls

Add fields to the persona wizard:

- Output policy: preserve length, tighten, expand slightly, summarize.
- Few-shot examples: raw input and desired output pairs.
- Safety mode: strict rewrite only, allow light answering, creative transformation.
- Per-persona max completion tokens.
- Per-persona chunk size.
- Prompt lint warnings.
- Test panel: run sample utterances before saving.

Files:

- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- `app/src/renderer/api/backend.js`
- `server.py`
- `llm_engine.py`

### Prompt Lint Rules

Warn when:

- Prompt does not say to output only rewritten text.
- Prompt asks the model to answer questions while using strict cleanup mode.
- Prompt says both "match length exactly" and "expand".
- Prompt is too long relative to configured chunk size.
- Persona has high temperature with strict cleanup mode.

### Acceptance Criteria

- Persona save shows useful warnings but does not block unless invalid.
- Test panel can run a sample through the current persona.
- Few-shot examples persist through GET/POST `/personas`.

## Phase 8: Review and Notification Behavior

### Desired User Flow

Short dictation:

1. User records.
2. App transcribes.
3. Gemma cleans text.
4. Review overlay opens.

Long dictation:

1. User records a long thought.
2. App shows "Long recording detected."
3. App shows chunk progress.
4. Optional stitch pass runs.
5. Review overlay opens with final draft and token/word summary.

Must-have notification:

- If chunk count is greater than 1, show a visible status notification.
- If processing exceeds 8 seconds, keep status visible and update progress.
- If processing fails, show draft error and recovery option.

Files:

- `server.py`
- `app/src/renderer/main.js`
- `app/src/renderer/overlay.html`
- `app/src/main/ipc.js`

## Phase 9: Wake Word MVP

### Problem

The app has hotkeys, dashboard buttons, and controller triggers, but no hands-free activation path.

`AudioRecorder` should stay focused on active recordings. Always-listening wake detection should be a separate service so it can be started, stopped, tested, and disabled cleanly.

### Changes

Add a new service:

- `wake_word.py`

Responsibilities:

- Own a passive `sounddevice.InputStream`.
- Load one wake detector adapter.
- Apply cooldown/debounce.
- Call `HotkeyManager.request_start(reason="wake_word")` on detection.
- Optionally pair with auto-stop-after-silence so the user can say the wake phrase, dictate, and stop naturally.

Profile fields:

- `wake_word_enabled`: default `false`.
- `wake_word_engine`: default `openwakeword`.
- `wake_word_model_path`: default empty.
- `wake_word_threshold`: default `0.55`, range `0.05-0.99`.
- `wake_word_cooldown_ms`: default `2500`, range `500-30000`.
- `wake_word_requires_vad`: default `true`.

Runtime endpoints:

- `GET /runtime/wake-word/status`
- `POST /runtime/wake-word/start`
- `POST /runtime/wake-word/stop`

Files:

- `wake_word.py`
- `server.py`
- `utils.py`
- `requirements.txt`
- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- `tests/test_wake_word.py`
- `tests/test_server_platform_runtime.py`

### Engine Choice

Start with an adapter interface, then implement `openWakeWord` first.

Adapter shape:

```python
class WakeDetector:
    def predict(self, audio_chunk: np.ndarray, sample_rate: int) -> dict:
        return {"detected": False, "score": 0.0, "label": ""}
```

`openWakeWord` is the preferred first implementation because it is local, open-source, supports pre-trained models, and supports custom model training. Keep `Porcupine` as a possible optional adapter later, not the default, because it requires an AccessKey/vendor account.

### Acceptance Criteria

- Hands-free mode is off by default.
- Enabling wake word starts a passive listener and reports status.
- Detection starts recording through the same runtime path as hotkeys.
- Disabling wake word fully releases the mic stream.
- Wake listener errors appear in `/runtime/status` and the dashboard.

## Phase 10: Auto-Stop After Silence

### Problem

Hands-free mode needs a natural stop condition. Without it, the user still has to press a key or button after a wake-triggered recording.

### Changes

Add a streaming silence detector around active recording chunks.

Profile fields:

- `auto_stop_after_silence_enabled`: default `false`.
- `auto_stop_silence_ms`: default `900`, range `250-5000`.
- `auto_stop_min_recording_ms`: default `700`, range `0-10000`.
- `auto_stop_rms_threshold`: default reuse `no_audio_min_rms` unless explicitly set.
- `auto_stop_peak_threshold`: default reuse `no_audio_min_peak` unless explicitly set.

Implementation:

- Compute per-chunk RMS/peak in `AudioRecorder._audio_callback()`.
- Feed chunk stats into a small pure state machine.
- If recording has speech and then trails into silence for the configured duration, call `request_stop(reason="trailing_silence")`.

Files:

- `recorder.py`
- `audio_gate.py`
- `hotkey_manager.py`
- `server.py`
- `utils.py`
- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- `tests/test_audio_gate.py`
- `tests/test_hotkey_manager_tts.py`

### Acceptance Criteria

- Short pauses inside a sentence do not stop recording.
- A wake-triggered recording stops after sustained trailing silence.
- Manual toggle mode is not forced to auto-stop unless the profile enables it.
- Stop reason is persisted in draft recording metadata.

## Phase 11: Missed-Release Watchdog

### Problem

Push-to-talk and controller PTT can get stranded if key-up/controller-up is missed by the OS, compositor, or device.

### Changes

Add a max recording duration watchdog.

Profile field:

- `max_recording_seconds`: default `120`, range `5-1800`.

Implementation:

- Start a timer when `_start_recording()` succeeds.
- Cancel it when `_stop_recording()` runs.
- If it fires, call `_stop_recording(reason="watchdog_timeout")`.
- Broadcast a warning status so the user knows recording was stopped for safety.

Files:

- `hotkey_manager.py`
- `server.py`
- `utils.py`
- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- `tests/test_hotkey_manager_tts.py`

### Acceptance Criteria

- A simulated stuck PTT stops at the configured timeout.
- Normal stop cancels the watchdog.
- The UI shows a clear status such as "Recording stopped after max duration."

## Phase 12: Confidence-Gated Send Policy

### Problem

Confidence is rendered in the dashboard, but it does not yet protect send behavior.

### Changes

Add a safety policy that decides when a draft is allowed to auto-send or must go through review.

Profile fields:

- `confidence_force_review_enabled`: default `true`.
- `confidence_force_review_below`: default `0.55`, range `0.0-1.0`.
- `confidence_auto_send_above`: default `0.85`, range `0.0-1.0`.

Policy:

- If confidence is missing, review first.
- If confidence is below `confidence_force_review_below`, review first.
- If draft is long, review first.
- If no-audio gates fired, review first.
- Only allow auto-send when confidence is high, draft is not long, and the selected profile explicitly allows auto-send.

Files:

- `server.py`
- `utils.py`
- `app/src/renderer/main.js`
- `app/src/renderer/index.html`
- `tests/test_server_drafts.py`
- `tests/test_pipeline_flags.py`

### Acceptance Criteria

- Low-confidence drafts always open review.
- High-confidence short drafts can use the existing auto-send path if enabled.
- The reason for forced review is visible in draft metadata or status details.

## Phase 13: Wake Word Test Harness

### Problem

Wake-word quality cannot be trusted from a happy-path manual test. It needs repeatable false-accept and false-reject checks before becoming a daily-driver feature.

### Changes

Add a local probe tool:

- `tools/wakeword_probe.py`

Probe behavior:

- List available wake engines.
- Listen to the mic and print score/detection/cooldown.
- Optionally call `POST /runtime/recording/start` on detection.
- Write a small JSONL log of scores for later tuning.

Add fixture folders:

- `tests/wake_fixtures/positive/`
- `tests/wake_fixtures/negative/`

Add tests:

- Positive wake phrase clips cross threshold.
- Negative clips stay below threshold.
- Cooldown prevents repeated triggers.
- Fake detector adapter can test server behavior without heavy ML deps.

Files:

- `tools/wakeword_probe.py`
- `wake_word.py`
- `tests/test_wake_word.py`
- `tests/wake_fixtures/README.md`

### Acceptance Criteria

- Wake-word logic is testable without a live microphone.
- The probe can tune thresholds on a real machine.
- Fixture tests can run in CI with a fake detector, and real-model tests can be opt-in.

## Test Plan

Unit tests:

- Profile migration for new token fields.
- Token cap reaches `_call_api()`.
- Sentence chunking preserves boundaries.
- Chunk progress callback fires expected statuses.
- Stitch pass fallback returns joined chunks on API failure.
- Persona v2 temperature/few-shot/format affect composed API payload.
- Legacy persona prompt behavior stays unchanged.
- Wake detector adapters debounce and cooldown correctly.
- Auto-stop silence state machine handles speech, brief pauses, and trailing silence.
- Missed-release watchdog stops stranded recordings.
- Confidence-gated policy forces review for low-confidence drafts.

Integration tests:

- Fake long transcript through `process_recording_result()`.
- Assert statuses include `long_recording_detected` and `chunking_progress`.
- Assert final draft has `chunk_count`, `token_count`, and `long_text` metadata.
- Fake wake-word detection starts recording through the existing runtime path.
- Simulated trailing silence stops a wake-triggered recording.

Renderer tests:

- Settings accept token cap above 1200.
- Long recording statuses update the status rail.
- Persona wizard saves few-shot examples and reloads them.
- Wake-word settings persist and reflect runtime status.
- Confidence policy settings validate in range.

Manual QA:

- Dictate a short sentence.
- Dictate a 5 minute long thought.
- Use strict cleanup persona.
- Use creative expansion persona.
- Force a chunk failure and verify draft recovery.
- Enable wake word and verify it starts recording.
- Verify wake-triggered recording auto-stops after trailing silence.
- Hold PTT past max duration and verify watchdog stop.
- Mumble a phrase and verify confidence forces review.

## Suggested Order

1. Raise and rename token cap safely.
2. Pass max completion tokens into initial cleanup.
3. Add sentence-aware chunk helper and tests.
4. Add chunk progress broadcasts and renderer messages.
5. Add optional stitch pass.
6. Wire persona v2 runtime fields into `process_fast_lane()`.
7. Expand the persona wizard UI.
8. Add confidence-gated send/review policy.
9. Add missed-release watchdog.
10. Add auto-stop-after-silence.
11. Add wake-word adapter shell and fake-detector tests.
12. Add wake-word probe tool.
13. Add real openWakeWord integration behind a disabled-by-default flag.

## Risks

- Higher completion caps can slow small machines.
- Larger outputs may make review overlays feel heavy.
- Stitch pass can accidentally summarize unless prompt and tests are strict.
- Few-shot examples consume context; cap them to a small count, likely 3 to 5.
- Per-persona model routing can cause surprise downloads if not gated.
- Wake-word false accepts can be disruptive; keep disabled by default and require threshold tuning.
- Always-listening mode has trust/privacy implications; surface it plainly in the UI.
- Auto-stop can cut off slow speakers if thresholds are too aggressive.
- Watchdog timeout must be long enough not to punish legitimate long recordings.

## Recommended Defaults

- `max_completion_tokens`: `1600`
- `max_completion_tokens` max: `4096`
- `long_draft_warning_words`: `1200`
- `llm_chunk_size`: keep `750` initially
- `long_recording_stitch_pass_enabled`: `true`
- Few-shot max examples: `5`
- Chunk overlap: `40` words
- `wake_word_enabled`: `false`
- `wake_word_threshold`: `0.55`
- `wake_word_cooldown_ms`: `2500`
- `auto_stop_after_silence_enabled`: `false`
- `auto_stop_silence_ms`: `900`
- `max_recording_seconds`: `120`
- `confidence_force_review_enabled`: `true`
- `confidence_force_review_below`: `0.55`
- `confidence_auto_send_above`: `0.85`
