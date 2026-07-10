# Voice Control Plan — Wake, Control, Edit

Status: in progress, started 2026-07-09. This document exists because the
Wake/Control/Edit proposal overlaps heavily with work already scoped elsewhere.
Rather than re-litigate it, this doc says exactly what's already spec'd (reuse
it), what's genuinely new (spec it here), and in what order to build it.

**Progress (2026-07-09):** Steps 1-4 of the build order below are done —
`utterance_history.py`, `voice_commands.py`, `voice_edit_commands.py`
(including `apply_inline_edits`), `voice_preview.py` (test-panel combinator),
and the `server.py` pipeline wiring (scratch-that early-exit, inline edits,
utterance recording, `editing_commands`/`app_commands` profile flags) are all
merged with green tests. Step 7 (wake-word service shell) is done —
`wake_word.py`'s `WakeWordService`/`FakeWakeDetector`. Step 5 (missed-release
watchdog) is half done — `hotkey_manager.py`'s timer is in, only the one-line
`server.py` callback wiring remains. Still open: the review-overlay/settings
UI wiring (scope 4's frontend half) and real openWakeWord integration.

## How this maps onto existing plans

| Proposal section | Existing coverage | Verdict |
|---|---|---|
| Wake Mode (settings, flow, safety) | `docs/PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN.md` **Phase 9: Wake Word MVP** — `wake_word.py`, adapter interface, `wake_word_*` profile fields, `/runtime/wake-word/*` endpoints, disabled by default | Reuse the spec as-is. Don't re-derive it here. |
| Auto-stop after trailing silence | Same doc, **Phase 10** | Reuse as-is. |
| "Easy kill switch" / stranded recording safety | Same doc, **Phase 11: Missed-Release Watchdog** | Reuse as-is. |
| "Send it should require high confidence or confirmation" | Same doc, **Phase 12: Confidence-Gated Send Policy** | Reuse as-is — this *is* the confirmation policy for risky draft actions. |
| False-trigger log / test panel | Same doc, **Phase 13: Wake Word Test Harness** — `tools/wakeword_probe.py`, fixture clips, fake detector | Reuse as-is. |
| Voice Control Commands (app-level: "send it", "scratch that", "make it shorter", "emergency stop") | Nothing existing. `intent_engine.py` is a state-machine skeleton (mock), not wired to any real actions. | **New** — spec'd below. |
| Voice Editing Commands beyond current formatting subset (scratch that, delete last word, replace X with Y, utterance history) | `docs/MASTER_PLAN.md` lists this as the *second slice* of **C2** ("Phrase history + DictationFormat state machine; command grammar pre-injection") — the first slice (spoken punctuation/structure/casing) already shipped as `dictation_commands.py`. No detailed phase doc exists for the second slice. | **New** — spec'd below. |
| Voice training / calibration (record examples, personalized thresholds, command aliases) | Nothing existing. | **New**, explicitly Phase 2 (after the above ships and is used for a while). |

Existing building blocks to reuse, not rebuild:
- `hotkey_manager.request_start(reason=...)` / `request_stop(reason=...)` — the single entry point wake-word and voice commands both call into.
- `broadcast_status_threadsafe(status, data)` + `/ws/voice_status` — the event channel the overlay already listens on; new command/wake states ride the same pipe, no new transport.
- `macros.py`'s pattern (word-boundary regex, longest-trigger-first, JSON persisted under `get_user_data_path()`, thread lock) — the template for the command-alias store.
- `intent_engine.match_command()` (difflib fuzzy match, threshold-gated) — reuse for command/alias matching instead of a new fuzzy-match implementation.
- `dictation_commands.py` — untouched; it stays the pure formatting pass. New editing commands are a separate module (stateful, needs history) rather than bolted onto this pure one.

Naming collision to avoid: the existing profile flag `voice_commands_enabled` / `voice_commands_enabled()` in `server.py` already gates `dictation_commands.py` (spoken punctuation formatting). The new app-control layer needs a **distinctly named** flag — `app_commands_enabled` — so toggling one doesn't silently toggle the other.

## New scope 1 — Utterance history buffer

Foundation for "scratch that" and for the app-control "read that back" / "make it shorter" commands, which need to know what was just emitted.

New module `utterance_history.py`, in-memory ring buffer (last ~40, mirroring the "phrase history" sizing already named in MASTER_PLAN's C2 entry), each entry:

```python
@dataclass
class Utterance:
    raw_transcript: str
    final_text: str
    emitted_length: int
    target_draft_id: str | None
    timestamp: float
    injected: bool
```

API: `record(utterance)`, `last()`, `pop_last()` (for "scratch that" — returns the entry and removes it), `clear()`. Pure/testable, no I/O. `process_recording_result` in `server.py` appends to it after a draft is created/sent.

## New scope 2 — Voice command intent parser (app-control)

New module `voice_commands.py`. Pure text → intent classification, no side effects — the side effects (calling `perform_output_action`, `emergency_stop_runtime`, etc.) stay in `server.py`, which is what makes this heavily unit-testable.

```python
@dataclass
class VoiceCommandIntent:
    kind: str            # "draft_action" | "app_action" | "unknown"
    action: str           # e.g. "send", "cancel", "read_back", "rewrite_shorter", "emergency_stop"
    confidence: float
    requires_confirmation: bool
```

`parse_command(text, context) -> VoiceCommandIntent | None`

- Matches a fixed action vocabulary (start/stop recording, cancel, read that back, send it, copy it, make it shorter/clearer, try again, switch to formal, open settings, emergency stop) via `intent_engine.match_command`-style fuzzy matching, longest-phrase-first like `macros.py`.
- Conservative by construction: returns `None` (no command) unless invoked from a "clear command context" — the caller passes `context` (`review_overlay_open`, `post_wake_word`, `command_mode_on`, `prefixed`) and the parser refuses to match unless at least one is true. This is what stops "send it" from firing mid-paragraph dictation.
- `requires_confirmation=True` is hardcoded (not configurable down) for: `send`, `delete_history`, and any action tagged destructive. `emergency_stop` always resolves regardless of context gating or confidence — it's the one action exempt from the "clear command context" gate.
- Confidence comes from the fuzzy-match score; below a threshold the parser returns `None` rather than a low-confidence guess.

This is Implementation Order step 1 from the original proposal — pure, no wiring, fully covered by `tests/test_voice_commands.py` before anything touches `server.py`.

## New scope 3 — Voice editing commands (phrase-history aware)

New module `voice_edit_commands.py`, sibling to `dictation_commands.py` but stateful (reads/writes `utterance_history`):

- "scratch that" / "undo that" / "delete that" → `utterance_history.pop_last()`, retract the emitted text.
- "undo last sentence", "delete last word" → operate on `final_text` of the current in-progress utterance, not history.
- "replace X with Y", "capitalize the word X" → targeted find/replace against the last utterance.
- "quote that", "bullet list", "numbered list", "new heading" → structural, extends `dictation_commands._STRUCTURAL` conventions.
- "no punctuation", "literal mode" → per-utterance mode flags that suppress the `dictation_commands`/`voice_edit_commands` passes for the current recording only.

Known personal-mishearing aliases (the training feature in scope 5) plug in here as an extra lookup table consulted before the fuzzy match, same shape as the example in the proposal:

```json
{"canonical": "scratch_that", "phrases": ["scratch that", "delete that", "undo that"],
 "observed_transcripts": ["scratch dat", "scratch debt", "scratched that"],
 "requires_confirmation": false}
```

## New scope 4 — Wire into review overlay + settings UI

- `review-overlay.html` / `main.js`: read/rewrite/accept/cancel actions call the same `/drafts/{id}/...` endpoints that buttons already use — voice just becomes another caller of existing handlers, gated through `voice_commands.parse_command`.
- New Settings → **Voice Control** section: wake word toggle/sensitivity/cooldown (already spec'd fields from Phase 9), auto-stop silence (Phase 10 fields), `app_commands_enabled`, editing-commands enabled, confirmation policy, command prefix (none / "BetterFingers" / custom), and a **test panel** that runs `voice_commands.parse_command` / `voice_edit_commands` against typed or spoken text and shows the resolved intent *without executing it*.
- Overlay state badges: idle / listening (wake active) / recording / `Command: <action>` / `Needs confirmation — say "confirm" or "cancel"`. These ride existing `broadcast_status_threadsafe` events; add `command_detected` and `command_needs_confirmation` status types.

## New scope 5 — Training / calibration (Phase 2, later)

Not started until scopes 1-4 are shipped and used for a bit. When picked up:

1. Command phrase recording + alias learning — record a user saying a command a few times, store `observed_transcripts` per canonical action (extends the JSON shape in scope 3).
2. Wake phrase calibration — record 5-20 examples + negatives, measure detector scores, pick a personalized threshold, surface "reliable / too noisy / needs more samples."
3. Local embedding verifier — phrase fingerprint compared against live audio alongside the base detector score (both must pass).
4. Voice Training settings panel: Wake Phrase Training, Command Training, Sensitivity Test, False Trigger Log, Delete Training Data, Export/Import Voice Profile.

Safety invariant carried through from scope 2: training improves recognition, never lowers the hardcoded `requires_confirmation` floor for destructive actions.

## Build order

1. **Utterance history buffer** (scope 1) — pure, no dependents blocked on it besides 2/3.
2. **Voice command intent parser** (scope 2) — pure, heavily tested, no wiring yet.
3. **Voice editing commands** (scope 3) — depends on 1.
4. **Wire review-overlay actions + settings UI + overlay badges** (scope 4) — depends on 2/3.
5. **Phase 11: Missed-release watchdog** (reuse existing spec) — independent, can slot in anytime; small.
6. **Phase 10: Auto-stop after silence** (reuse existing spec).
7. **Phase 9: Wake-word service shell + fake detector** (reuse existing spec).
8. **Phase 12: Confidence-gated send policy** (reuse existing spec) — ties "send it" confirmation to real confidence numbers instead of a stub.
9. Real `openWakeWord` integration (still Phase 9, later sub-step — heavier dependency, do last).
10. **Phase 13: Wake-word test harness** (reuse existing spec).
11. **Training/calibration** (scope 5) — Phase 2, after real-world use of the above.

Steps 1-4 are this doc's actual new contribution and are being implemented now. Steps 5-10 execute the pre-existing, already-detailed `PERSONA_LONG_RECORDING_ROBUSTNESS_PLAN.md` phases in the order that doc already recommends — no need to duplicate that spec here.
