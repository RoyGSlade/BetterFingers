# Wave 12A, Objective A — native form controls on Signal Desk

Supervisor: `sup-ui-polish`. Opus-only, no workers spawned (budget directive).

Objective B (data-root/persona-loading probes, `sup-dataroot`) is covered
separately in [`WAVE12A_PROBE_EVIDENCE.md`](WAVE12A_PROBE_EVIDENCE.md), which
also folds in what `probe_wave12a/`'s scratch scripts established. That
directory is still on disk as of 2026-07-29 — its removal is blocked on an
operator action; see the probe-evidence doc's opening note.

Source: five verbatim product-owner findings from a hand-test of the flipped
build. These are user reports, not audit rows.

| # | Reported | Root cause | Fixed by |
|---|----------|------------|----------|
| 1 | "big arrows in text lines meant for dropdowns look terrible, out of place, wrong size, no distinguishable backplate" | 35 of 36 `<select>` never set `appearance:none`; the native GTK arrow was drawn | element-level `select` rule |
| 2 | "pause style brings up black text hard to see options" | `.sd-review-select option { color: #000 }` + platform-dark popup | rule deleted; `select option` colors + `color-scheme: dark` |
| 3 (UI half) | cannot see which voice is selected, nor what voices exist to blend | the selection lived only inside a closed native select; the blend roster was never listed anywhere | `#voiceActiveVoiceName`, `#sdVoiceBlendAvailable`, blend empty-state sentence |
| 4 | "remove button on blend voices looks like a generic html button, and the choose file button" | `voiceStudio.js` emitted base.css-only class names; `input[type=file]` had no styling at all | module emits `sd-` primitives; `::file-selector-button` treatment |
| 10 | "the dropdowns look like blank html and its awful, buttons oversized" | `.sd-select`/`.sd-button--ghost` undefined; the page font was declared only on `.sd-shell` | element-level rules + `font-family` on `:root` |

## The one cause

`app/src/renderer/signal-desk.html` links **exactly one** stylesheet
(`styles/signal-desk.css`) and nothing else. That file styled controls only
through per-family **classes**. Anything the page or a feature module rendered
without one of those classes fell back to the browser's Chromium/GTK widget on
a `#0A0E14` page.

Measured before the fix:

* **36 `<select>` across six class families** — `.sd-input`,
  `.sd-util-select`, `.sd-set-select`, `.sd-review-select`,
  `.sd-library-filters__control`, `.sd-select`. Exactly **one**
  (`.sd-review-select`) set `appearance: none`.
* **`.sd-select` was never defined** anywhere in the stylesheet.
  `#sdSelectedContactPicker` wore it. So did `.sd-button sd-button--ghost` on
  `#sdSelectedContactApply` — also undefined.
* **`.sd-review-select option { color: #000 }`** — a literal black.
* **43 class names reachable on this page are defined only in
  `styles/base.css`**, which this page does not load.
* **3 `<input type="file">`** with no styling of any kind.

## The fix, and why it is at the element level

Every new rule is keyed on the **element** (`select`, `button`,
`input[type=file]`), specificity 0-0-1. That makes it the floor for every such
control reachable today or added later, while every existing class rule
(0-1-0) still wins where it deliberately differs. A seventh select class can no
longer reintroduce an unstyled dropdown.

### Native popup legibility — the decision

A `<select>`'s option list is drawn by the platform, not the page, so page CSS
does not reach it on Linux/GTK the way it reaches the closed control. Two
options were available:

* **(a) replace all 36 selects with custom listboxes**, or
* **(b) tell the platform what palette to draw in.**

**(b) was chosen.** (a) means hand-reimplementing keyboard interaction,
typeahead, scroll containment and the ARIA listbox pattern 36 times, days
before a release, and each reimplementation is a fresh accessibility
regression surface — for a purely cosmetic win. (b) is two declarations, and
**both** are needed because neither alone covers every platform:

* `color-scheme: dark` on `:root` and on `select` — the standardised signal
  that makes Chromium request the dark native widget set. This repaints the
  popup **chrome**.
