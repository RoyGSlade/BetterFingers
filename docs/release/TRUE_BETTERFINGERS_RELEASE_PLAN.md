# True BetterFingers Release Plan

- **Product:** BetterFingers
- **Publisher:** Source Arcanum
- **Target platforms:** Windows and Linux
- **Recommended release identity:** `v0.2.0-alpha.1`
- **Status:** Wave 0 product measurement evidence and collaboration repairs
  complete; external authentication/restart/spawn proof and director
  acceptance remain open, and the implementation freeze remains active
- **Last reconciled:** 2026-07-28

This document is the product contract for the first public Source Arcanum
release. `RELEASE_BOARD.md` is the live queue, `DECISIONS.md` records rulings,
and `KNOWN_LIMITATIONS.md` records facts that must remain visible or be cleared
before publication. Older plans and design documents remain evidence and
rationale; they are not competing release queues.

## 1. Mission

Ship one real, hardened BetterFingers application:

> A private, local-first communication application that captures speech,
> preserves the user's meaning and voice, adapts to the active application,
> supports keyboard and controller workflows, and safely places the finished
> message where the user intends.

The release must provide:

- A production Signal Desk composition root with no runtime fixture or mock
  data.
- Durable first-run privacy consent and honest data-lifecycle controls.
- Working Talk, Library, Studio, Utilities, and Settings workspaces.
- Versioned personas, consent-gated learning, and preservation-qualified
  context features.
- Code-based active-application profiles without recipient inference.
- Keyboard, controller, qualified wake-word, and Stream Deck input paths.
- A restricted, approved application-launch workflow engine with no arbitrary
  scripts.
- Safe Windows and Linux injection fallbacks and truthful live capability
  status.
- Reproducible Windows and Linux artifacts, checksums, provenance, SBOM, and a
  Source Arcanum download/support surface.

This release does **not** include vision or screenshot analysis, game-guide
lookup, general web research, arbitrary computer control, arbitrary scripts,
gameplay automation, or a broad autonomous agent.

## 2. Authoritative repository baseline

The following baseline was verified locally and against the connected GitHub
repository on 2026-07-28:

| Field | Authoritative value | Evidence |
|---|---|---|
| `AUTHORITATIVE_REPOSITORY` | `https://github.com/RoyGSlade/BetterFingers.git` (`RoyGSlade/BetterFingers`) | Local `origin` and connected GitHub repository metadata agree; default remote branch is `main`. |
| `AUTHORITATIVE_BRANCH` | `feat/signal-desk-ui` | It contains the newer onboarding, contacts, audience, and traits work and exists at the same head locally and on GitHub. |
| `AUTHORITATIVE_COMMIT` | `093eaf2a2ae3e68c2671d8549d4b583c31558080` | Local `HEAD`, `origin/feat/signal-desk-ui`, and the GitHub comparison head agree. |
| `REMOTE_MAIN_COMMIT` | `4f9f4a8b7ff7f83bb67081063cfa439397b1663e` | Local `main`, `origin/main`, and the GitHub comparison base agree. |
| `LOCAL_UNPUSHED_COMMITS` | None on either local branch | Both local branches equal their configured upstreams; the authoritative branch is `0` ahead and `0` behind its upstream. |
| `OPEN_WORKTREES` | One: `/home/donaven/Desktop/BetterFingers` on `release/true-betterfingers` | `git worktree list --porcelain`. |
| Branch relationship | Authoritative branch is 7 commits ahead of `main`, 0 behind | Connected GitHub comparison and local history agree. |

The seven authoritative commits above `main` are:

1. `6d2bb86` — onboarding on the guided-flow shell.
2. `e3275af` — first-run setup banner in Talk.
3. `b9dbf5c` — persona creation on the guided-flow shell.
4. `daa22b9` — contacts backend.
5. `1503ae8` — contacts UI and audience preservation gate.
6. `8b0e0dc` — persona-traits design.
7. `093eaf2` — persona traits and the default-off preservation gate.

### 2.1 Integrated Wave 0 workset

The Wave 0 workset was broader than collaboration infrastructure. Its exact
review-and-commit scope was:

