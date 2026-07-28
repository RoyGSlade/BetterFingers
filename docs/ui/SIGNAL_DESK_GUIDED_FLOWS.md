# Signal Desk — guided flows (SPEC stage 13)

**Status:** design, implementation started.
**Covers:** the four surfaces that had no Signal Desk design at all — onboarding (§2),
Persona Foundry (§3), the manual persona wizard (§7.5.1), and First-Run Setup (§6.1).

Written after the rest of Signal Desk exists, deliberately: the brief was "design it based on
everything else so far", and the useful answer turned out to be *fewer* new patterns rather
than four new screens.

---

## 1. The observation that shapes this

Laid side by side, three of these four are the same shape:

| Surface | What it is |
|---|---|
| Onboarding | 4 steps, forward/back, one gating consent, ends in a saved flag |
| Persona Foundry | 4 screens, forward, model-led Q&A, ends in a saved persona |
| Persona wizard | 4 steps, forward/back, form-led, ends in a saved persona |
| Contact wizard (`CONTACT_WIZARD_DESIGN.md`) | 4–6 questions, model-led, ends in a saved contact |

And two of them produce **the same object**. The Foundry is a model-led persona builder; the
wizard is a form-led persona builder whose step 1 already contains
"✨ Build it with your model" — a miniature Foundry. They were separate because they were
built at different times, not because a user thinks of them as different things.

Porting all four as distinct overlays would carry that duplication into the new UI and then
add a fifth for contacts. So:

> **One guided-flow shell, several flows.** The shell owns stepping, progress, focus, escape
> semantics and the footer. A flow supplies steps and a completion action.

## 2. The shell

`.sd-flow` — a modal dialog, extending the pattern already established by the shortcut sheet
(`.sd-shortcut-sheet`): fixed overlay, centred card, header with title + close, scrollable
body, footer with actions. Nothing new to learn.

```
┌─ sd-flow ─────────────────────────────────┐
│  Title                                [×] │
│  ● ● ○ ○   ← sd-flow__steps (progress)    │
├───────────────────────────────────────────┤
│  sd-flow__body   (per-step content)       │
├───────────────────────────────────────────┤
│  [Back]              [status]   [Next →]  │
└───────────────────────────────────────────┘
```

Shell responsibilities, so no flow reimplements them:

- **Step model** — ordered steps, current index, `canAdvance()` per step.
- **Progress** — dots, with done / current / upcoming states. Purely informational; not
  clickable, because jumping into an unvalidated step is how half-built objects get saved.
- **Focus** — focus moves to the step heading on each transition, and is trapped inside the
  dialog. Focus returns to the trigger on close.
