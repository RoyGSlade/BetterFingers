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
| OR-13 | Selected-text TTS hotkey doesn't read the selection | **UNQUALIFIED.** The accepted X11 evidence covers only source `Ctrl+Alt+R` selection rewrite into a review-only draft; it does not qualify selected-text TTS. Wayland and Windows operator runs remain open; retain an honest unavailable-selection message. |
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

---

## STATUS AFTER WAVE 14 · 2026-07-31 (director)

This is a historical Wave 14 status snapshot. Current branch/remote state must
be reconciled from `git status` and `git log` before publication. The counts
below are historical unless explicitly dated otherwise.

### Fixed — but nobody has watched them run

These are code-complete and unit-tested. Not one has been exercised in a live
GUI, and several are in the most device-dependent paths in the app. **Rebuild
first** (`npm run build` in `app/`) — the QA harness tests the BUILT renderer.

| | Item | What to look for |
|---|---|---|
| OR-01 | Auto Submit | Toggle it on: you should get a confirmation naming the focus risk, and a red banner that stays while it is armed. Decline it — it must revert. |
| OR-02 | Startup screen | Watch a cold boot. Service rows should appear only as `/doctor` reports them, and it must NOT declare failure early. |
| OR-06 | Audio defaults | Fresh profile: picker reads "System default", not blank. Then record silence — expect the "I can't hear you" toast with a working link. |
| OR-07 | Model download | Download Whisper Tiny and watch it. Progress, then verification, then "Installed and Ready". |
| OR-09 | Voice cloning | With the model absent, the control should say so up front and offer install — not accept a recording and fail after. |
| OR-12/14/15 | Voice Studio | Preview must play **your recording**, not TTS. Presets persist with Apply/Make active/Rename/Duplicate/Delete. Read Aloud has Play/Pause/Stop/Restart. |
| OR-18 | Diagnostics | Rows should match what `/doctor` actually returns — no row for a subsystem it did not mention. |
| OR-19 | Stress Test | The button is disabled and points at Diagnostics. It no longer sends anything. |

### Fixed with a caveat — please re-test these specifically

| | Item | The caveat |
|---|---|---|
| OR-03 | LLM Always On | Readiness now comes only from the `llm_ready` probe. Should be solid. |
| OR-04 | False hotkeys error | **The literal string "Hotkeys fetch failed" does not exist anywhere in `app/src`.** The class of bug that produces false hotkey errors is fixed, but I cannot prove that exact message is gone. If you still see it, tell me the screen and I will find the real source. |
| OR-10 | Persona test | Studio now frames the sample as rewrite material and shows persona/settings. But the **backend still receives it as a final `user` message** — the root cause is a backend contract change outside this wave. Expect improvement, not a cure. |
| OR-11 | Active persona | Badge and "Make active" exist in Studio; persisting global activation needs a host callback that is not wired yet. |
| OR-05 | STT confidence | One real scale bug fixed (a perfect segment was scored as the worst possible one). **The threshold is untouched and is your decision.** Also: your "passed at ~35%" case cannot be the default auto-send gate under current settings — that was a manually invoked send, a different path. |

### Still open

| | Item | Why it did not land |
|---|---|---|
| OR-08 | Runtime/model incompatibility | The runtime contract does not carry the data. It reports backend/runtime/blend capability, **not** supported TTS model or voice IDs. Building the filter anyway would mean inventing a mapping and presenting a guess as a guarantee — the exact defect class this wave exists to remove. Needs a backend capability first. |
| OR-13 | Selected-text TTS hotkey | **UNQUALIFIED.** The accepted X11 result covers source `Ctrl+Alt+R` selection rewrite only, not selected-text TTS. Require separate X11 TTS, Wayland, and Windows operator evidence, with an honest "cannot read your selection here" message when selection is unavailable. |
| OR-16 | Talk volume slider | A worker reported no such slider exists in production markup. **Unconfirmed — needs your eyes.** If you can still see it, tell me where. |
| OR-19 | Real stress test | The injection behaviour is gone, but the actual latency/throughput probe (Light/Medium/Hard, STT/rewrite/TTS timings, CPU/RAM/VRAM) has not been built. It belongs in Pipeline Latency / Diagnostics. |
| P2 | Scribe, nav restructure, Custom Voice modal | Not started. Backlog by your own ordering. |

### Two decisions that are yours, not mine

1. **OR-05's threshold.** The gate works and reads the right fields, but the
   score is a heuristic, not a calibrated probability. Candidates and their
   tradeoffs are in `.collab-reports/w-stt.md`. I deliberately had the worker
   not pick a number — it trades a false reject against a wrong send, and that
   is your tolerance to set.
2. **OR-13's approach.** Selected-text TTS remains unqualified and needs
   separate per-platform operator evidence plus an honest unavailable-selection
   message; the accepted rewrite run does not resolve this decision.

---

## UPDATE — 2026-08-04 (Scribe routing and rewrite review)