```text
AGENTS.md
.claude/collab-mcp/collab_lib.py
.claude/collab-mcp/hooks.py
.claude/collab-mcp/server.py
.claude/collab-mcp/test_collab.py
.claude/settings.json
.claude/skills/collab/SKILL.md
.claude/skills/hierarchy/SKILL.md
.claude/skills/wake/SKILL.md
.codex/config.toml
.codex/hooks.json
ACCOMPLISH.md
docs/ui/CURRENT_UI_INVENTORY.md
docs/PERSONA_TRAITS_DESIGN.md
docs/release/DECISIONS.md
docs/release/KNOWN_LIMITATIONS.md
docs/release/PACKAGE_BASELINE.md
docs/release/PARITY_INVENTORY.md
docs/release/PRESERVATION_BASELINE.json
docs/release/PRESERVATION_BASELINE.md
docs/release/RELEASE_BOARD.md
docs/release/TRUE_BETTERFINGERS_RELEASE_PLAN.md
app/tests/qa/out/baseline/dashboard-loads.png
app/tests/qa/out/baseline/settings-general-renders.png
app/tests/qa/out/baseline/settings-recording-renders.png
app/tests/qa/out/signal-desk/contacts/picker-is-backed-by-real-contacts.png
app/tests/qa/out/signal-desk/contacts/selecting-a-contact-persists-and-describes-them.png
app/tests/qa/out/signal-desk/contacts/the-typed-name-answers-the-first-question.png
app/tests/qa/out/signal-desk/contacts/wizard-offers-name-only-before-any-questions.png
app/tests/qa/out/signal-desk/first-run-banner/banner-appears-when-models-are-missing.png
app/tests/qa/out/signal-desk/first-run-banner/banner-is-absent-when-everything-is-installed.png
app/tests/qa/out/signal-desk/onboarding/consent-gates-the-forward-action.png
app/tests/qa/out/signal-desk/onboarding/decline-and-quit-is-separated-from-next.png
app/tests/qa/out/signal-desk/onboarding/does-not-open-on-a-completed-profile.png
app/tests/qa/out/signal-desk/onboarding/escape-cannot-dismiss-the-consent-gate.png
app/tests/qa/out/signal-desk/qa-report.md
app/tests/qa/out/signal-desk/signal-desk-shell/shell-mounts-with-live-bridge.png
app/tests/qa/out/signal-desk/signal-desk-shell/shortcuts-are-live-and-typing-safe.png
app/tests/qa/out/signal-desk/signal-desk-shell/status-bar-reports-real-state.png
app/tests/qa/out/signal-desk/signal-desk-shell/toast-host-renders-feedback.png
app/tests/qa/out/signal-desk/signal-desk-talk/decision-row-and-revise-drawer.png
app/tests/qa/out/signal-desk/signal-desk-talk/delivery-controls-replace-destination.png
app/tests/qa/out/signal-desk/signal-desk-talk/draft-editor-is-real-and-editable.png
app/tests/qa/out/voice-control/backbone-not-downloaded.png
app/tests/qa/out/voice-control/disabled-default.png
app/tests/qa/out/voice-control/user-imported-classifier-present.png
```

The coordinator reviewed and integrated that complete set, including the
regenerated QA report and all 23 pixel-identical PNG re-encodings, in three
bounded commits:

1. `abafdf6` — collaboration hierarchy hardening, repairs A–C, tests, and
   authoritative operating instructions.
2. `d320904` — repository, parity, preservation, package, and release-control
   baselines.
3. `cfe6136` — deterministic QA evidence.

The integration tree was clean after those commits. The final external
prerequisite was satisfied on 2026-07-28: the operator authenticated the
Claude CLI interactively, a restarted collab MCP served the repaired
configuration, and the authenticated cross-client hierarchy smoke passed end
to end (director → Opus supervisor in its own generation room → Sonnet worker;
claim round-trip, handoff, independent re-verification, `SMOKE PASS`
report-up, status-0 exits). Gate 0 is **ACCEPTED** (D-0017).

### 2.2 Integration branch status

The coordinator created `release/true-betterfingers` from the authoritative
commit, integrated the reviewed Wave 0 workset, and pushed the branch to
`origin`. The authenticated cross-client spawn smoke passed and the release
director recorded Gate 0 acceptance on 2026-07-28 (D-0017); Wave 1 is open
under the recorded sequencing rules (D-0014).

## 3. Current evidence, not assumptions