- **Escape** — a flow declares `dismissible: true|false`. Dismissible flows close on Escape;
  gating flows swallow it (onboarding's consent step is the only current case).
- **Footer** — Back is hidden on the first step. The primary button's label is per-step
  (`Get started` / `Accept & continue` / `Next` / `Finish`), matching the existing behaviour
  rather than flattening everything to "Next".

## 3. Friction budget

`ACCOMPLISH.md` §3 rule 2 now carries the owner's constraint that *explicit means chosen
once, not asked every time*. Guided flows are where that is easiest to violate, so:

- **Every flow except onboarding is optional and escapable.** A persona can be created from a
  name alone; the flow is an offer to make it better.
- **Quitting halfway saves what exists** wherever the object is valid without the remaining
  steps. A flow that discards ten minutes of answers because the user closed it teaches
  people not to start one.
- **No flow is a prerequisite for dictating.** The core loop never routes through one.
- **Onboarding is the one gate**, and it stays as short as it is today. Four steps, one of
  which is a legal necessity.

## 4. Where each surface lands

### 4a. Onboarding — shell flow, `dismissible: false`

Unchanged in content: Welcome → data-stays-here consent → how it works → speech models.
The consent checkbox continues to gate the primary button, and Escape stays swallowed. It is
the only flow that may block the app, and only once.

**Decline & quit** stays in the footer, left-aligned, visually separated from the forward
action — it quits the application, and must never sit adjacent to `Next` where a mis-click
lands on it. That separation is measured, not eyeballed: the QA scenario asserts the gap
between the two controls exceeds 30% of the card width, so a future footer reflow breaks
loudly rather than quietly moving an app-exit button under the cursor.

Two implementation notes worth keeping:

- **Step bodies are markup, not template strings.** The shipping overlay builds each body
  with `innerHTML`, which is why every piece of backend text in the recommendation box needs
  an `escapeHtml()` around it. Markup plus `textContent` has no such rule to remember.
- **Listeners bind at construction, not on open.** Binding inside `init()` left the dialog
  half-live for any caller that opened it another way: steps advanced but the consent
  checkbox was inert, which is indistinguishable on screen from a gate that can never be
  satisfied. Caught by QA, now covered by a unit test.

### 4b. First-Run Setup — *not* a flow. It belongs in Talk.

This is the one that should **not** become a dialog. It is a status panel — runtime / language
model / speech model, each present-or-missing with a download action — and it is exactly the
information a new user needs *in front of them*, not behind a modal they dismissed.

It lands as a **banner at the top of Talk**, above the Signal Core, shown only while something
required is missing, dismissible once satisfied. Talk is where a new user starts and where the
absence of a model actually stops them.

This also fixes the bug found earlier in this work: the panel currently latches onto its first
failed probe and advertises "Get BetterFingers set up" on a fully-configured machine. As a
banner driven by live status, "everything installed" simply means it is not rendered.

**Landed.** Same feature module as the dashboard panel — `features/firstRun.js`, mounted via
the new `collectFirstRunElements(doc, { prefix })`. The dashboard builds that element map with
24 hand-written `getElementById` calls in `main.js`; a second hand-written copy for Signal Desk
would have been a guarantee of drift, so the lookup is derived from an id prefix and a test
asserts the default prefix reproduces `index.html`'s ids exactly.

Two additions, both small and both additive (rule 6):

- `hooks.onReady(status)` fires once on the transition to ready, so the banner can take itself
  off screen. The dashboard panel passes none and keeps today's behaviour.
- `lib/message.mjs` — `setMessage` extracted from `main.js`, because the preview page had grown
  a near-copy that set `data-tone` but never removed it: an element that had once shown an error
  stayed red under every later success message.

Its "Continue to app" button is labelled **Done** here. The banner is already inside the app,
so "continue to" it means nothing; `firstRun.js` sets that button's disabled state but never
its text, so the wording belongs to the host.

### 4c. Persona creation — one flow, two entry paths, in Studio

Studio's `+ New Persona` and `✨ Build with AI` both open the same flow. They differ only in
which step it starts on:

| Entry | Starts at | Then |
|---|---|---|
| `✨ Build with AI` | Interview (model-led Q&A) | → Examples → Stress test → Review & save |
| `+ New Persona` | Basics (role / tone / rules) | → Review & save |

Both end on a step named **Review & save**, and both save through the one `POST /personas`
they always shared.

**Correction, made during implementation.** This section originally said both paths would
converge on *the Foundry's* review screen. They do not, and should not. The Foundry's review
renders a compiled character card — archetype, temperament, signature moves, reliability —
produced by the interview. The wizard's step 4 carries the editable prompt, Regenerate,
Clean-up-with-your-model, the advanced knobs, lint, sample test and the few-shot editor.
Collapsing them into one screen would have deleted real capability from one side, which is a
parity loss dressed up as a simplification.

What genuinely converges is the **dialog, the entry points, and the save call**. That is the
duplication worth removing; two review screens doing two different jobs is not duplication.

**How it is wired.** The shell supplies chrome only — overlay, focus trap and return, Escape,
title, progress. It does not own stepping: the wizard advances from its own Back/Next plus a
jump to step 4 when the model drafts a persona from a description, and the Foundry advances on
backend results and per-screen Continue buttons. `personas.js` now exposes
`setWizardStepObserver` / `setFoundryScreenObserver`, and the dialog *follows*.

Rewriting either builder's stepping onto the shell's footer would have meant rewriting ~300
lines of validation and prompt regeneration with no unit coverage to land on — the big-bang
rewrite rule 7 exists to prevent. Two things advancing the same wizard would also simply
fight.

Consequences worth recording:

- Step elements are addressed by `data-flow-step="<id>"`, not by position. The two paths are
  different four-step subsets of the same eight-section markup, so "step 2" means a different
  element depending on how the dialog was opened.
- `flow.goTo(id)` bypasses gates. Gates guard the user's Next button; they are not a lock
  against the owner that already decided where the user is. An unknown id is a no-op rather
  than a jump to step 1 — silently rewinding a half-finished interview is the worse failure.
- The footer is path-specific. The Foundry has no footer controls at all, because every one
  of its advances is a Continue button inside the screen that produced the thing being
  continued from.

The wizard's model assists (`Build it with your model`, `Clean up with your model`) stay
exactly where they are useful; they are the same idea as the interview, at a smaller
granularity, and having both is fine now that they live in one flow rather than two screens
that don't know about each other.

**Deliberately not merged:** the stress-test screen stays Foundry-only. It needs a session id
from the guided interview and does not apply to a persona typed in by hand.

### 4d. Contact creation — the same shell

`CONTACT_WIZARD_DESIGN.md` already specifies the interview; it uses this shell rather than a
fifth bespoke dialog. Its degrade-to-a-plain-form requirement becomes "start on the Basics
step" — the same mechanism `+ New Persona` uses, which is why that entry path is worth having
even for users who never click it.

## 5. Order of work

1. ~~The shell (`sd-flow`) + unit tests for the step model.~~ **Done.**
2. ~~Onboarding onto the shell — the only gating flow, and the one with real consequences.~~
   **Done** — `features/onboardingFlow.js`, `tests/onboardingFlow.test.mjs` (19),
   `tests/qa/scenarios/onboarding.mjs` (4). First QA coverage onboarding has ever had; the
   harness skipped it because there was no way to ask for it on a configured profile.
3. ~~First-Run banner in Talk.~~ **Done** — `tests/qa/scenarios/first-run-banner.mjs` covers
   both directions: present when models are missing, absent when they are not.
4. ~~Persona flow (both entry paths converging on Review & save).~~ **Done** —
   `features/personaFlow.js`, `tests/personaFlow.test.mjs` (15),
   `tests/qa/scenarios/persona-flow.mjs` (4). Flips `personas.new`, `personas.foundry` and
   `personas.wizard` in `STUDIO_PLACEMENT_MAP` from `wired: false` to `wired: true`. See the
   correction in §4c: the two review screens stay separate.
5. Contact flow, when contacts land. **← next, and blocked on contacts existing**

Each is independently shippable, and the parity maps get their entries flipped as each lands
rather than in one batch at the end.

## 6. What this does not do

- It does not redesign the persona schema, the interview questions, or the compile step. Those
  are backend behaviours that work; this is where they surface.
- It does not add a "skip onboarding" affordance. Consent is a legal gate, not a preference.
- It does not make the progress dots navigable. See §2.