* explicit `background-color`/`color` on `option`/`optgroup` — honoured by
  Chromium inside the popup on Linux and Windows. This fixes the **text**.

Result: `#E8EEF4` on `#131A23` ≈ **15.3:1**, verified by the QA scenario
computing the real WCAG ratio rather than eyeballing a screenshot.

### Two defects the new QA scenarios found on their first run

Both were pre-existing, neither was in the five findings, both are now fixed:

1. **The page font was declared only on `.sd-shell`.** Every control outside
   the shell grid — the whole persona wizard, the Foundry, the contact wizard,
   the onboarding flow, the confirm dialogs, the toast close button — inherited
   the UA default and rendered in **Times New Roman**. That is **34 buttons and
   5 selects** on the shipping page. `font-family` now sits on `:root`.
   `font-size` deliberately does **not**: 23 rules in the file use `rem`.
2. **Disabled placeholder options measured 3.20:1** (`--sd-text-muted`) on
   `#sdUtilAudioDeviceSelect` and `#sdUtilGameSetupDelivery` — below AA. A
   placeholder you cannot read is the same complaint the user made about the
   rest of the list, so it was raised to `--sd-text-secondary` rather than
   exempted for being disabled.

### One more, found while wiring the readout

`#settingReviewTtsVoiceHint` (the read-aloud voice select) had **no `change`
listener at all**. Picking a different voice neither marked the profile dirty
nor moved the effective-mix line, so the blend readout could sit there
describing a base the user had already changed away from. Now wired, with a
regression test.

### Also corrected

`.sd-review-select` is worn by four **text/number inputs**
(`#settingReviewTtsSpeed`, `#voicePreviewText`, `#voicePresetNameInput`,
`#voiceCloneName`) as well as by selects, and it hard-coded a chevron
background — so those four inputs each rendered a dropdown arrow they could not
act on. The chevron now comes from the `select` rule, which reaches exactly the
elements that open a list.

All five select families were changed from the `background:` **shorthand** to
`background-color:`. The shorthand resets `background-image`, and a class rule
beats the element rule — so any of them would have silently deleted the chevron
for its whole family. A unit test now guards this.

## Files changed

| File | Change |
|------|--------|
| `app/src/renderer/styles/signal-desk.css` | NATIVE FORM CONTROL CONTRACT block; `.sd-review-select` de-conflicted; five families switched to `background-color`; `color-scheme`/`font-family` on `:root` |
| `app/src/renderer/signal-desk.html` | `#voiceActiveVoiceName`, `#sdVoiceBlendAvailable`; `sd-button sd-button--ghost` → `sd-btn` |
| `app/src/renderer/features/voiceStudio.js` | blend rows and preset rows emit `sd-` primitives; active-voice readout; available-voices sentence; base-select `change` listener |
| `app/src/renderer/features/studioWorkspace.js` | `#sdVoiceBlendAvailable` roster line; "+ Add Voice" names what it added |
| `app/tests/qa/scenarios/ui-controls-prod.mjs` | **new** — 5 production-target scenarios |
| `app/tests/qa/scenarios/index.mjs` | registers the new area |
| `app/tests/uiControlContract.test.mjs` | **new** — 5 static regression guards |
| `app/tests/voiceStudio.test.mjs` | +4 tests |
| `app/tests/studioWorkspace.test.mjs` | +4 tests |

## Why the QA scenarios are computed-style, not screenshot

Every finding here is visual, which is exactly why none of the evidence is an
image:

* A screenshot of a `<select>` shows the **closed** control. Finding (2) lives
  in the **open** popup, which the platform draws in its own window —
  Playwright cannot screenshot it, and a green screenshot of the closed select
  would have "passed" the entire time the bug shipped.
* A screenshot cannot distinguish "styled to look native" from "not styled".
  `appearance` and the presence of a `background-image` can.
* "Buttons oversized" is a font-metric bug, measurable to the character.

