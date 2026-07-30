# OPERATOR REVIEW — 2026-07-30

Donaven's hands-on pass. Consolidated from his notes, triaged by the release
director, and treated as **the authoritative statement of what this product is
actually like to use.** Where it contradicts `PUBLISH_PLAN.md`, this document
wins — the plan was written from the code, this was written from the app.

**Headline: the §2 publishable bar is NOT met.** The plan assumed operator QA
would surface polish. It surfaced core reliability defects, one safety defect,
and two subsystems that need redesign rather than repair. That is not a failure
of the QA process — it is the QA process doing precisely its job, at the only
moment it could. See [Release impact](#release-impact).

---

## P0 — safety and correctness. Nothing ships past these.

### OR-01 · Auto Submit presses Enter in whatever window has focus, unwarned · **RED**
- **Where:** `injector.py:539-556` (`send_output` → `paste_text` then
  `_press_key("enter")`); the toggle is a bare row at `signal-desk.html:2581`.
- **Verified by director:** the injection path unconditionally presses Enter
  after pasting, into the OS-focused window. **There is no warning text anywhere
  in the UI** — the setting reads "Auto submit" and nothing else.
- **Operator also observed** it appears to inject as soon as LLM processing
  begins rather than on completion, i.e. partial output.
- **Why this is the top item:** every other bug in this review costs the user
  time. This one can send half-written text into their Slack, their terminal, or
  a customer email, and press Enter on it. It is the only finding that can do
  damage outside the app.
- **Required:** inject only completed output; a prominent warning naming the
  focus risk; explicit acknowledgement before the toggle can be enabled.

### OR-02 · UI reports "Listening" before the backend is ready · **RED**
- Talk shows *Listening* while the backend, audio pipeline and models are still
  coming up. The app claims a state it is not in — the exact class of dishonesty
  §5.5 and the plan's "nothing claims success that didn't happen" rule forbid.
- **Required:** a startup screen with real states — Starting backend / Loading
  models / Initializing audio / Ready / Failed (with a usable error) — and
  backend+frontend connection status surfaced in Runtime Diagnostics.

### OR-03 · LLM turns itself off despite "Always On" · **RED**
- Configured Always On, runtime silently off. The UI shows the *saved setting*
  rather than the *actual runtime state*, so the two disagree with no signal.
- **Required:** UI reflects runtime truth; a clear reason surfaced when the LLM
  cannot start.

### OR-04 · False "Hotkeys fetch failed" while hotkeys work · **RED**
- A working subsystem reports failure. Trains the user to ignore errors, which
  is worse than the false message itself.
- **Required:** separate genuine failures from delays and empty responses.

### OR-05 · STT confidence score passes badly wrong transcriptions · **RED**
- Operator repro: "testing" spoken six times transcribed as "feeding", still
  scored a **pass at ~mid-30%**.
- A confidence score that passes a wholesale word error is worse than no score —
  it launders a bad transcription as a checked one.
- **Required:** document what the score means, re-derive the threshold against
  known-bad transcriptions, and consider surfacing average token confidence,
  lowest-confidence word, and an overall quality label.

### OR-06 · Audio devices don't default to System Default · **RED**
- Should start on System Default, persist a device only on deliberate selection,
  and fall back when a device is disconnected or renamed. Today a stale device
  binding can leave the user with no working audio and no explanation.

---

## P1 — broken primary workflows

| ID | Finding | Notes |
|---|---|---|
| OR-07 | **Model download gives almost no feedback** (Whisper Tiny) | Needs a real download panel: name, type, download size, installed size, purpose, quality/speed tradeoff, recommended hardware, install location, progress, **verification**, explicit "Installed and Ready". Partially related to D-3, which fixed the *silent on-demand* download in Talk — this is the *explicit* Utilities flow and is still open. |
| OR-08 | Runtime/model incompatibility not prevented | Only offer models the selected runtime can use; confirm the smallest supported TTS model is correctly identified. |
| OR-09 | Voice cloning offered without its model | The control must state a model is required and route to the download flow, not fail later. |
| OR-10 | **Persona test is incoherent** | Sometimes answers the user instead of demonstrating the persona; sometimes refuses; sometimes generic. Needs a defined contract (voice / tone / formatting / boundaries / rewrite), isolation from normal chat, and a display showing input, rewrite, active persona, settings. |
| OR-11 | Active persona selection buried in Settings | Belongs in Studio, switchable across all personas, with the globally-active one clearly marked. |
| OR-12 | **Read Aloud unstable** | Must honour the active voice/blend and expose Play / Pause / Stop / Restart. |
| OR-13 | Selected-text TTS hotkey doesn't read the selection | Expected: highlight in any app → hotkey → BetterFingers reads it in the active voice. Needs an honest notification when nothing is selected. |
| OR-14 | Recording preview plays TTS, not the recording | Must play the user's own sample, show duration and playback state, and allow discard/rerecord. |
| OR-15 | Saved voice blends don't appear after creation | Must be listed, editable, renamable, duplicable, deletable, with the active one marked. |
| OR-16 | Talk volume slider does nothing | Remove it. A control with no audible effect is a lie about capability. |
| OR-17 | Delivery control emits three unsolicited alternatives | Distinct from the Talk delivery selector cut in D-0036 — this is the Studio/Settings **speech delivery** path (`signal-desk.html:2694`). Clicking a setting should apply it. Also clarify whether it affects text rewriting, spoken TTS, or both. |
| OR-18 | Runtime Diagnostics bugged / misaligned | Should show backend, frontend, LLM, STT, TTS, audio devices, loaded models, hotkey service, recent errors. |
| OR-19 | Stress Test is not a stress test | Currently appends prompt-injection text to a request. Move out of Persona Studio into Pipeline Latency / Diagnostics, with Light / Medium / Hard modes reporting STT, rewrite, TTS and total latency, CPU, RAM, GPU/VRAM, failures and timeouts. |
| OR-20 | Wake Word fetch/loading failure | **May already be fixed** — `098dfba` (00:55 tonight) repaired the backbone list, which never rendered at all, and the badge that could never read "Ready" (QA-UTIL-001). **Needs a re-test on current HEAD before any further work.** |

---

## P2 — structure and scope (redesign, not repair)

### Information architecture
- **Scribe** replaces Library in primary nav; rename Text & Playground → Scribe.
- Move **Library, History, Runtime Diagnostics, Game Mode** under Utilities.
- Scribe: persona switching inside it; left sidebar for drafts / projects /
  pages; centre writing surface; autosave; obvious draft recovery. Deliberately
  a lightweight notepad, not an imitation word processor.
- Define the vocabulary and hold it: **Drafts** = editable working documents;
  **History** = prior generated/rewritten/spoken/injected content;
  **Library** = saved reusable material.

### Voice system — replace, don't patch
Retire the separate Voice & Delivery workflow for a single **Make Custom Voice**
modal: Name → Voice blend (add/adjust/remove contributors) → Pause & speaking
style → Modulation (pitch, speed, energy) → Test with sample text → Save as
reusable preset. Modulation belongs *inside* this flow, not as a disconnected
feature.

### Hide until real
Wake Word (pending OR-20 re-test), Launch Workflows, Teach Prompts, Contact
Audience, Speech Delivery, Why This Works, Example Rewrites.

### Remove
Instant Type · the dead Talk volume slider · the standalone Voice & Delivery
workflow once Custom Voice lands.

### Trim
Theme screen carries explanatory prose that should be tooltips or disclosure.

---

## Release impact

**`v0.2.0-alpha.1` cannot ship on the current bar.** Stating it plainly:

- **Gate 11 remains legitimately ACCEPTED.** It is a *parity* gate — every
  inventory row is wired or ruled — and that is still true. It was never a
  statement that the product works well, and D-0044 says so explicitly.
- **The §2 "publishable" definition is not met.** It requires the operator QA
  checklist completed with all RED findings fixed. There are **six REDs**, one
  of which (OR-01) can damage data outside the application.
- **The wave's automated evidence remains valid and is not invalidated by this.**
  99/99 board, 1668/1668 node, 3098/0 python, 0 blocked rows. Those tests
  verified the things they cover. This review is a measurement of everything
  they *don't* cover — which is why it was always the deciding gate.

**Recommendation:** treat this review as Wave 14's scope. Phase 1 below is the
minimum that makes an alpha defensible; the redesign work (Scribe, Custom Voice,
navigation) is a genuine second release, not a polish pass. Do **not** attempt
Phase 4 before Phase 1 — shipping a redesigned voice system on top of a backend
that turns itself off would waste both efforts.

### Order (operator's, adopted as-is)

1. **Stop presenting broken states** — startup readiness, LLM Always On, audio
   defaults, false hotkey error, download progress + verification, recording
   preview, **Auto Submit safety first within this phase**.
2. **Simplify the visible alpha** — hide unfinished features, remove dead
   controls, rename to Scribe, move Library/History/Diagnostics to Utilities,
   persona selection into Studio.
3. **Repair primary workflows** — persona testing, Read Aloud, selected-text
   TTS, Scribe drafts/projects, Runtime Diagnostics, confidence scoring.
4. **Voice system redesign** — Custom Voice modal, blend editing, modulation,
   cloning prerequisites.
5. **Polish** — theme text, status messaging, model guidance, latency modes,
   consistency sweep.

---

## A note on process

Six REDs reached a release candidate that had passed 99/99 scenario tests, a
1668-test node suite, a 3098-test python suite, and a 438-row parity audit.

That is not an argument that the automation is worthless — it caught four REDs
of its own during the wave, including a silent 150 MB download and a model list
that never rendered. It is an argument about what automated evidence *is*: it
proves the mechanisms it was pointed at. It cannot tell you that "Listening"
appears before the backend is up, that a confidence score passes a wrong word,
or that a toggle will press Enter in someone's terminal.

The plan's §2 ordering was right to put operator QA before the packaging gates.
The mistake would be reading a green board as permission to skip it.
