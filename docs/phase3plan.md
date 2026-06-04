# Phase 3 Plan: Workflow Send, Overlay UX, And Robust Interaction

## Why this doc exists

This document reviews the current `docs/ELECTRON_FULL_FUNCTIONALITY_TODO.md` Phase 3 scope against the current Electron app and your stated product direction:

- keep BetterFingers working like the original app
- improve robustness first
- upgrade UI without trapping users inside the dashboard
- move toward an Electron-first experience, not a web-admin panel with voice features bolted on

It also includes open questions, concerns, and a recommended execution plan.

---

## Current functionality review

Based on the current docs and renderer:

- Electron shell startup, sidecar boot, diagnostics, profiles, model UI, and draft flows already exist.
- The current Electron UI is functional, but it is still dashboard-heavy.
- Draft review/edit/rewrite/send exists, but the primary interaction model still assumes the user spends too much time inside BetterFingers.
- Phase 3 in the master TODO is currently defined as:
  - send modes
  - injection
  - clipboard safety
  - primary action behavior
- Your notes add an important product correction:
  - BetterFingers should primarily help users work in other apps
  - recording state needs overlay feedback
  - review should be optional/lightweight, not the center of the product
  - persona and settings need much better explanation and structure

---

## Recommendation

Phase 3 should stay focused on end-to-end workflow parity, but broaden slightly so we do not harden the wrong UX.

Recommended Phase 3 definition:

> Make BetterFingers reliable for the real user loop:
> record -> visible recording state -> process -> review only when needed -> send safely into the target app -> recover cleanly on failure.

That means Phase 3 should include:

- send/injection hardening
- clipboard safety and fallback logic
- primary action predictability
- lightweight overlay/status UX for recording and processing
- reduction of dashboard dependence for normal use

It should not try to fully complete:

- the full settings redesign
- full theme/appearance system
- advanced planner/agent behavior
- deep TTS completion

Those belong mostly to later phases, though Phase 3 should lay the architecture for them.

---

## Concerns

### 1. Scope conflict between parity and redesign

The existing master plan puts big settings and UX redesign work in Phase 4, but your feedback shows some UX changes are actually required earlier because they affect how users interact with the app at all.

### 2. Current dashboard-centric UX is not the product

The current Electron renderer is valuable for diagnostics and development, but it does not yet feel like the original BetterFingers workflow. If we only harden backend send behavior without shifting the interaction model, we risk polishing the wrong surface.

### 3. Review cannot disappear entirely

I agree that users should not live inside BetterFingers to manually copy text out. Still, removing review completely would hurt safety and trust. The better direction is:

- quick review when needed
- auto-send when configured
- small overlay/status window for interrupts and corrections
- full dashboard kept as control center, not main workflow

UserNote: should be able to create an overlay similar to the original app on windows that after the users text has been recorded translated can be played back to them modified further etc all within the overlay not the dashboard (overlay on top of other apps not within betterfingers)

### 4. Overlay design needs platform realism

Windows and Linux do not offer the same behavior, and Wayland is especially constrained. We should design overlay/status features so they degrade gracefully without pretending Linux supports Windows-style injection behavior. We need to find a solution that provides the same level and utility as the windows version on linux regardless of added complexity.

### 5. Settings complexity is already outrunning UX clarity

The app now exposes many settings, but the current presentation does not teach the user what they do, when they matter, or which ones are platform-limited. If we keep adding options without structure, robustness will improve for us but usability will decline for the user.
I agree with your point we need to make the user feel comfortable before throwing them into the spiral of settings and things to mess with we should have everything at a baseline of awesome then improve from there overwhelming the user is not on my to do list dropdowns for more advanced settings and minimizing the need for everysetting is a high priotity in the future development window.
---

## Open questions

These are the main questions I think we should resolve while implementing Phase 3:

1. Should accepted drafts auto-send by default for the main profile, or should `review_first` remain the default until Linux/Windows QA passes?
   - Recommendation: keep `review_first` as the default until send behavior is verified on your real daily workflow targets. review first should always be the default always espessially with whisper and an llm they can work really well but while we may trust our program we should always give ourselves and the users the ability to verify our work before it is sent.

2. What is the minimum overlay set for parity?
   - Recommendation: start with:
   - recording overlay
   - processing indicator
   - send result toast/status
   A compact easy to use would be yes i agree with the rewrite/edit press action key once accepts its in a clipboard press second time to paste if they dont like the edit or request a change they click either change which will give our ai their old context plus new or instruct which will allow them to record special instructions for the ai rewrite we will reinject the og prompt and the og persona the new prompt and then lastly add the user instructions with some slight special rules for either button then a review pannel would extend to show the new prompt version etc etc etc then accept will send it where as cancel will start over.

3. Should the Review panel remain in the dashboard after overlay work lands?
   - Recommendation: yes, but as a hidden from the main ui somewhere deeper for recovery, editing, history, and diagnostics.

4. Do we want a dedicated mini review window, or an in-dashboard review panel plus overlay notifications first?
   - Recommendation: do overlay notifications first, then add a mini review window only if the flow still feels too heavy.
      do both the app almost doesnt make sense without the notifcations and the review window as explained above 