| Required Gate 0 evidence | Current state |
|---|---|
| `CURRENT_TEST_TOTALS` | Qualified `.venv`: backend **2,085 passed / 3 skipped / 9 subtests / 12 warnings**, exit 0. Renderer: **775/775** unit tests, production build passes, Playwright **18 passed / 3 model-dependent skipped**. Literal system Python is not a valid project environment and exits 2 with 72 dependency-related collection errors. |
| `CURRENT_PARITY_TOTALS` | The strict [438-item release ledger](PARITY_INVENTORY.md) records **0 `wired`, 4 `intentional_cut`, and 434 `blocked`**. Zero wired is the honest Gate 0 production-evidence baseline, not a product failure count to hide. The separate preview placement maps report Talk `28/33`, Library `11/23`, Studio `26/31`, Utilities `57/59`, and Settings `37/37`: **159/183 placed/wired in those maps, 24 unwired**; those values do not satisfy or replace the strict release ledger. |
| `CURRENT_PRESERVATION_RESULTS` | Retained [human-readable](PRESERVATION_BASELINE.md) and [machine-readable](PRESERVATION_BASELINE.json) evidence: delivery `PASS 3/3` and audience `PASS 3/3`, both qualified-but-disabled; corrected production True Janitor traits protocol exactly three consecutive suites, each `PASS 3/3`, from `2026-07-28T08:42:42Z` through `08:43:44Z`. Traits remain **UNAVAILABLE** (`unavailable_methodology_unreconciled`): the valid historical result is `FAIL_TRAITS 0/3`, and the invalid earlier Wave 0 adapter leaves qualification methodology unreconciled. Under the current gate, the valid historical failure blocks qualification. The adapter's `2/3`, `3/3`, and `3/3` observations used the wrong preset name, temperature `0.3`, and omitted the production absolute rule; they are not evidence for or against qualification. W0-P1 evidence collection is `DONE`, traits qualification is not a pass, and `use_persona_traits` remains `false` pending a director-approved repeated policy. |
| `CURRENT_PACKAGE_BASELINE` | The [Wave 0 package baseline](PACKAGE_BASELINE.md) is a timestamped `2026-07-28T08:11:19Z` snapshot, not a live authoritative checkout byte count. At that snapshot the tracked checkout was **525 files / 35,761,072 bytes**, `app/out` was **30 files / 1,288,162 bytes**, and `assets` + `images` were **14 files / 15,941,784 bytes**. The Python sidecar was **UNBUILT**, with Windows and Linux artifacts both **0 / 0 bytes**; no later package build is recorded, so the artifact result remains **ABSENT/UNBUILT**. Lock/toolchain drift is recorded; this completes the Gate 0 measurement, not Wave 12 qualification. |
| Legacy QA | The Wave 0 `qa:screens` run regenerated the default-UI report with `37/37` passing scenarios. |
| Signal Desk QA | The Wave 0 `qa:screens` run regenerated the aggregate Signal Desk report with `28/28` passing scenarios. |

Targeted reconciliation checks performed on 2026-07-28:

- Qualified environment: Linux Mint 22.3 (Ubuntu noble), kernel `7.0.0-28`,
  x86_64, CPython 3.12.3, pytest 9.1.1; `.venv` passes `pip check`.
- Full backend suite:
  `.venv/bin/python -m pytest -q tests` — `2,085 passed, 3 skipped,
  9 subtests, 12 warnings`, exit 0 in 172.67 seconds.
- Cheap backend suite:
  `.venv/bin/python -m pytest -q -k "not transcriber and not tts_engine"` —
  `1,972 passed, 3 skipped, 113 deselected, 9 subtests, 12 warnings`, exit 0.
- Focused storage/privacy/preservation/contact suite: `248 passed,
  6 warnings`, exit 0.
- Renderer contacts, contact wizard, traits helpers, Studio helpers, and parity
  maps: `100/100` passed.
- Full renderer unit baseline: `775/775` passed.
- Renderer production build: passed; generated `app/out` size
  `1,288,162` bytes across 30 files.
- Playwright: `18` passed and `3` model-dependent scenarios skipped.
- The concurrently run renderer baseline regenerated legacy QA at `37/37` and
  Signal Desk QA at `28/28`. These use the deterministic stub backend described
  by the QA harness; they do not prove a production composition root or real
  backend behavior.
- Literal `/usr/bin/python3 -m pytest -q tests` is an environment negative
  control: it exits 2 with 72 collection errors because project dependencies
  including `fastapi`, `numpy`, `keyboard`, and `pyperclip` are absent. It is
  not a code-test verdict and must not replace the qualified `.venv` result.