Each scenario **enumerates** rather than samples (33 selects, 222 buttons, 3
file inputs) and asserts a non-zero count first, so an `expects` cannot pass
vacuously on a selector that matches nothing.

## Verification

| Check | Result |
|-------|--------|
| `node --test "tests/**/*.test.mjs"` (renderer) | **1533/1533 pass** |
| `npm --prefix app run build` | green |
| `node tests/qa/run.mjs ui-controls-prod` (production target) | **5/5 pass** |
| `node tests/qa/run.mjs` (full production target) | 89/97 — see below |
| `python3 tools/parity_ledger_build.py` | 396 wired / 21 intentional_cut / 21 blocked |
| `python3 tools/parity_validator.py` | OK, 438/438 bound |
| `.venv/bin/python -m pytest` | 3050 passed, 2 failed — see below |

The parity totals are **unchanged**: this wave fixed the appearance of controls
that were already wired, so no row moved. The ledger diff is confined to QA
attribution lines now citing `ui-controls-prod.mjs`.

### Not-mine failures, stated rather than absorbed

* **6 × `onboarding-prod/*`** — self-reporting environmental refusals:
  `enterFirstRunState refuses to run without BETTERFINGERS_DATA_DIR set`. Not a
  regression; the harness is declining to touch a real profile.
* **2 × `overlay-windows/*`** — `capture-overlay-renders-every-pipeline-state`
  and `production-page-drives-both-overlay-windows`. **Unattributed, leaning
  not-mine.** Evidence: (i) the failing assertion is a poll on
  `BrowserWindow.isVisible()` after `status:'idle'`, and that hide path is
  entirely main-process (`app/src/main/ipc.js`, the `alwaysOn` branch) — no
  CSS, no renderer module and no markup participates; (ii) the area is
  non-deterministic here, with a *different* scenario
  (`review-overlay-rewrite-instruct-and-read`) failing on a second consecutive
  run and passing on the first; (iii) `bootstrap/signalDeskApp.js` and
  `features/settingsWorkspace.js` are concurrently modified by `sup-dataroot`
  and were compiled into this build — and `settingsWorkspace.js` is what
  writes the overlay `alwaysOn` setting the failing branch reads.
* **2 × `tests/test_server_platform_runtime.py::*_without_appdata`** — pass
  **15/15 in isolation**, fail only in the full run. Cross-test env pollution
  in the data-root area `sup-dataroot` is actively editing
  (`app_paths.py`, `tests/conftest.py`, the latter now pinning
  `BETTERFINGERS_DATA_DIR`). Zero Python changed in this objective.

## Open findings, reported not fixed

1. **29 class names remain reachable on `signal-desk.html` but undefined in the
   one stylesheet it loads** — down from 43, re-measured after the fix. The
   control-shaped ones this objective owned are fixed at source in
   `voiceStudio.js`; three more (`.secondary-button`, `.settings-input`,
   `.persona-learning-delete-button`, emitted by `features/personas.js` and
   `features/personaLearning.js`) are **bridged** in `signal-desk.css` so the
   shipping page is correct — a bridge is a stopgap, not the fix, and those
   modules should be ported by their owning supervisor. The remainder are
   layout/BEM classes (`few-shot-row`, `foundry-stress-case`,
   `draft-history-item`, `sd-timeline__day`, `sd-context__row`,
   `sd-header__titles`, `textarea-small`, …) that render as unstyled `<div>`s
   rather than browser widgets — out of this objective's scope, but real, and
   `features/personas.js` owns 10 of them.
2. **`.sd-trait-field`** is used five times in `signal-desk.html` and defined
   nowhere, although all five of its BEM children are defined. Harmless today
   (the elements also carry `.sd-field`), but a dangling name.

   Fixed in passing, because it sat on a row this objective was already
   editing: `#sdSelectedContactPicker`'s label carried `sr-only`, another
   base.css-only name — so a label intended to be **screen-reader-only was
   rendering visibly** above the picker. Now `sd-visually-hidden`, the defined
   primitive the rest of the file uses.