Primary Scribe routing and its compose → selected-persona local cleanup → review
surface are **code-complete**. The source selected-text rewrite hotkey
(`Ctrl+Alt+R`) is live-qualified on Linux X11 in two isolated targets and
remains review-first: it must not auto-replace or send text. This does not
qualify selected-text TTS (OR-13), general push-to-talk/injection, Wayland,
Windows, package, audio, hardware, or reliability gates.

Selection capture remains display-server dependent. The accepted source X11 run
used xed and a fresh Chrome textarea; X11 dependencies included `DISPLAY`,
`xclip` (or `xsel`), and `xdotool`. Wayland remains best-effort and requires a
native target host/tools/compositor/portal; tool presence alone is not
qualification. A host where capture is not available must show that honest
failure rather than imply that text was captured.
The broader Scribe notebook asks — projects, pages, autosave, and recovery —
remain separate work if they are not implemented. This update does not change
the unrelated release blockers or make a publishability claim.

Qualification on 2026-08-04: the current source passed the real X11
selection-rewrite workflow in xed and a fresh Chrome textarea. The accepted
interactive evidence recorded **8/8 canonical checks PASS** across the two
targets: selected-text capture, review-only rewrite draft, clipboard restore,
and no automatic send. The artifact row remained `UNTESTED`; this is not
package qualification. The 2026-08-03 `410/28/0` run is historical targeted
parity evidence; current authoritative Gate 11 is `411/27/0`.

The accepted X11 rewrite run observed the configured runtime ready for this
source workflow; no general model, selected-text TTS, package, or release
qualification follows. Selected-text TTS (OR-13), Wayland, Windows,
clean-machine install, signing, audio, hardware, and reliability remain
unqualified/open. A packaged selection operator is pending; do not claim a
packaged selection PASS unless its report and matching final artifact hash are
present.

## UPDATE — 2026-08-04 (Wave 14 operator re-test, Luna worker)

The built renderer was rebuilt from the current checkout with `npm run build`
before testing. The focused automated checks covering the Wave 14 RED repairs
completed cleanly: **294/294 renderer tests passed** across boot readiness,
runtime truth/hotkeys, Auto Submit acknowledgement, Talk capture/download
feedback/no-input guidance, Utilities downloads/diagnostics/audio defaults,
voice cloning, Voice Studio, model compatibility, latency probing, and the
task-#3 persona/runtime tests; **77/77 Python tests passed** across selection
capture, Windows restoration, qualification helpers, STT confidence, and voice
clone QA (2 subtests also passed). These are mechanism checks, not human audio,
hardware, usability, or package qualification.

The full built Electron production QA board was **NOT RUN** in this worker
environment: Electron exited before the first scenario with `Missing X server
or $DISPLAY` / `The platform failed to initialize`, and neither `xvfb-run` nor
`Xvfb` is installed. The checked-in production report therefore remains the
older **83/99** artifact and must not be relabelled as a current post-rebuild
run. No live operator checks were performed, including startup timing, audio
input/output, hotkey behaviour, model download UX, voice playback, hardware,
Wayland/Windows, or package smoke.

No deterministic release-blocking RED was reproduced in the focused checks, so
this re-test made no product or test-file changes. OR-01, OR-02, OR-03, OR-04,
OR-06, OR-07, OR-09, OR-12, OR-14, OR-15, OR-17, and OR-19 remain subject to
the human/live qualification steps above; passing unit tests does not convert
them into operator sign-off. OR-05, OR-08, OR-10, OR-11, and OR-18 remain in
the separate task-#3 ownership/open-status lane described above.

## UPDATE — 2026-08-04 (release director final automated re-test)

The release director rebuilt the current `release/v1.1.0-alpha.1` working tree
on a host with `DISPLAY=:0` and ran the complete production Electron board with
isolated BetterFingers and Electron data roots. The canonical result is now
**100/100 PASS**, recorded in
`app/tests/qa/out/signal-desk-prod/qa-report.md`. The run found and closed four
deterministic issues before the final pass: echoed Persona Studio transport
markers, a permanently hidden persona-teaching panel, stale Library QA routing,
and two permanently hidden late-wave disclosure/workflow groups. The default
route assertion was also reconciled to the actual five primary workspaces.

Final automated release evidence is **3177 Python tests passed / 4 skipped / 26
subtests**, **1772/1772 renderer tests**, a green production build, parity
**410 wired / 28 intentional_cut / 0 blocked / 438 total**, npm audit **0
vulnerabilities**, and Bandit **0 medium / 0 high** in the shipping-backend
scope. These automated results do not qualify human audio, model quality,
hardware, Wayland, Windows, clean-machine installation, or release artifacts.

The reported model-loading failure reproduced for distil Whisper: both distil
sizes mapped to nonexistent Hub repository IDs, and the installed-cache parser
did not recognize the valid `faster-distil-whisper-*` prefix. The mapping and
cache discovery are corrected and an isolated backend inventory/load-probe
smoke passes. No multi-gigabyte model was downloaded or loaded during this
release run, so live LLM/STT/TTS artifact qualification remains external.