- The strict release-parity audit is recorded in
  [PARITY_INVENTORY.md](PARITY_INVENTORY.md): `0 wired`,
  `4 intentional_cut`, `434 blocked`, total `438`. Its production-evidence
  standard is deliberately stricter than the five `159/183` preview placement
  maps.
- The reproducible size/dependency/artifact measurement is recorded in
  [PACKAGE_BASELINE.md](PACKAGE_BASELINE.md). It finds no Windows or Linux
  distributable and no built sidecar; `ABSENT/UNBUILT` is the measured result,
  not an inferred package failure or a Wave 12 pass.
- The retained preservation measurement and runtime identity are recorded in
  [PRESERVATION_BASELINE.md](PRESERVATION_BASELINE.md) and
  [PRESERVATION_BASELINE.json](PRESERVATION_BASELINE.json). W0-P1 evidence
  collection is complete. The corrected traits snapshot is three consecutive
  `PASS 3/3` suites, but traits qualification is not a pass because the valid
  historical failure and invalid earlier methodology remain unreconciled.

## 4. Reconciled feature state

### 4.1 Contacts: partially implemented

Implemented on the authoritative branch:

- Versioned, atomic contact store with create, list, get, update, delete, and
  clear-all behavior.
- Deterministic interview and optional local-model compilation.
- FastAPI CRUD, interview, compile, and active-contact routes.
- Renderer API wrappers for CRUD and active selection.
- Signal Desk create wizard, picker, sticky selection, an unmounted
  status-label helper, Library contact mapping/filtering, and Studio
  preferred-contact display.
- Nullable draft `contact_id`.
- Privacy report listing and verified participation in the current privacy-wipe
  postconditions.
- User-authored-only boundary: no OS-address-book, active-window, or history
  inference.

Not release-complete:

- The visible Manage action opens the create wizard; no edit or delete manager
  consumes the existing renderer update/delete APIs.
- The contact status-label helper is used only by tests; no applied-contact
  status-bar cell consumes it.
- No user-visible Settings control enables or explains audience context.
- No implemented route/UI retroactively applies a contact to an existing draft.
- Contact export is declared in the future registry inventory, but that
  inventory's path, size, wipe, verification, and export mechanisms remain
  stubbed; the legacy privacy route and wipe contain separate contact logic.
- All visible contact surfaces currently live in the Signal Desk preview rather
  than a production composition root.

Binding classification for `v0.2.0-alpha.1`: **partially implemented**. Wave 5
must complete the entire release contract or cut contacts and audience context
from the release surface.

### 4.2 Audience context: backend implemented, user feature unavailable

The profile keys `use_audience_context` (default `false`) and
`active_contact_id` exist. When enabled, the dictation path resolves the
user-selected contact and passes a name-free audience block to the normal
cleanup prompt; drafts record the selected `contact_id` independently of the
toggle. The retained Wave 0 preservation evidence records `PASS 3/3`.

There is no visible Settings control, disclosure, or gate-status surface for
`use_audience_context`. Therefore the backend path is implemented but the
release feature is **unavailable to ordinary users** pending the Wave 5
control/disclosure work and preservation confirmation at that gate. The
current Wave 0 preservation result is `PASS 3/3`.

### 4.3 Persona traits: implemented but preservation-blocked

The five user-authored axes are present in schema normalization, storage,
persona routes, Studio controls, prompt rendering, tests, and the dictation
path. `use_persona_traits` defaults to `false`, so non-neutral traits do not
reach the live cleanup prompt.

The retained [preservation baseline](PRESERVATION_BASELINE.md) records exactly
three consecutive corrected production True Janitor suites, each `PASS 3/3`.
That green numeric snapshot does not qualify the feature: the valid historical
`FAIL_TRAITS 0/3` and the invalid earlier Wave 0 adapter leave the qualification
methodology unreconciled. The earlier adapter's `2/3`, `3/3`, and `3/3`
observations are methodologically invalid, not current evidence.

The current UI does not yet explain that saved sliders are gated off. Binding
release state: **Experimental — unavailable.** No release surface may imply
that traits affect output until a director-approved repeated policy reconciles
the methodology and produces an accepted qualification.

### 4.4 Signal Desk and production mocks

Signal Desk is not the production composition root:

- `app/src/main/windows.js` loads legacy `index.html` by default.
- Only `BF_UI=signal-desk` loads `signal-desk-preview.html`.
- No `app/src/renderer/signal-desk.html` or
  `app/src/renderer/bootstrap/signalDeskApp.js` exists.