3. **`#sdSetTheme` offers System / Dark / Light and the stylesheet has no light
   theme at all** — no `data-theme`/`prefers-color-scheme` rules exist. The
   control cannot do what it says. `color-scheme: dark` was pinned to state
   what actually ships; whoever wires the light theme must revisit that line.
4. **The regenerated ledger now cites `app/tests/personaOptions.test.mjs`**,
   an untracked file belonging to `sup-dataroot`'s in-flight work. The director
   should regenerate at integration time once that lands.

## Suggested commit message

```
Wave 12A-A: one select, one file-input and one button treatment for Signal Desk

The product owner's hand-test of the flipped build produced five findings that
all reduce to one cause: signal-desk.html links exactly one stylesheet, and
that stylesheet styled controls only through per-family classes. Anything
rendered without one of those classes fell back to the browser's own GTK widget
on a #0A0E14 page -- 35 of 36 selects kept the native arrow, `.sd-select` and
`.sd-button--ghost` were never defined at all, three file inputs had no styling
whatsoever, and `.sd-review-select option { color: #000 }` painted black text
into a popup the platform draws dark.

The fix is keyed on the ELEMENT, not the class, so it is the floor for every
control reachable now or added later. For the option list -- drawn by the
platform, not the page -- color-scheme:dark plus explicit option colors were
chosen over replacing 36 selects with custom listboxes: the latter means
reimplementing keyboard interaction, typeahead and the ARIA listbox pattern 36
times, days before a release, for a cosmetic win.

Also fixes what the new QA scenarios found on their first run: the page font
was declared only on .sd-shell, so 34 buttons and 5 selects outside the shell
grid -- every dialog and wizard -- rendered in Times New Roman; and disabled
placeholder options measured 3.20:1, below AA. And the read-aloud voice select
had no change listener at all, so picking a voice neither marked the profile
dirty nor updated the mix readout.

Selected-voice visibility: the active voice and the voices available to blend
are now named in page text, not only inside a closed dropdown.

Evidence is computed-style, never screenshots: the select popup is an OS-drawn
window Playwright cannot capture, so a green screenshot of the closed control
would have passed the whole time the bug shipped. Each scenario enumerates
(33 selects, 222 buttons, 3 file inputs) and asserts a non-zero count first so
it cannot pass vacuously.

Renderer 1533/1533, build green, production QA ui-controls-prod 5/5,
parity 396/21/21 unchanged and validator OK.
```

---

## Director correction to the P0 narrative (2026-07-29)

Commit `2507930`'s message says the `APPDATA` branch of `resolve_base()`
"ignored its value and returned the real `~/BetterFingers`". **That is wrong,
and this note is the correction.**

`_legacy_home_base()` reads `APPDATA` itself and returns
`$APPDATA/BetterFingers` when it is set. So the pre-fix branch already honoured
the variable. Proven by executing the pre-fix source directly: with
`APPDATA=/tmp/probe-appdata`, `resolve_base()` returned
`/tmp/probe-appdata/BetterFingers`, not a path under `$HOME`. The director
asserted the opposite from a partial read and shipped that claim in a commit
message; `sup-dataroot` disproved it by execution. The edit in `2507930` is
behaviour-equivalent (it adds `expanduser`) and is kept, but it did not fix a
destroyer.

**What IS established.** Two test modules deliberately unset `APPDATA` and then
boot a full `TestClient(server.app)`. With `APPDATA` gone, resolution falls
through to the legacy `~/BetterFingers`, and before the marker-file fix a lone
`debug.log` was enough to elect it. That is a real, reproducible write path
from the suite into a live install, and it accounts for the `profiles/` and
`history.db` that appeared in the owner's data root. `tests/conftest.py`'s
`_forbid_real_data_root()` guard caught it immediately, which is the whole
argument for guarding the resolver's answer rather than trusting an env var.

**What is NOT established.** Nothing here proves what deleted the owner's
`models/`, personas, voices and presets. A proven write path is not a proven
delete path. The loss is real and its cause is still unknown; it must not be
written up as solved.