5. Which real target apps should define send QA?
   - Recommendation: test at minimum:
   - Google Docs in browser
   - Gmail or another web text area
   - a plain text editor
   - one rich desktop editor on Windows
   all of the above easily and should work in most video games as well we need to also be ready for controller button mapping if im playing rocket league i need to be able to map a button to trigger an action or a sequence of actions and bamm trash talk them kids

---

## Phase 3 goals

### Goal 1: Real workflow parity

Users should be able to trigger BetterFingers, speak, and get text into another app without babysitting the dashboard.

### Goal 2: Safe send behavior

When typing/pasting/injection fails, BetterFingers should clearly say what happened, preserve user state where possible, and fall back safely.

### Goal 3: Lightweight UX

Normal usage should rely on overlays, status indicators, hotkeys, and predictable send behavior. The dashboard should support the flow, not be the flow.

### Goal 4: Robustness before expansion

No planner/assistant expansion should be built on top of unreliable recording, processing, send, or clipboard state.

---

## Proposed execution plan

### Workstream A: Send pipeline hardening

Implement and verify:

- explicit requested-action vs actual-action reporting after send
- reliable fallback chain:
  - preferred action
  - platform-allowed fallback
  - final clipboard-safe fallback
- improved send result payloads for:
  - requested mode
  - actual mode used
  - fallback reason
  - target capability status
  - clipboard restore outcome
- stronger failure states in UI and backend event stream
- test-send utility in settings

Exit criteria:

- send behavior is never silent
- failed injection leaves a useful user-facing result
- copy fallback is always obvious

### Workstream B: Primary action and accepted-draft behavior

Clarify and lock the main interaction contract:

- if a draft is pending acceptance, show the next expected action clearly
- if a draft is accepted and pending send, primary action should behave predictably
- if no draft is pending, primary action should perform selected-text or configured fallback behavior
- emergency stop should interrupt any active send/typing path and leave state consistent

Exit criteria:

- primary action never feels ambiguous
- accepted/pending/sent states are visible and consistent

### Workstream C: Overlay-first interaction layer

Add the minimum parity overlays needed for daily use:

- recording started indicator
- recording active indicator
- processing indicator
- send success/fallback/failure notification
- blocked no-audio or error notification

Design rules:

- fast to read
- minimal clicks
- non-invasive
- clear platform-limitation language
- dashboard remains available for deeper review/history/settings

Exit criteria:

- user can understand app state without opening the dashboard
- normal usage feels closer to the legacy app

### Workstream D: Dashboard de-emphasis, not removal

Refactor the dashboard’s role:

- keep review/history there
- keep diagnostics there
- keep settings there temporarily
- reduce wording and layout that implies this is the primary daily workspace

Practical UI changes:

- relabel dashboard sections around operational tasks
- add “last action/result” summaries
- surface send mode more clearly
- stop making review feel like a mandatory in-app handoff

Exit criteria:

- the dashboard feels like a control center, not a required editor

### Workstream E: Settings clarity required for Phase 3

Do not attempt the full Phase 4 redesign yet, but complete the minimum settings work needed to support real usage:

- explain record mode clearly
- explain send mode clearly
- explain overlay/status behavior clearly
- show platform warnings inline
- improve persona wizard language so users understand what each part changes
- group the most important daily settings first

Exit criteria:

- a new user can understand how to record, stop, review, and send without guessing

### Workstream F: Real-world QA and robustness

Phase 3 should use real manual testing, not mock-only confidence.

Required QA tracks:

- Linux X11
- Linux Wayland with expected limitations documented
- Windows
- real voice recordings
- real target apps
- repeated rapid usage
- clipboard preservation tests
- emergency stop during processing/sending

Automated coverage should focus on:

- send fallback semantics
- pending send queue transitions
- clipboard restore behavior
- empty/failed send results
- primary action state transitions

Exit criteria:

- the common end-to-end user path is proven on actual targets

---

## Suggested implementation order

1. Finalize send result contract and backend state reporting.
2. Harden fallback and clipboard preservation logic.
3. Add visible send mode controls and test-send behavior.
4. Implement recording/processing/send overlays.
5. Simplify dashboard messaging so it supports, not dominates, workflow.
6. Improve the minimum settings explanations needed for daily use.
7. Run real manual QA on Linux and Windows targets.
8. Update parity map and full functionality docs with actual verified status.

---

## What should wait until after Phase 3

- full settings IA redesign
- full appearance/theme system
- advanced onboarding flows
- full TTS completion and read-aloud polish
- planner/goals/reminders/local-agent expansion

---

## Recommended definition of done

Phase 3 is done when:

- the user can reliably record, process, and send text into another app
- BetterFingers clearly shows recording, processing, success, fallback, and failure states
- clipboard and send failures are recoverable and visible
- the dashboard is no longer required for normal operation
- Linux limitations are explicit rather than hidden
- manual QA has been performed with real voice input and real target apps

---

## Final recommendation

I do not think Phase 3 should be treated as only a backend send-hardening phase.

I also do not think it should become a full settings/UI redesign phase.

The right middle ground is:

- finish send/injection robustness
- add overlay-first workflow UX
- reduce dependence on the dashboard
- make only the minimum settings improvements needed to support that flow

That keeps us aligned with the original BetterFingers behavior while still moving the Electron app toward a stronger, more modern foundation.