- The preview identifies itself as “Director QA Preview,” contains static
  sample markup, and hardcodes visible version `v1.2.0`.
- It unconditionally seeds `MOCK_ITEMS`, `MOCK_PERSONAS`, mock voices, model
  state, devices, diagnostics, metrics, recordings, jobs, logs, settings,
  privacy locations, and onboarding responses in a page Electron can load.
- Talk and the status bar use some live adapters, but the page mixes those with
  fixtures; “partly live” is not a production state.
- Signal Desk onboarding opens only on a QA hash/query and uses disposable
  in-memory storage. The legacy app's onboarding state is renderer-local
  `localStorage`, not the required durable application consent record.
- `app/package.json` is `0.1.0`, which disagrees with the preview's `v1.2.0`
  and the planned `0.2.0-alpha.1`.

Production use of this page is blocked. Wave 1 must create one real composition
root and eliminate runtime fixtures before Signal Desk may become default in
Wave 11.

## 5. Binding product and engineering rules

1. BetterFingers remains local-first. User speech, text, contacts, context,
   persona examples, and models do not leave the device except for an explicit,
   separately described operation.
2. A contact is created, named, and selected by the user. Active-application
   identity must never infer a recipient.
3. Persona traits are configured by the user and never inferred from speech,
   transcript, history, or edit signals.
4. Persona learning is explicit, inspectable, removable, exportable, and
   covered by wipe verification.
5. Names, numbers, dates, negation, requests, commitments, stated intensity,
   technical identifiers, and selected formatting are preservation invariants.
6. No production runtime fixture, `MOCK_*`, preview bootstrap, hardcoded sample
   profile, or hash-only onboarding bypass may ship.
7. Platform capability states use only `supported`,
   `supported_with_requirements`, `clipboard_only`, `experimental`,
   `unavailable`, or `unknown`.
8. No arbitrary shell, batch, PowerShell, command, generated-code, registry,
   credential, purchase, destructive-file, or hidden-message action exists in
   a saved workflow.
9. `auto_submit=false` is the default for games; no gameplay automation,
   memory inspection, coordinate clicking, or repeating macros.
10. Every feature requires implementation, automated tests, user-visible
    failure behavior, privacy review, and documentation or a QA scenario.
11. Only the coordinator manages branches, commits, merges, tags, or releases.
12. The director reruns every wave gate from the integrated tree.

## 6. Approved technical strategy

### Audio privacy

Split output ducking from input privacy. Implement a lease-based privacy
lifecycle that restores exact prior state on every stop and crash path. Linux
capture isolation uses a journaled PulseAudio/PipeWire adapter that identifies
streams structurally and never mutes BetterFingers. Windows capture isolation
requires a time-boxed Core Audio feasibility proof; otherwise Windows ships
push-to-mute with an honest unavailable isolation status. Never disable the
physical microphone and do not distribute SoundVolumeView.

### Application workflows

Store only versioned restricted actions. Natural language may compile a
workflow, but validation, exact preview, and explicit approval precede saving
or running it. Platform launchers receive executable plus argument arrays,
never shell strings. Partial execution reports each step.

### Injection

Preserve the existing Windows simulation, Linux `xdotool` / `wtype` /
`ydotool`, clipboard-paste fallback, pacing, clipboard restoration, and
chat-key behavior. Add optional adapter interfaces; do not treat Playwright as
a universal production controller. Clipboard-only remains available.

### Wake word

Harden the existing detector rather than replacing it. One `AudioInputBroker`
owns the device; a bounded in-memory pre-trigger ring protects the first command
word; trailing silence ends command capture. Audit every model license and
qualify false accepts/rejects, latency, CPU, handoff, coexistence, and device
recovery before making support claims.

### Architecture boundary

Electron owns OS-facing windows, active-app context, hooks, launching, typed
IPC, and renderer composition. Python owns STT, LLM, TTS, personas/learning,
qualified contact context, wake detection, validation, persistence, and data
lifecycle. Preserve that boundary.

## 7. Execution waves and gates

| Wave | Objective | Gate |
|---:|---|---|
| 0 | Reconcile repository, create the coordinator-owned integration branch, measure exact tests/QA/parity/preservation/dependencies/artifacts, and freeze scope. | One branch, clean reconciled tree, exact evidence, contacts classified, no unresolved release-critical worktree. |
| 1 | Build the real Signal Desk composition root and durable onboarding; remove production mocks and self-initialization conflicts. | Default-candidate page uses real backend/data, honest empty states, durable consent, no duplicate handlers or console errors. |
| 2 | Complete Talk capture, emergency stop, delivery selector/results, editing, and teach-from-edit. | All input paths converge; every stop releases resources; Type/Paste/Copy and fallback reporting work. |
| 3 | Implement Library domain semantics for pin, per-item delete, duplicate, reopen, resend, restore, filters, and clear modes. | Every action has domain tests and accurate provenance/recovery semantics. |
| 4 | Wire the Library domain into accessible Signal Desk UI. | Every Library parity entry is `wired` or `intentional_cut`. |
| 5 | Complete Studio, persona flows, contacts/audience, and qualified Settings controls. | Contacts are complete or absent; audience toggles disclose data and gate status; traits remain unavailable pending an accepted qualification. |
| 6 | Close privacy and data lifecycle for every persistent store. | Registry, filesystem, report, export, wipe, and verification agree. |
| 7 | Promote active-app detection into deterministic application profiles. | Unknown is safe, Wayland is honest, no recipient inference, profile changes do not interrupt work. |
| 8 | Implement audio privacy, shared audio input, wake handoff, licensing, and failure UI. | Exact restoration, crash recovery, one microphone owner, licensed artifacts, no first-word loss. |
| 9 | Implement the restricted action engine and approved application workflows. | Unsupported actions and unknown commands cannot execute; partial failure is visible. |
| 10 | Complete controller and Stream Deck adapters over shared action IDs. | Reconnect/release/bounce/timing behavior and emergency stop pass; setup cannot accidentally send. |
| 11 | Close and rerun the strict 438-item release ledger, remove mocks, centralize version, and flip Signal Desk default with legacy rollback. | Zero blocked entries, Signal Desk default, legacy fallback, matching versions, compatible stores. |
| 12 | Qualify Windows NSIS and Linux AppImage packages, signing status, allowlist, CI, hardware matrix, checksums, provenance, and SBOM. | Same tag, install/upgrade/uninstall and clean launch verified, no P0/P1, no migration/privacy/arbitrary-execution failure. |
| 13 | Publish the Source Arcanum page, downloads, manifest, guides, privacy/support content, and honest limitations. | Gates 0–12 accepted; website/package/backend/renderer versions and claims agree. |
| 14 | After one Signal Desk release, remove legacy renderer and then reorganize backend monoliths one seam at a time. | No rollback blocker; compatibility and import-cycle gates remain green. |

Dependency order is binding:

```text
composition → live workspace mounting → parity audit → default flip → packages
Library domain → Library UI
AudioInputBroker → wake handoff → capture isolation
action schema → launch adapters → voice/controller/Stream Deck
persistent store → privacy registry → public release
```

## 8. Cross-cutting release gates

- **Preservation:** delivery is qualified but default-off; audience is
  qualified but remains default-off pending product controls; traits are
  unavailable because qualification methodology is unreconciled and require a
  director-approved repeated policy and accepted qualification before they can
  be enabled.
- **Security:** context isolation, disabled Node integration, restricted
  navigation/popups, typed IPC, exact route allowlists, destructive
  confirmation, no shell, no user text in logs, hash-verified downloads, and
  commit-pinned release actions.
- **Reliability:** recording and held state cannot strand; clipboard, output
  volume, audio privacy, controller, wake, crash recovery, send/wipe races,
  corruption, and migrations have tested restoration paths.
- **Performance:** record cold start, idle RAM/CPU, wake-on CPU, STT/LLM/TTS
  latency, gaming latency, profile activation, controller-to-record latency,
  and artifact sizes on defined hardware.
- **Accessibility:** keyboard traversal, visible focus, labels/status
  announcements, reduced motion, non-color state, dialog focus/escape, and
  practical non-mouse controller setup.

## 9. Public-release definition of done

A new user can verify and install the Windows or Linux artifact, complete real
privacy consent, install/select local models, create and version a persona,
dictate by keyboard or controller, review a real Talk draft, Type/Paste/Copy
with honest fallback, recover and manage Library items, approve and inspect
learning, use application profiles and qualified wake support, run only
approved launch workflows, use shared controller/Stream Deck actions, inspect
real capability limits, wipe and verify personal data, generate a content-free
support report, and upgrade without losing supported data.

The project can prove there are no production mocks, blocked parity entries,
arbitrary execution paths, unlisted stores, enabled unqualified preservation
features, unqualified release commits, fabricated platform claims, or version
mismatches.
