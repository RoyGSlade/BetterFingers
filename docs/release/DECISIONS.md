# True BetterFingers Release Decisions

- **Release:** `v0.2.0-alpha.1`
- **Last updated:** 2026-07-28

These decisions are binding until superseded by a later numbered ruling from
the release director.

## D-0001 — Authoritative source baseline

**Owner:** release-director

**Evidence owner:** Wave 0 reconciliation

**Decision:** Use `RoyGSlade/BetterFingers`,
`feat/signal-desk-ui`, commit
`093eaf2a2ae3e68c2671d8549d4b583c31558080` as the authoritative source
baseline.

**Reason:** The connected GitHub branch and local branch agree exactly. It is
seven commits ahead of `main` and contains the newer onboarding,
contacts/audience, and persona-traits work named in the directive. It is not
behind `main` and has no local-only commits.

**Consequence:** Connected `main` at `4f9f4a8…` is not a sufficient release
planning baseline. Source authority does not imply Gate 0 qualification.

## D-0002 — Use the coordinator-owned integration branch

**Owner:** release-director / coordinator

**Decision:** Use `release/true-betterfingers`, created by the coordinator from
`093eaf2a…` and pushed to `origin`, as the release integration branch.

**Reason:** Wave 0 reconciliation identified the authoritative source, and the
coordinator reviewed and integrated the bounded workset without changing that
source ancestry.

**Consequence:** The branch-creation requirement is satisfied. Gate 0 remains
open and all implementation waves remain blocked on the authenticated,
restarted cross-client spawn proof and subsequent director acceptance.

## D-0003 — Preserve and review the complete Wave 0 workset

**Owner:** release-director / coordinator

**Decision:** The coordinator reviewed and committed every exact Gate 0 path
listed in the [release plan workset](TRUE_BETTERFINGERS_RELEASE_PLAN.md#21-integrated-wave-0-workset):
`AGENTS.md`; `.claude`/`.codex` infrastructure and skills; `ACCOMPLISH.md`
repair C; UI/release/persona docs; the regenerated Signal Desk QA report; and
the 23 regenerated PNGs that are pixel-identical but byte-reencoded.

**Reason:** The live Wave 0 worktree contains active infrastructure,
documentation, evidence, and generated QA artifacts. It is inaccurate to
describe only collaboration/hierarchy infrastructure as dirty.

**Consequence:** Repairs A–C and the complete workset are integrated in
`abafdf6`, `d320904`, and `cfe6136`; the integration tree was clean afterward.
Claude authentication, a client/MCP restart onto the repaired configuration,
and a real authenticated Claude cross-client spawn remain external blockers
before Gate 0 can pass; the spawn evidence is incomplete.

## D-0004 — Contacts are partially implemented

**Owner:** release-director

**Decision:** Classify contacts as `partially implemented`, not design-only and
not release-complete.

**Reason:** Store, interview, CRUD routes, active selection, renderer API,
create/picker UI, draft `contact_id`, Library/Studio mapping, privacy reporting,
and wipe postconditions exist. The status-label helper is not mounted. Visible
edit/delete/manage, retroactive draft application, integrated export/lifecycle,
Settings disclosure, and production composition do not.

**Consequence:** Wave 5 either completes the full contract and Gate 5 or removes
contacts and audience context from the release surface. No create-only or
fictional manager ships.

## D-0005 — Audience context stays unavailable by default

**Owner:** release-director

**Decision:** Keep `use_audience_context=false` until a visible Settings
control explains its data, effect, preservation promise, default, inspect path,
and gate status, and the current pass is confirmed at the Wave 5 gate.

**Reason:** The backend path and retained Wave 0 [preservation
baseline](PRESERVATION_BASELINE.md) `PASS 3/3` evidence exist, but no ordinary
user can inspect or enable the feature through Signal Desk.

**Consequence:** Active contact selection may remain useful metadata and may be
recorded on a draft; it must not silently affect model output.

## D-0006 — Persona traits are Experimental — unavailable

**Owner:** release-director

**Decision:** Preserve schema/storage/UI data, keep
`use_persona_traits=false`, and show traits as `Experimental — unavailable`
until a director-approved repeated preservation policy produces an accepted
qualification.

**Reason:** The corrected production True Janitor protocol has a green current
numeric snapshot—exactly three consecutive `PASS 3/3` suites—but the valid
historical `FAIL_TRAITS 0/3` and invalid earlier Wave 0 adapter leave
qualification methodology unreconciled. A saved slider that silently does
nothing is also not acceptable release behavior, so the UI must disclose the
gate.

**Consequence:** No unqualified trait path may be enabled or advertised as
effective.

## D-0007 — Signal Desk preview is not a production root

**Owner:** release-director

**Decision:** Do not promote or rename
`signal-desk-preview.html` into production. Build
`app/src/renderer/signal-desk.html` plus
`app/src/renderer/bootstrap/signalDeskApp.js` as a single live composition
root.

**Reason:** The current preview is opt-in, identifies itself as Director QA,
mixes live adapters with extensive runtime fixtures, hardcodes a false version,
and uses QA-only onboarding state.

**Consequence:** Legacy `index.html` remains the production default until Wave
11. All runtime fixture data must move behind test/QA-only entry points before
Gate 1.

## D-0008 — Release identity and version source

**Owner:** release-director

**Decision:** Target `v0.2.0-alpha.1`, product `BetterFingers`, publisher
`Source Arcanum`, and recommended application ID
`com.sourcearcanum.betterfingers`. Freeze the final installer upgrade identity
before the public artifact.

**Reason:** The current package (`0.1.0`) and preview (`v1.2.0`) conflict. A
public application-ID change breaks upgrade continuity.

**Consequence:** One build version source must feed Electron, Python, renderer,
support report, manifest, and filenames before Gate 11.

## D-0009 — Platform support requires qualification

**Owner:** release-director

**Decision:** Use only `supported`, `supported_with_requirements`,
`clipboard_only`, `experimental`, `unavailable`, or `unknown` for capability
status. Until Wave 12 evidence exists, package-level Windows and Linux claims
remain `unknown`.

**Reason:** Source code paths and CI workflows are not package qualification.

**Consequence:** Source Arcanum copy and in-app capability UI must reflect
measured status, including Wayland, injection tools, signing, GPU runtimes,
wake, and voice privacy.

## D-0010 — Audio privacy strategy

**Owner:** release-director

**Decision:** Split output ducking from input voice privacy; use lease-based,
journaled, exact restoration. Linux may implement PulseAudio/PipeWire capture
isolation. Windows isolation requires a Core Audio feasibility proof and
otherwise uses push-to-mute.

**Rejected:** Physical microphone disable, bundled SoundVolumeView, and
application-name shell loops.

## D-0011 — Restricted workflow strategy

**Owner:** release-director

**Decision:** Store only versioned restricted actions, validate targets, show
an exact preview, require approval, and execute through platform adapters using
argument arrays.

**Rejected:** Shell, Bash, PowerShell, CMD, arbitrary scripts/code, destructive
file actions, process killing, registry edits, credentials, purchases, and
hidden messages.

## D-0012 — Injection and game policy

**Owner:** release-director

**Decision:** Preserve current injection/fallback behavior, add optional
accessibility adapters, and retain clipboard-only mode. Playwright remains a QA
tool, not a universal controller. Game defaults are review-only or
clipboard-safe with `auto_submit=false`.

## D-0013 — Wake architecture

**Owner:** release-director

**Decision:** Harden the existing detector with one `AudioInputBroker`, a
bounded in-memory pre-trigger ring, trailing-silence capture termination,
license provenance, and measured qualification.

**Consequence:** Personalized wake phrases are convenience, not
authentication; restricted action contracts remain the security boundary.

## D-0014 — Release sequencing

**Owner:** release-director

**Decision:** Enforce the dependency order recorded in the release plan. In
particular, production composition precedes live workspace mounting and parity;
Library domain precedes Library UI; shared audio ownership precedes wake/privacy
integration; action schema precedes invocation adapters; persistent stores
precede privacy closure.

**Consequence:** Passing work in an independent lane does not authorize a
dependent wave before the director accepts its gate.

## D-0015 — Accept strict parity and absent-package baselines

**Owner:** release-director

**Evidence:** [PARITY_INVENTORY.md](PARITY_INVENTORY.md) and
[PACKAGE_BASELINE.md](PACKAGE_BASELINE.md)

**Decision:** Accept the strict Gate 0 release-parity model and the exact
package artifact ledger as the authoritative baselines:

- Parity: 0 `wired`, 4 `intentional_cut`, 434 `blocked`, total `438`.
- Package snapshot at `2026-07-28T08:11:19Z`: tracked checkout
  `525 files / 35,761,072 bytes`; `app/out` `30 files / 1,288,162 bytes`;
  `assets` + `images` `14 files / 15,941,784 bytes`; Python sidecar
  `UNBUILT`; Windows `0 artifacts / 0 bytes`; Linux `0 artifacts / 0 bytes`;
  overall result `ABSENT/UNBUILT`.

**Reason:** A `wired` release status requires the complete production Signal
Desk data/action/failure/accessibility/QA/privacy evidence chain. The separate
preview placement maps (`159/183`) are useful discovery evidence but do not
meet that rule. Likewise, source and build-output sizes are measurements, not
substitutes for distributable packages. Lock-root metadata, Python
environment, and native toolchain drift are recorded in the package baseline.
The tracked-checkout file and byte counts are a timestamped snapshot, not a
live authoritative measurement of the changing worktree.

**Consequence:** Zero strict wired entries is the honest starting state, not a
product failure count to hide or inflate with preview placement. W0-I1 and
W0-D1 are complete as Gate 0 evidence tasks. The 434 blocked parity rows remain
Wave 1–11 work, and the absent sidecar/installers plus toolchain and allowlist
gaps remain Wave 12 qualification work.

## D-0016 — Corrected green traits snapshot is not qualification

**Owner:** release-director

**Evidence:** [PRESERVATION_BASELINE.md](PRESERVATION_BASELINE.md) and
[PRESERVATION_BASELINE.json](PRESERVATION_BASELINE.json)

**Decision:** Record the current corrected traits numeric snapshot as exactly
three consecutive production True Janitor suites, each `PASS 3/3`, while
classifying the release gate as `unavailable_methodology_unreconciled`.

**Reason:** The valid historical result is `FAIL_TRAITS 0/3`. Earlier Wave 0
observations of `2/3`, `3/3`, and `3/3` used the wrong preset name,
temperature `0.3`, and omitted the production True Janitor absolute rule; they
are methodologically invalid and are not evidence for or against
qualification. The corrected green snapshot does not by itself reconcile the
historical failure, sampling behavior, corpus scope, or acceptance threshold.
Under the current gate, the valid historical failure blocks qualification.

**Consequence:** W0-P1 product measurement evidence collection is `DONE`, but
traits qualification is not a pass. `use_persona_traits` remains `false` until
a future director-approved repeated qualification policy reconciles the
methodology and yields an accepted result.

## D-0017 — Gate 0 is accepted

**Owner:** release-director

**Evidence:** Spawn logs
`.claude/collab/spawn-logs/sup-smoke-20260728-021957-e6f6a187.log` and
`.claude/collab/spawn-logs/worker-smoke-20260728-022013-58ad2be3.log`; room
`.claude/collab/rooms/sup-smoke-18c6699673c0b3ee-e6f6a187/`; main-room
`SMOKE PASS` report-up of 2026-07-28.

**Decision:** Accept Gate 0 and open Wave 1.

**Reason:** The one remaining blocker, W0-C4, passed on 2026-07-28. The
operator authenticated the Claude CLI interactively (version 2.1.219,
`loggedIn: true`, claude.ai first-party auth). A freshly started collab MCP
process serving the repaired post-`abafdf6` code ran the complete hierarchy:
the Fable 5 release-director session spawned `sup-smoke` (Opus 5), which
received its own generation-specific private room, spawned exactly one
`worker-smoke` (Sonnet 5) into that room, and the worker registered, performed
a `__smoke-test__` pseudo-claim round-trip, verified the release board and a
clean worktree, and handed off. The supervisor independently re-verified every
worker-reported fact, reported `SMOKE PASS` up to the director's room, and both
children exited status 0. The auth preflight and bounded health check that
previously refused unauthenticated spawns (`loggedIn: false`) demonstrably
gated, then admitted, the real session. Every other Gate 0 row was already
`DONE` with retained evidence.

**Consequence:** Wave 1 (production Signal Desk composition root and durable
onboarding) may begin under the recorded sequencing rules (D-0014). All other
wave gates remain closed until their own evidence exists. The stale
pre-repair `sup-reconcile`/`sup-baseline` fleet records (exit status 1, from
the unauthenticated era) are historical artifacts, correctly classified by the
repaired liveness logic, and consume no capacity.

## D-0018 — Wave 1 objectives A and B accepted and integrated

**Owner:** release-director

**Evidence:** Supervisor handoffs in the main room (2026-07-28); director
reruns: renderer unit `856/856`, build green, onboarding suite 78 tests green,
`test_data_categories` 11/11, legacy QA `37/37`, preview QA `28/28`,
production `signal-desk-prod` persona-learning `3/3`
([report](../../app/tests/qa/out/signal-desk-prod/qa-report.md)).

**Decision:** Accept and integrate Wave 1 Objective A (production composition
root) and Objective B (durable onboarding/consent), with the director applying
the integration-owned wiring. Ratify sup-composition's QA judgment call: the
"editing never learns anything on its own" trigger is asserted as "running
Test Persona never learns anything on its own" because Studio's teach panel
has no live-draft concept; the privacy invariant under test (nothing stored
without prepare-then-confirm-with-consent) is unchanged. Restoring the
original edit-trigger assertion is Wave 2+ Studio wiring work, not a scenario
weakening.

**Also decided:**

- The taskSafe spawn allowlist gains `Bash(npm run test:*)` and
  `Bash(node --test *)`. Three Wave 1 sessions were unable to execute any
  renderer test (`npm run test *` cannot match `test:unit`) and correctly
  refused to shim around the allowlist; they reported UNRUN instead of
  fabricating results. That behavior is the intended contract.
- Committed QA screenshots are environment-pinned baselines. A rerun from a
  different rendering environment that changes PNGs visually (46/46 here)
  must not overwrite them; assertion-level passes are the portable evidence.
- Production-target QA runs must isolate both Electron state
  (`BF_QA_USER_DATA_DIR`) and the unified data root
  (`BETTERFINGERS_DATA_DIR`) now that the durable consent store writes real
  files; the isolated run produced a correct migrated record while real roots
  stayed untouched.

**Consequence:** Wave 1 remains `IN PROGRESS` on W1-G1 (consent-gate QA on
the prod target, real-backend dev boot, reachability/console sweep,
privacy-wipe reachability) before a Gate 1 ruling. Two integration-caught
defect classes are recorded for future waves: new main-process modules must be
added to `electron.vite.config.js` main inputs (a missing input fails at
runtime as a silent no-window startup), and consent-step advance predicates
must incorporate live user intent, not only boot-time durable state.

## D-0019 — Gate 1 is accepted

**Owner:** release-director

**Evidence:** Director-run 2026-07-28: renderer unit `866/866`; production
`signal-desk-prod` QA `11/11` — consent gate `5/5` (first run, seeded
completed record, legacy-flag migration, decline/next separation, Escape
cannot dismiss), section reachability + privacy-wipe control `2/2`,
zero-exclusion console sweep `1/1`, persona-learning `3/3`
([report](../../app/tests/qa/out/signal-desk-prod/qa-report.md)); regressions
preview `28/28` and legacy `37/37` unchanged. Real-backend probe: the page
booted with `server.py` from the qualified `.venv` (Uvicorn up, the app's
authenticated calls all 200, unauthenticated callers correctly 401,
voice-status WebSocket open), the first-run consent gate appeared with a blank
data root and blocked all navigation until a real click-through wrote a
schema-correct `accepted: true` record, after which all sections navigated
with zero console/page errors.

**Decision:** Accept Gate 1. Wave 1 is complete; Waves 2 (Talk) and 3
(Library domain semantics) open under D-0014.

**Scope notes, recorded honestly:**

- The consent scenarios drive the real durable gate — no production debug
  handle exists; the preview's `window.__onboarding`-driven scenarios remain
  preview-only.
- Windows first-run consent has no evidence yet; per D-0009 platform claims
  stay `unknown` until the Wave 12 qualification matrix runs it.
- The QA harness first-run seam refuses to operate without an explicit
  `BETTERFINGERS_DATA_DIR` override, so consent QA can never touch a real
  profile; its auto-dismiss sentinel is single-shot so scenario order is not
  load-bearing (supervisor-caught defect, fixed before handoff).
- Same-environment screenshot determinism held: the persona-learning PNGs
  were byte-identical across two runs on this machine, supporting D-0018's
  environment-pinned baseline rule.
- The collab Stop-hook sibling misattribution that cost worker cycles in both
  Wave 1 lanes is root-caused and fixed: room-scoped `spawns.json` records
  now filter on `spawned_by_sid` in `stop_report()` and `wait_for_activity()`.

## D-0020 — Gate 3 is accepted

**Owner:** release-director

**Evidence:** [WAVE3_LIBRARY_CONTRACT.md](archive/WAVE3_LIBRARY_CONTRACT.md) (ratified
before implementation, amended A1/A2 under its own change rule); commits
`ff39159`/`8408aad`/`9db4500`. Director-run in the qualified `.venv`: cheap
suite `2114 passed / 0 failed` (+142 over the Wave 0 baseline), the
privacy-wipe contract suites green against the widened history schema, the
137 new library tests, and 28 ducker tests.

**Decision:** Accept Gate 3. Wave 4 (Library UI) may start once the Wave 2
lane releases the shared composition root, so the two lanes never hold
`signal-desk.html` concurrently.

**Rulings on the lane's open findings:**

- **Restore fidelity:** a restored recording yields a pending draft whose
  `final_text` is the raw transcript (the full pipeline would double-create a
  draft). Accepted for `v0.2.0-alpha.1`: the draft is pending, opens in Talk
  for review, and Talk's ordinary revise path can clean it. Wave 4's UI must
  label restored drafts as raw transcripts; a process-without-creating-draft
  pipeline seam is the recorded follow-up if that labeling proves
  insufficient.
- **Ducker stranding (reported by sup-talk's lane, fixed at integration):**
  emergency stop now unducks unconditionally, and ducks carry a generation
  captured at recording start so a stop that lands before the async duck
  commits wins. Gate 2's "emergency stop releases ducking" bullet is now
  true at the backend level.
- The `_parse_date_bound` docstring overclaim was corrected at integration:
  space-separated datetimes are deliberately treated as date-only and
  widened to end-of-day, and the docstring now says so.

## D-0021 — Gate 2 is accepted

**Owner:** release-director

**Evidence:** Commits `eda4ae0` (lane) and the integration commit following
it. Director-run: renderer unit `963/963`; production QA `16/16` including
the five new Talk scenarios (capture actions, single delivery selector,
send-result surface, confidence-links-to-Settings, and
`editing-teaches-only-with-approval` — the restored D-0018 trigger, proving
save performs zero teach calls and consent+confirm performs exactly one,
carrying the edited text and `consent: true`); preview `28/28` and legacy
`37/37` unregressed; build green.

**Decision:** Accept Gate 2. The Wave 1 QA substitution recorded in D-0018 is
retired — the original "editing teaches only with approval" invariant is now
asserted directly.

**Ratifications:**

- Three single-owner intentional cuts in Talk: the context-panel persona
  dropdown, the confidence slider, and the delivery-mode select were all
  unbound controls miming Settings-owned profile fields; Talk now displays
  each read-only with a link to the real owner. A per-utterance persona
  picker needs a per-draft persona concept and is Wave 5 scope.
- "Send to Chat" as the primary-button label when `send_mode` is `auto_send`
  and no delivery segment is selected.
- Two QA-fixture corrections at integration, neither weakening an assertion:
  the teach scenario's request capture moved from `page.on('request')` —
  which can never see backend traffic because the renderer talks through the
  main-process IPC proxy — to the stub itself, the one place every real
  request lands; and the send scenario's stub became stateful so GET /drafts
  reflects the post-send draft exactly as the real backend does.

**Deferred with reasons, not silently:**

- Controller capture-path convergence is Wave 10 scope; no controller
  bindings exist yet. The shared reducer contract is the convergence
  mechanism when they arrive.
- "Emergency stop releases the privacy lease" waits for Wave 8, which
  introduces the lease; recorder, TTS, pending injection, mute key, and
  (as of D-0020) audio ducking are all released today.

## D-0022 — Gate 4 is accepted

**Owner:** release-director

**Evidence:** Commit `5340c67` plus the Wave 4/5 integration commit;
director-run: unit `1105/1105`, Library QA `13/13`, full production target
`42/42`, preview `28/28` and legacy `37/37` unregressed, build green.

**Decision:** Accept Gate 4. `LIBRARY_PLACEMENT_MAP` ends at 26 `wired`,
2 `intentional_cut`, 0 blocked/false/todo — the Gate 4 rule, enforced by
tests, not convention.

**Ratifications and recorded follow-ups:**

- The multi-status group filter cut is ratified: `GET /library/search` takes
  one status, and merging per-status streams would make pagination lie. The
  un-cut seam (a repeated `status` parameter) is recorded for a later wave.
- Unconfirmed delete/clear previews are built client-side from data the
  client already holds, content-free by construction and by test. The route
  layer's `HTTPException` drops the backend's own preview; returning a JSON
  body with it is a recorded follow-up if backend authority is wanted.
- The clear dialog quotes only observed counts and never a reassuring zero;
  a `GET /library/counts` (or clear-preview counts) is the recorded seam.
- The Library contact filter remains a declared client-side narrowing with
  both counts printed; a backend `contact` filter parameter may open now
  that Wave 5 qualified contacts.
- Fixed in passing: retained recordings were dated to 1970 (epoch seconds
  read as milliseconds).

## D-0023 — Gate 5 is accepted

**Owner:** release-director

**Evidence:** Commits `f695fe7` and the integration commit; director-run:
unit `1105/1105`, Wave 5 QA areas `5/5` + `6/6` + `2/2` inside the `42/42`
production run, contact/server suites `129 passed` in the qualified venv
(including five new tests for the retroactive-contact route), build green.

**Decision:** Accept Gate 5. The persona shell is singular (New,
Build-with-AI, and Edit are three entries to one dialog with one save path;
the cross-document fallbacks are deleted); tags/"last updated"/preferred
destinations render nowhere; traits show `Experimental — unavailable` with
the reason and no enabling control (D-0006); both D-0005 toggles ship OFF
with the full six-part disclosure; contacts are COMPLETE per D-0004 —
manage, edit, delete, apply, clear-applied, sticky selection, status-bar
cell, and retroactive application.

**Rulings:**

- sup-studio's reading of D-0005 is ratified: "Use speech delivery signals"
  is a live opt-in (its preservation gate holds a current `PASS 3/3`),
  while the audience control is rendered, disclosed, and unswitchable —
  `use_audience_context` is deliberately uncollectable by any save path.
  Enabling audience remains a future director decision at its own gate.
- Retroactive contact application landed at integration as
  `POST /drafts/{id}/contact` (WAVE5_INTEGRATION_DIFFS §5 applied verbatim:
  metadata-only, never re-runs cleanup, refuses ids that name no existing
  contact, empty id clears; five tests). The renderer affordance that calls
  it is the one recorded deferral, scheduled with Wave 6's Library/privacy
  polish; `setDraftContact` is already exported for it.
- Five QA-fixture corrections at integration, none weakening an assertion:
  stub handlers that captured the request object as "body"; persona-card
  clicks that substring-matched the wrong card via trait-slider hints (now
  `data-persona-name` attribute selectors); the missing `current_preset`
  stub the active-badge assertion depends on; per-scenario reset of the
  stateful contacts stub; and `GET /personas/:name` stubs for the Edit
  loader (the harness matches raw, percent-encoded pathnames).

## D-0024 — Gate 7 is accepted

**Owner:** release-director

**Evidence:** Commit `b8a670e` plus the integration commit; director-run:
109 targeted python tests plus the full cheap suite `2382 passed / 0
failed`, renderer unit `1137/1137`, Wave 7 QA `10/10` on first execution
inside the `52/52` production board, preview `28/28` and legacy `37/37`
unregressed, build green.

**Decision:** Accept Gate 7. Every checklist bullet is evidenced:
deterministic resolution, honest Default for unknown/Wayland, debounce,
recording-hold (the recording state is pushed into the service from the
runtime-status builder, applied at integration), disable-able one-sentence
announcements, per-application pin and temporary override, and the 50-token
gaming completion ceiling now actually consumed by `_call_api` after its
64-token floor — order is load-bearing and commented. The no-recipient rule
is enforced three ways (schema rejection, closed snapshot vocabulary walked
by test, class-only window detection), and `perform_output_action` maps every
input-synthesising action to `copy_only` while a game is focused.

**Also recorded:** the `app_profiles` store is declared `personal` in the
privacy registry — the pinned map records which applications the person
runs, and under-claiming that as configuration would defeat the report.
sup-appcontext caught the director's own D-3b defect (helpers defined but
missing from backend.js's export block) and adapted to the authoritative
integration naming; the honest-degradation path it shipped (feature reports
"unavailable", never invents a profile) worked exactly as designed while
the export was missing.

## D-0025 — Wave 8A checkpoint accepted; Gate 8 remains open

**Owner:** release-director

**Evidence:** Commit `c23ae28` plus the integration commit; director-run:
the lane's 288-test set re-run under the qualified venv inside the
404-test targeted run and the `2382`-test cheap suite; provenance manifest
guarded by test.

**Decision:** Accept the Wave 8A checkpoint. Landed and wired: the
D-0010 schema split with unconditional idempotent migration and legacy
projection at all four profile call sites (migrate-then-project order is
load-bearing); the AudioInputBroker as the one microphone owner with the
recorder and wake listener subscribing; push-to-mute driven by
`voice_privacy.mode`; `/capabilities` audio words, the `/audio/status`
snapshot, and unconditional broker quiesce in both the privacy-wipe and
emergency-stop paths; the wake model provenance manifest (zero bundled
model binaries; CC-BY-NC-SA classifiers excluded; runtime downloads pinned
and hash-verified).

**Explicitly not yet Gate 8:** the pre-trigger ring and trailing-silence
command capture are unit-tested but unwired (the recorder needs a
prepend-audio entry point — Wave 8B work); capture isolation has no
adapter (`isolate_capture_streams` is reserved and degrades visibly);
`restore_complete` is constant `True` until 8B's journaled lease; wake
`qualified` stays false until measured qualification exists. Low findings
WMP-3 (allowed-licenses enforced only by test, not runtime) and WMP-4
(Kokoro license asserted, not verified) are recorded, neither blocking.
The taskSafe allowlist gains the `.venv/bin/python` pytest/py_compile
patterns so no future lane has to smuggle site-packages through a plugin.

## D-0026 — Gate 8 is accepted

**Owner:** release-director

**Evidence:** Commits from the Wave 8B lane and integration; director-run:
full backend suite `2772 passed / 0 failed`, renderer `1216/1216`,
production QA `63/63`, preview `28/28`, legacy `37/37`, build green — and a
LIVE capture-isolation qualification on this machine (PipeWire 1.0.5 via the
PulseAudio compatibility server, pactl 16.1): a second application's real
capture stream was muted while engaged and restored exactly
(`restored: 1, gone: 0, failed: []`), with the journal written before the
first mute and cleared on release. The crash-recovery path was exercised
twice against genuine crash artifacts (a driver error mid-qualification left
a real journal; `recover_on_startup()` read it, classified the vanished
stream `gone`, and cleared it).

**Decision:** Accept Gate 8. Every checklist bullet holds: no stop path
leaks a held mute key (the lease releases on normal stop, silence auto-stop,
watchdog, failed start, emergency stop, wipe, shutdown, and crash-via-journal);
prior mute states restore exactly and already-muted streams are never
recorded so restore can never unmute a user's own choice; BetterFingers'
own stream is identified by process identity, never name; the wake detector
and recorder share the broker's single stream; the first command word
survives activation through the wired pre-trigger ring (which re-arms after
each command so the second wake keeps its first word too); wake model
licensing is manifest-guarded with runtime enforcement (WMP-3 closed); and
the privacy wipe closes the wake stream, wipes the pre-trigger ring, and
releases the lease.

**Recorded residuals, none blocking:** Windows isolation is a documented
feasibility design and Windows ships push_to_mute with honest status (as
D-0010 always allowed); `partially_restored` is produced but not yet
surfaced in the renderer (Wave 11 parity work); measured wake qualification
does not exist, so `wake_status.qualified` stays false and no wake support
claim may ship without it; WMP-4 (Kokoro license verification) stays open in
the TTS lane. One genuine discovery from the live run: PipeWire's
per-application stream-restore memory re-applies a remembered mute to an
application that REOPENS its stream after a BetterFingers crash — the
index-keyed journal correctly restores live streams and classifies vanished
ones, but cannot reach the audio server's own per-app memory. Recorded as a
known limitation with the design tension noted (fixing it needs application
identity in the journal, which is content-free by design).

## D-0027 — Gate 9 is accepted

**Owner:** release-director

**Evidence:** The Wave 9 lane commit and integration; director-run: backend
`2772/0` including the 158 Wave 9 tests, renderer `1216/1216`, the eleven
`wave9-actions` scenarios passing on first execution inside the `63/63`
production board.

**Decision:** Accept Gate 9. The validator rejects every unsupported verb
with a reason (never by silently dropping); URI and path inputs are
normalized and bounded (dot-dot refused, dangerous schemes refused by name);
workflows cannot name anything outside the user-confirmed registry; unknown
commands are unexecutable by construction and explain themselves without
ever showing command syntax; partial launch failure reports per step with
two-of-three as `partial`, never success; run history holds status codes
only, with a sanitizer that drops prose rather than trusting callers; and
launching only ever passes argument arrays with `shell: false`, asserted
against fields packed with shell metacharacters.

**Rulings:**

- The lane's decision to withhold a bare `applications:launch` IPC channel
  is ratified emphatically — it would bypass the approval gate the wave
  exists to build. The main-process run executor (call `/workflows/run`,
  execute the approved steps, post per-step codes to `/workflows/run/record`)
  is the named follow-up, scheduled with Wave 10 so controller/Stream Deck
  invocation and execution land against the same contract.
- The registry IPC channels were registered through `handleTrusted` rather
  than the doc's raw `ipcMain.handle`, matching the repo's sender-validation
  convention for privilege surface.
- Voice/keyboard/controller/Stream Deck invoking the same action ID is
  deferred to Wave 10 exactly as D-0021 deferred controller capture — the
  contract exists; the devices come next.
- The pre-existing `parse_command` over-trigger (an unanchored "use …"
  pattern resolving to switch_persona) is pinned by a regression test and
  assigned to Wave 11 polish; it cannot reach a launcher workflow.
- Windows launch adapters are designed and mockable but unqualified, and
  say so in the plan object itself, not only in comments.

## D-0028 — Gate 6 is accepted

**Owner:** release-director

**Evidence:** The Wave 6 lane handoff and integration; director-run: backend
`2990 passed / 0 failed`, renderer `1288/1288`, production QA `71/71`,
preview `28/28`, legacy `37/37`, build green.

**Decision:** Accept Gate 6. The registry is complete in both directions —
30 categories with real paths/size/wipe/verify callables (the Phase-2.1
stubs are gone and a test forbids their return), reconciled against the
filesystem with the report-cannot-lie-by-omission agreement test now also
surfaced to the user as an unmapped-file warning. `_perform_privacy_wipe`
is registry-driven with the quiescence protocol intact; the factory-reset
executor finally exists behind the typed phrase `DELETE EVERYTHING`
(never a boolean anywhere in the chain) and covers Python and Electron
state; persona-learning gains its full disclosure surface; export reads
`included_in_export` instead of ignoring it; and the D-0023 retroactive-
contact affordance landed.

**Ratified lane rulings:** persona_learning and contacts move to
conversation-tier — the shipped wipe has ALWAYS deleted both, and
declaring them personal-tier would have silently stopped clearing user
text; the registry follows the code, not the other way. Any string the
user typed sets `may_contain_user_text` (`stream_deck_config` True for
its key titles, `controller_bindings` False as a closed-enum document).

**Notable fixes accepted:** undeclared `.bak-v<N>`/`.corrupt` migration
siblings — verbatim user text invisible to every wipe — now declared for
all 14 versioned stores; verifications no longer create the files they
check, with a byte-identical-directory test; the wipe tests' vacuous
split-root arrangement fixed at `app_paths.resolve_base` with a
declared-path-matches-store guard.

**Recorded deferrals:** dedicated QA scenarios for the five new privacy
Settings groups (unit-covered; the prod sweep's zero-console-error nav
covers them indirectly) fold into Wave 11's audit; the legacy
`index.html` privacy section keeps its copy-fix only, with Wave 11
ruling whether the rollback surface needs more or an intentional cut.

## D-0029 — Gate 10 is accepted (software); hardware stays unqualified

**Owner:** release-director

**Evidence:** The Wave 10 lane handoff, correction note, and integration;
the same suite totals as D-0028, with the eight `wave10-input` scenarios
green inside the `71/71` production board.

**Decision:** Accept Gate 10's software contract. Controller reconnect,
device-loss release through the SAME Wave 8 lease/broker path (no second
release mechanism), bounce debounce, chord/sequence timing to the
millisecond, the game-setup wizard whose test step drives a rehearsal
dispatcher with no handlers (it cannot fire a send by construction), the
Stream Deck plugin as a thin adapter owning no workflow definitions, and
the D-0027 run executor as the launcher's only caller behind a
workflow_id-only typed channel — all landed and tested. The dispatcher
is wired to the same functions the HTTP routes call; `cancel_capture`
and `inject_latest` are deliberately unset rather than second-implemented,
reporting `unavailable` honestly.

**Unqualified, stated plainly:** no controller or Stream Deck hardware is
attached to this machine (pygame enumerates zero joysticks), so both
device matrices remain UNQUALIFIED with the 16-step manual pass in
WAVE10_QA.md as the operator's checklist — priority item: unplug the
controller mid-dictation and confirm the microphone releases through the
lease. `command.begin/end` and the two settings-activation actions
report `unavailable` pending backend entry points; Wave 11's ledger
resolves each as wired-later or intentional_cut. Accepted defects fixed
in passing: the dead chord-window constant hiding real input lag, the
phantom button-4 default, Wave 9's Run button claiming execution before
an executor existed, and the Stream Deck store that could not read its
own output.

**Also recorded:** both lanes edited shared/integration-owned files
directly this wave, coordinating the swaps between themselves through
claims and the room rather than through documented diffs. The work
arrived tested, cross-reviewed, and green, and the director reviewed it
at integration — the discipline's purpose (serialized shared-file access
with review) was served by a different mechanism, and this record keeps
that deviation visible rather than silent.

## D-0030 — Wave 11 accepted; Gate 11 is NOT accepted

**Owner:** release-director

**Evidence:** The Wave 11 lane handoff plus integration; director-run:
backend `3017 passed / 0 failed`, renderer `1300/1300`, build green,
parity validator reporting zero errors on a regenerated ledger, and the
three QA boards under the flip — default target (which is now the
production page, asserted with an empty environment), `BF_UI=legacy`, and
the preview target.

**Decision:** Accept the Wave 11 *work* — the default flip, the version
centralization, the rollback proof, and the re-audit tooling — and
explicitly **do not accept Gate 11**. The strict ledger stands at
**161 wired / 10 intentional_cut / 267 blocked**, and the gate forbids any
blocked row. Signal Desk is now the product; it is not yet fully evidenced
as the product, and the honest number stays on the board.

**What the flip means concretely:** `BF_UI` unset opens `signal-desk.html`;
`legacy` opens `index.html` as the rollback path; `signal-desk` still opens
the QA preview per D-0007; `signal-desk-prod` remains a compatibility
synonym so every committed Wave 1–10 invocation keeps working; an
unrecognised value falls through to the shipping product rather than a dead
app. `tests/test_rollback_store_parity.py` proves no Python source can
observe `BF_UI`, so the backend cannot store anything differently for
either page — flipping forward and rolling back lose nothing.

**Ratified lane rulings:** R-1, the legacy page's smaller privacy surface,
is an intentional cut with its cost stated (a rolled-back user can still
wipe and export — both registry-driven and identical on either page — but
cannot browse the store list or the learning disclosure there). R-2, none
of the D-0029 `unavailable` actions are cut: they need backend entry
points, and cutting them would be deciding the product does not want
controller-driven persona switching, which no lane had the standing to
decide.

**The honesty note is accepted as a limitation, not a defect:** `wired`
here means anchored in the shipping page, handlers resolve, and something
exercises it. The failure-state, accessibility, and privacy legs rest on
the accepted Gate 1–10 evidence for the workspace each row sits in rather
than on a per-row pass. The ledger header says so; Gate 11 acceptance will
require closing that gap or recording it as an accepted release
limitation.

**Two QA fixture faults found at integration, both fixed, neither a
product defect:** the app-context override stub was static, so the
three-second status poll repainted the rail back to the un-held profile a
moment after an override landed — the real service holds the override in
memory, so the stub now does too (pins likewise, being durable). And the
learned-example *list* was asserted visible when it is legitimately empty
and therefore zero-height on an install that has taught nothing; the sweep
now asserts the disclosure paragraph, which is what Gate 6 actually
requires the screen to say.

**Gate 11 remediation, ordered by cost:** the blocked rows split 91
product gaps and 176 evidence gaps, so the campaign is mostly QA
authoring, not feature work. First the evidence lane — retarget
`personas.mjs` to the production page (23 rows, no product change), author
overlay-window scenarios (18 rows), and resolve the 57 rows whose source
text names no code handle at all. Then the product lane — chiefly the
hotkey and wake-word capture controls, the legacy model-manager surface,
and the dashboard status cards, each of which must either gain a
production home or be cut against a named replacement row. Progress is
measured by rerunning `tools/parity_validator.py`, not by narration.

## D-0031 — Wave 11B/11C accepted; Gate 11 still NOT accepted at 21 blocked

**Owner:** release-director

**Evidence:** Director-run after both remediation rounds: backend
`3034 passed / 0 failed`, renderer `1510/1510`, build green, ledger
`396 wired / 21 intentional_cut / 21 blocked` regenerated and byte-identical
under `PYTHONHASHSEED` 1, 7 and 12345, validator clean.

**Decision:** Accept the remediation work — **139 blocked → 21** across two
rounds, from a Gate 0 baseline of 434 — and hold Gate 11 open. The gate
forbids any blocked row and 21 remain. Nineteen are evidence rows and two are
product rows (`#toggleRecordingButton`, `#sendActionSelect`), so what is left
is small, named, and mostly not feature work.

**The real product regression this round caught:** since the Wave 11 flip made
Signal Desk the default, *no user had a capture overlay or a Review Deck at
all*. The elements shipped and the new overlay QA drove them directly, so the
audit could not see it — the only caller of `overlay:update-status` /
`review:show` in the repo was legacy `main.js`. `features/overlayBridge.js` is
now the production caller, forwarding every voice-status message (including the
quiet ones the put-away path depends on) with show/hide policy left in the main
process so the two dashboards cannot drift. This would have shipped invisibly.

**A third measurement defect, found at director verification (C-5):** the
comment stripper tracked string state but not REGEX literals, so
`.replace(/[&<>"']/g, …)` opened a phantom string at the quote inside its
character class, and every comment until the next matching quote survived —
reopening the comment hole by another route. Five production files carry that
exact escape-HTML regex, the composition root among them; the confirmed victim
claimed `#sendActionSelect` shipped when the id existed only in a comment.
Regex literals are now tracked, division is distinguished from literals by
expression position, and both directions have regression tests. That makes
three separate ways this tool could lie, all found and closed:
comments-as-evidence, `\b` blocking endpoint coverage, and hash-seed-dependent
anchors.

**Rulings on what remains:**

- **The onboarding "correct cuts" premise was false and is overturned.**
  Production ships the full four-step wizard on the shared guided-flow shell —
  it was never a single-screen gate. Cutting those rows would have recorded a
  feature as absent while it shipped. Evidenced instead.
- **C-6 (`#draftConfidence`, UI-06-021 / UI-14-007): stays blocked, not cut,
  pending a Wave 12 ruling.** The id resolves only through the "an id may live
  in JS" fallback while `signal-desk.html` has no such element, so
  `renderConfidenceBadge()` is a permanent no-op on the shipping page. The
  capability is not missing — Talk's meta strip shows the score — but a dead
  code path plus a live replacement deserves a deliberate decision, not a
  convenience re-anchor at the end of a long session.
- **The overlay isolation fix did NOT work and is recorded as such.**
  `review-overlay-rewrite-instruct-and-read` fails 3/3 standalone while passing
  inside the full board, so its area is still order-dependent. It is not
  counted as evidence, and the reachability of the overlay windows rests
  instead on `production-page-drives-both-overlay-windows`, which passed on
  every run.
  **Update (2026-07-29):** it now fails inside the full board as well
  (`96/97`, empty rewrite capture). So this is not merely order dependence —
  the scenario is genuinely broken, and the earlier board passes were the
  lucky side of a race. Still not counted as evidence; it needs a real fix,
  not a rerun.
- Two rows (`UI-12-008`, `UI-15-007`) assert *negative* properties — "no
  backend calls", "no donation prompt exists anywhere" — which have no handle
  by construction. They need a director ruling in Wave 12, not a ledger row.

**Standing correction for future lanes:** `settingsWorkspace.js:49-57` asserts
a `ReferenceError` that does not occur (an element `id` is exposed as a window
property, so the bare identifier resolves). The comment is wrong and outlived
the lane that found it.

## D-0032

**Wave 12 UI rulings, executed by sup-ui (2026-07-29).** Three of the items the
Wave 12A session left open for a director ruling are now settled, and one
correction below matters more than any of them.

**C-6 (`#draftConfidence`, UI-06-021 / UI-14-007): CUT on the shipping page.**
Ruled by the release director; both rows move `blocked` -> `intentional_cut`.
The capability is not being removed — the confidence read-out ships live in
Talk's meta strip as `#sdConfidenceValue` / `#sdConfidenceBarFill`, already
evidenced by `app/tests/talkDraftSurfaces.test.mjs` (which also pins the honest
case: an unknown score reads `—`, not `0%`). `index.html`'s element and its
behaviour are deliberately RETAINED — it is the rollback path, and this ruling
does not touch it.

**Correction to the record, and the reason this ruling is not a formality:** the
two ledger rows justified themselves with *"Production anchor(s):
`#draftConfidence` in `app/src/renderer/signal-desk.html`"*. That statement was
false. The id occurs zero times in `signal-desk.html`. It resolved only through
the "an id may live in JS" fallback, matching `features/drafts.js`'s
`getElementById('draftConfidence')`, and the ledger then reported the *location*
as the production page rather than as the JS file the fallback actually matched.
So these rows were not "anchored in production but missing QA" as they claimed —
they were never anchored in production at all, and the D-0015 chain was being
satisfied by a mislabelled pointer.

The scope of that mislabelling is NOT established. Only these two rows were
checked, because they were the two under ruling. Any other row whose evidence
rests on an id-only anchor reported as living in `signal-desk.html` deserves the
same one-line check before it is read as production evidence. Recorded as an
open audit item rather than quietly fixed for two rows and forgotten.

**UI-12-008 and UI-15-007 (the negative-property rows): evidenced by static
contract test, both now `wired`.** These sat blocked for a structural reason,
not a product one — "no backend calls" and "no donation prompt anywhere" have no
production anchor by construction, because an absence has nothing to point at.
The handle they lacked is `app/tests/negativeProperties.test.mjs`, built on the
`mainScopeLint.test.mjs` pattern of asserting a property over real shipping
source. Three deliberate choices, each closing a way this kind of test lies:

- The absence checks are paired with a POSITIVE one asserting
  `review-overlay.html` does route through `window.betterFingers.backendRequest`
  — otherwise a file that made no calls at all would pass the absence check
  trivially and prove nothing.
- The detectors are fed known violations (a Patreon link, a mixed-case "Buy Me A
  Coffee", a bare `fetch(`) in their own test, so a narrowed term list or a
  fat-fingered matcher fails loudly instead of going permanently, quietly green.
  An absence test passes for two very different reasons — the property holds, or
  the detector is broken — and those are indistinguishable from a green run
  unless the second one is made checkable.
- The source is read RAW, with no comment stripper, deliberately. This file
  already records a stripper in this repo that mishandled regex literals and
  swallowed real code, letting a lane claim an id shipped when it existed only
  inside a comment. A subtly-wrong stripper fails OPEN here — it would hide a
  real call. The cost is that a future comment writing `fetch(` in prose trips
  the test; rewording a comment is a far better failure than a false green.

The donation check is scoped WIDER than the row it settles: the source row was
hand-scoped to index.html + main.js + features/* + overlays and left the caveat
"if one exists it must live outside this scope". The test walks the entire
renderer tree, which settles that caveat rather than inheriting it.

**Ledger effect:** `396/21/21` -> **`396/23/19`**, regenerated by
`tools/parity_ledger_build.py` from source-level annotations in
`tools/parity_anchors.py` — NOT hand-edited. `parity_validator.py` reports the
ledger internally consistent and bound to source; `tests/test_parity_regen.py`
passes, which it did not while the ledger was hand-edited.

**Correction, recorded rather than quietly fixed.** This entry first claimed
`398/23/17`, from hand-edits made directly to `PARITY_INVENTORY.md` before it
was understood that the ledger is a GENERATED artifact. That was wrong twice
over: it broke `test_parity_regen.py` (blocking another lane's green-suite
gate), and the two rows hand-moved to `wired` — `UI-12-008` and `UI-15-007` —
were exactly the "hand-claimed wired the generator does not derive" that the
strict ledger exists to prevent. Both are back to `blocked`, and the C-6 cuts
were re-expressed as `CUTS` entries so regeneration reproduces them.

**The negative-property rows are now solved — see D-0035.** They were left
`blocked` at the time of writing because the generator had no vocabulary for
them; director Ruling A authorised building one.

**Final numbers after Rulings A and B: `398 wired / 23 intentional_cut /
17 blocked`.** That is numerically identical to the figure this entry
originally claimed by hand — but every row now earns its status through the
generator, and the two that could not be earned honestly were the reason the
hand-edit was wrong in the first place.

**Not settled here:** the `review-overlay-rewrite-instruct-and-read` failure
recorded above. It is under active root-cause and is deliberately NOT marked
resolved on the strength of a passing rerun. See D-0033.

## D-0033

**`review-overlay-rewrite-instruct-and-read`: root-caused, and it was a real
product bug (2026-07-29, sup-ui).** Verified by execution: fresh build +
`overlay-windows` area = **6/6**, this scenario PASS.

**First, a correction about how it was measured.** Earlier "passing" runs of
this area were run against a stale `app/out/` built hours before the Wave 12A
and port-fix commits landed. They were testing old code. Once every run
rebuilt first, the failure reproduced deterministically — 3/3, across two
revisions (`91d19b8` and clean HEAD `3f86e30`) and two checkouts. **Standing
protocol: rebuild before any QA run.** Two earlier conclusions in this file
rest on un-rebuilt runs and are downgraded accordingly: the claim that the
scenario was "order-dependent" (it was not — it was consistently broken), and
the theory that a dirty dev machine holding port 8080 explained it (killed: it
reproduced in a stub-isolated worktree).

**The cause.** `review-overlay.html`'s `#readButton` handler, on its Stop
branch, posted `POST /tts/stop` and then never reset the overlay state. It was
relying on the `draft_tts_stopped` push handled in `onStatus` — but that push
is what arrives when playback ends *on its own*. A user who presses Stop has
ended it themselves, and nothing guarantees a stopped-event for a stop the user
asked for.

So after one manual Stop, `currentState` stayed `'speaking'` permanently: the
button kept reading "Stop", the badge kept reading "Speaking", and the next
press re-entered the same branch and posted a *second* `/tts/stop` instead of
starting a new read. **The Read control was a dead end after a single use, on
the shipping page, with no user-visible error.** `stopTtsIfSpeaking()` twelve
lines away always did this correctly; only this one handler was missing it.
Fixed by calling `setOverlayState('pending', 'Playback stopped.')` after a
successful post.

**Reconciling the "empty rewrite capture" record.** The earlier note describing
this as an empty *rewrite* capture and this failure at the *TTS* assertion are
NOT two different races. They are one defect class at two call sites: a flat
`expect(...).toHaveLength(n)` on a capture array, read before the async POST it
is counting has landed. Playwright's `click()` resolves when the click is
dispatched, not when the handler's awaited request completes, and the request
goes out over IPC to the main process and back — so the check essentially never
won, which is why it failed deterministically rather than flakily. Wave 11C
fixed the rewrite site with `expect.poll` and its comment says so; the TTS site
was simply missed, so once the first was polled the run advanced to the next
unpolled one. One class, two sites, fixed one at a time.

**Why the two halves were the same bug.** The scenario could not anchor its
capture check behind an awaited UI assertion — the file's own documented rule —
because *there was no UI transition to await*, because the product forgot to
emit one. Fixing the product created the observable the test needed.

The scenario now asserts that transition (`#readButton` back to "Read", badge
no longer "Speaking"), polls the capture counts per the file's rule, and adds
the half the old assertions could never reach: a third press must start a NEW
read (`ttsCalls` -> 2, `ttsStops` stays 1). That extension fails against the
old code, so it is a genuine regression guard rather than decoration.

## D-0034

**Ledger anchor mislabelling, sized (2026-07-29, sup-ui).** D-0032 flagged that
the C-6 rows claimed a production anchor that did not exist and noted the scope
was unknown. It is now measured, by `tools/anchor_audit.py` (new, report-only,
alongside `parity_validator.py`). Of **404** ledger rows claiming an anchor "in
`app/src/renderer/signal-desk.html`", **178 (44.1%)** name at least one token
that is absent from that file.

That headline number badly overstates the problem, and is recorded here with
its breakdown precisely so it is not quoted alone:

| Class | Rows | Meaning |
|---|---:|---|
| **Serious** | **7 (1.7%)** | A `#id`/`.class` present on **none** of the three shipping pages. The C-6 class — the element may exist only in legacy `index.html`. |
| Location-only (overlay) | 24 (5.9%) | An overlay id (`#readButton`, `#statusRing`…) attributed to the dashboard when it ships in `overlay.html` / `review-overlay.html`. |
| Location-only (code) | 147 (36.4%) | A function or route attributed to the page when it lives in `features/*.js` or `api/backend.js` — where it *should* live. An HTML file is not where `acceptDraft()` would ever appear. |

So the great majority is a wrong *location* field on a real, shipping
capability — sloppy, worth correcting, not a false release claim. The real
residue is **7 rows**, one of which (`UI-14-007`) is already cut by D-0032:

`UI-06-020` (`#draftRawText`), `UI-06-023` / `UI-06-057` (`#draftFinalText`),
`UI-06-061` (`#voiceStatus`), `UI-07-135` (`#voicePitchValue`),
`UI-14-007` (`#draftConfidence`, cut), `UI-15-001` (`#personaLearningSection`).

All seven were investigated. **Every capability ships**; not one is missing.
Verified production homes:

| Row | Legacy id named | Real production home |
|---|---|---|
| UI-06-020 | `#draftRawText` | `#sdRawTranscriptText` (Talk meta strip raw cell) |
| UI-06-023 / UI-06-057 | `#draftFinalText` | `#sdRefinedHero` ("Cleaned message, editable") |
| UI-06-061 | `#voiceStatus` | `#sdSignalCoreStatusLabel` / `#sdSignalCoreStatusDetail` |
| UI-07-135 | `#voicePitchValue` | **did not exist — fixed at source, see below** |
| UI-14-007 | `#draftConfidence` | `#sdConfidenceValue` (cut per C-6) |
| UI-15-001 | `#personaLearningSection` | `#sdTeachSection` + the `sdTeach*` panel |

**The re-anchors could not be landed, and the reason matters.**
`parity_evidence.collect()` rejects a `ROW_ANCHORS` declaration for any row
that "already resolves in production on its own" — and by the id-may-live-in-JS
fallback, all of these do, because a `features/*.js` module still calls
`getElementById` with the legacy name. So the guard that exists to stop
redundant declarations is currently the thing PRESERVING the mislabelling: the
ledger cannot be told the truth about these rows while the fallback keeps
insisting they are already fine.

`UI-15-001` is the sharpest proof that the fallback is wrong rather than merely
imprecise. `features/studioWorkspace.js` documents that Studio's teach panel
uses distinct `sdTeach*` ids *precisely so that* `personaLearning.js`'s
self-init IIFE never matches — which means `#personaLearningSection` is
guaranteed **by design** to exist in no page at all. It is still reported as a
production anchor.

**Recommendation (director's call, not taken here):** the collector should
attribute a `#id`/`.class` anchor only to markup, never to a JS file that
merely names the string. That is a change to `tools/parity_evidence.py` with
real blast radius across all 438 rows, which is why it is written up rather
than made at the end of this lane. The verified re-anchor targets are recorded
in `tools/parity_anchors.py` next to the guard that rejects them, so whoever
takes it has the answers already.

**UI-07-135 was a genuine product bug and IS fixed.** Its `#voicePitchValue`
read-out existed on no page, so `voiceStudio.js`'s `updateModulationLabels()`
— which no-ops when the label is missing — left every modulation slider on the
shipping page unlabelled. Adding the four read-outs surfaced a worse defect
underneath: `signal-desk.html` declared energy/warmth/brightness as
`min=0 max=100 step=1 value=50`, while every other layer treats them as 0..1
floats (`MODULATION_PRESETS` use 0.35/0.55/0.7; `gatherVoiceStudioSettingsFrom
Inputs()` defaults energy to 0.5; `buildPersistableVoiceStudioSettings()`
writes them straight to `review_tts_energy/_warmth/_brightness`). That broke
the page both ways: loading a saved `0.5` onto an integer 0..100 range snapped
the thumb to the bottom so a real setting looked switched off, and saving read
the raw slider back, persisting `review_tts_energy: 50` — fifty times its
maximum legal value. Legacy `index.html` always had these right
(`min=0 max=1 step=0.05`), so this was a transcription error when the control
was rebuilt for Signal Desk. Ranges corrected, read-outs added, and pinned by
`app/tests/voiceStudioModulationContract.test.mjs`, which asserts the ranges,
that the markup defaults equal the JS fallbacks (otherwise merely opening Voice
Studio and pressing save silently changes the user's settings), and that a
round trip stays inside 0..1.

## D-0035

**Rulings A and B executed: the collector no longer fabricates anchors, and the
ledger can now express test-backed evidence (2026-07-29, sup-ui).**

**Ruling B — `parity_evidence.resolve()` stopped accepting a lookup as proof.**
The old rule accepted *any* quoted or selector-shaped mention of an id anywhere
in the reachable module text, so `document.getElementById('draftConfidence')`
in a `features/*.js` module counted as evidence that `#draftConfidence` ships.
It does not: a lookup proves something *looks for* an element, not that the
element exists — and the ledger then printed the location as
`signal-desk.html`.

The fix is deliberately narrower than "drop JS-created ids". Some elements
genuinely are built at runtime and never appear in markup, and un-anchoring
those would swap one false report for another. The distinction that matters is
**creation versus lookup**, and `parity_evidence.js_creates_id()` now requires
the former: `.id = 'name'`, `setAttribute('id', 'name')`, or `id="name"` inside
markup built in JS. `getElementById`, `querySelector`, `closest` and `matches`
deliberately no longer count.

**Churn was exactly the predicted neighbourhood.** `tools/parity_churn.py` (new
— a totals line says how many rows moved, never which, and a regenerated
release artifact must not be adopted on a count alone) reported **7 rows** on
the first pass, every one of them already named by the audit, with zero
collateral movement across the other 431.

Those 5 rows dropping out of `wired` is what finally made them re-anchorable:
`collect()` rejects a declaration for any row that "already resolves in
production on its own", so while the fallback insisted they were fine, **the
guard against redundant declarations was the thing preserving the
mislabelling.** They are re-anchored by HANDLE in `parity_anchors.py`
(`#draftRawText → #sdRawTranscriptText`, `#draftFinalText → #sdRefinedHero`,
`#voiceStatus → #sdSignalCoreStatusLabel`, `#personaLearningSection →
#sdTeachSection`) — per handle rather than per row, because `#draftFinalText`
is cited by two rows and a per-row declaration is refused for the one whose
other four handles already resolve. Final churn versus HEAD is **4 rows**, all
deliberate rulings. `tools/anchor_audit.py` now reports **0 serious**.

**Ruling A — `_evidenced_by_test()`, and why it is not a hand-claim.** Rows
asserting a negative property have no anchor by construction. The annotation
binds a row to a test file, the production files the property is asserted
*over*, and a written rationale. `verify_test_evidence()` runs before any row
is classified and raises on three distinct decay paths, each with its own
regression test in `tests/test_parity_evidence_binding.py`:

- the test file is deleted;
- the file survives but no longer *names* the row (the realistic path — nobody
  deletes the test, someone renames its assertion during an unrelated refactor
  and the row keeps a `wired` nothing is checking);
- the file survives and still names the row, but a *subject* file is gone —
  "no donation prompt in X" is trivially true once X stops existing.

Writing those tests immediately caught a self-referential trap worth recording:
the first version bound a fake id to the test file itself, so the string was
present in the very file being checked and the binding held for the silliest of
reasons. The check was right; the test was wrong.

The subject files also satisfy `parity_validator`'s rule that every `wired` row
carry a production-file pointer. That rule was not weakened to accommodate this
— it is met honestly, and a negative property is only meaningful once you say
what it is negative *about*.

**Gates, all green together:** `parity_ledger_build` → `398 wired / 23
intentional_cut / 17 blocked`; `parity_validator` → consistent and bound to
source; `tests/test_parity_regen.py` + `tests/test_parity_evidence_binding.py`
→ 8 passed; `anchor_audit` → 0 serious; renderer unit suite → **1613 / 1613**.

**Ruling C — the 171 "location-only" rows are DEFERRED to post-launch, with the
cause named.** `tools/anchor_audit.py` reports 171 rows whose stated anchor
location does not hold. There is exactly one cause, and it is not 171 separate
mistakes: `build_evidence_cell()` in `tools/parity_ledger_build.py` hardcodes
the string ``in `app/src/renderer/signal-desk.html` `` for every anchor it
prints, regardless of where that anchor actually lives. So functions and routes
that correctly live in `features/*.js` or `api/backend.js`, and overlay ids that
live in `overlay.html` / `review-overlay.html`, are all attributed to the
dashboard.

**No capability is missing and no row's status is wrong** — this is a formatting
string in the report generator, not an evidence failure. The distinction from
the seven rows fixed above matters: those claimed a DOM element that existed on
no shipping page at all, which was a false claim about the product; this is a
true claim about the product with the wrong filename attached.

Deferred deliberately (director ruling, superseding an earlier instruction to
sweep the location fields mechanically — that instruction predated the
root-cause). Fixing it properly needs per-anchor file attribution threaded
through `RowEvidence`, a change to the collector's data model touching all 438
rows, with real regression risk at the end of a lane and no launch payoff.
Mechanically rewriting the prose instead was tried and rejected: a first pass at
it reproduced the exact D-0032 mislabelling at scale, attributing
`#personaLearningSection` to `features/personaLearning.js` and `#draftRawText`
to `talkDrafts.js` — the JS that merely *looks them up*. Automating a bad rule
is worse than leaving an honest, documented gap.

`anchor_audit.py` is the standing record: it runs on demand, prints the exact
count and every affected row, and separates serious findings (currently **0**)
from location-only ones. Nobody can be misled by the ledger's filenames while
that tool exists and reports them.

---

## D-0036 — Delivery is Paste only for this release; UI-06-038 is cut

**Owner:** release-director (operator ruling, 2026-07-29)

**Context:** Gate 11's two remaining product rows needed a wire-or-cut ruling
before the parity lane could run (see `PUBLISH_PLAN.md` task B-3). Row
UI-06-038 is the legacy `#sendActionSelect` dropdown in `index.html` with five
options (Profile default / Copy only / Paste / Type / Open chat then send).
Production does not carry that dropdown: D-0015-era Wave 2 work already
replaced it with the segmented `#sdDeliverySegmented` control
(`signal-desk.html:3211`, painted by `features/talkWorkspace.js:492`), which
offers Type / Paste / Copy — the three actions `perform_output_action()`
actually accepts. A second dropdown, `#sdDeliveryType`, survives only in
`signal-desk-preview.html` and does not ship.

**Decision:** For `v0.2.0-alpha.1` the product delivers by **Paste only**.

1. **UI-06-038 → `intentional_cut`**, named replacement `#sdDeliverySegmented`.
   The five-option legacy dropdown is not rebuilt. "Profile default" and
   "Open chat then send" are not shipped at all this release.
2. **The segmented control is reduced to Paste** — Type and Copy are not
   offered as user choices on the shipping page. Keeping a three-way selector
   that only ever resolves one way would be exactly the overload
   `PUBLISH_PLAN.md` §5 forbids.
3. **Backend actions are untouched.** `perform_output_action()` keeps
   accepting `type` / `paste` / `copy_only`; this ruling narrows what the UI
   *requests*, not what the backend can do. Re-offering Type/Copy later is a
   markup change, not a rebuild.
4. **The gaming-policy downgrade stands and is not a violation of this
   ruling.** `backend/domain/gaming_policy.resolve_send_action()` converts
   `paste` to `copy_only` while a gaming profile is active, because synthetic
   input reaches whatever has focus and in a game that is the movement keys.
   Paste-only describes the user's choice, not an absolute guarantee about the
   wire action; that safety downgrade is deliberate and must survive.

**Still open — not ruled here.** UI-06-016 (`#toggleRecordingButton`, only
partially anchored in production) is the other B-3 product row and remains
undecided. It is unrelated to delivery method and needs its own ruling before
B-3 can close.

**Consequence for the ledger:** blocked count drops by one (17 → 16) once the
cut is declared and the ledger regenerated. Gate 11 stays NOT ACCEPTED.

## D-0037 — Recording toggle UI-06-016 is cut; production ships explicit Start/Stop

**Owner:** release-director (director ruling, 2026-07-29)

**Context:** `PUBLISH_PLAN.md` task B-3b required a wire-or-cut ruling before
any worker could touch row UI-06-016. D-0036 explicitly declined to rule on it.
The row describes the legacy dashboard's single `#toggleRecordingButton` — one
button that flips label and `data-recording` between Start and Stop and calls
`POST /runtime/recording/toggle`. Verified at HEAD `545e582`:

- `#toggleRecordingButton` exists **only** in `app/src/renderer/index.html`
  (the rollback path, §7 "legacy `index.html` extraction") and its handler
  `app/src/renderer/main.js:155`.
- `app/src/renderer/features/runtime.js:78-80` still paints that element, but
  guarded by `if (els.toggleRecordingButton)` — on the shipping page the
  element is absent and the branch never runs.
- The shipping page deliberately replaced it in Wave 2 with an explicit pair,
  `#sdCaptureStartButton` (`signal-desk.html:966`) and `#sdCaptureStopButton`
  (`:970`), plus a never-disabled Emergency Stop, all bound by
  `features/talkCapture.js` — which converges the button path and the hotkey
  path on one reducer with voice-status messages authoritative, and falls back
  to `api.toggleRecording()` → `POST /runtime/recording/toggle`
  (`api/backend.js:564`). The in-file comment at `signal-desk.html:951-963`
  records the replacement and its rationale.

So the *capability* and the *endpoint* are wired; only the legacy element id is
absent. That is precisely the "partially anchored" state the row is blocked on.

**Decision:** **UI-06-016 → `intentional_cut`**, named replacement
`#sdCaptureStartButton` / `#sdCaptureStopButton` (`features/talkCapture.js`).

1. The single combined toggle is **not** rebuilt on the shipping page.
   Rebuilding it would be new scope (§1 rule 1) and a usability regression: a
   control whose meaning depends on invisible state is the failure mode the
   explicit pair exists to prevent.
2. `POST /runtime/recording/toggle` stays reachable and `api.toggleRecording()`
   keeps its fallback role in `talkCapture.js`. This ruling narrows the *UI
   surface*, not the backend.
3. Emergency Stop stays never-disabled (`signal-desk.html:961-962`). A diff
   that adds a disabled state to it is `REJECTED`.
4. No change to `index.html`; it remains the rollback path.

**Consequence for the ledger:** blocked drops by one. With D-0036's cut, the
two product rows together take blocked 17 → 15. Gate 11 stays NOT ACCEPTED
until the remaining evidence rows close.

## D-0038 — Release identity for installer metadata

**Owner:** operator ruling (Donaven Crenshaw, 2026-07-29), recorded by
release-director

**Context:** electron-builder warns `author is missed in package.json`. Benign
for the AppImage but it feeds publisher identity for any future NSIS/dmg
target. D-0008 froze release identity as "Source Arcanum" before any public
artifact existed; the portfolio has since rebranded to Donaven Crenshaw. Board
item #2 escalated the choice to the owner.

**Decision:** Installers ship as **Donaven Crenshaw**,
contact **dcworks@donavencrenshaw.com**. This **supersedes D-0008** for
release-identity purposes only (D-0008's other provisions stand).

- `app/package.json` gains `"author": "Donaven Crenshaw <dcworks@donavencrenshaw.com>"`.
- `app/package.json` is integration-owned: the edit needs a director-granted
  claim and lands with the WS-F packaging work, not as a drive-by.
- Board item #2 is closed by this ruling.

**Consequence:** no code behavior changes; the electron-builder warning clears
when the field lands.

## D-0039 — The dev machine has no discrete GPU; E-1's premise is withdrawn

**Owner:** release-director (director ruling, 2026-07-29)

**Context:** `PUBLISH_PLAN.md` task E-1 and `QA_NOTES.md` entry QA-DOC-001 both
asserted that `KNOWN_LIMITATIONS.md`'s "this machine… no GPU" line was wrong,
because "this machine has an RTX 4060 Ti 16 GB" and
`hardware_report.get_hardware_tier()` returns `dgpu-12g+`/`cuda`. Neither
citation carried pasted output. Worker `w-docs` refused to write the claim
because it could not reproduce it, and escalated. The director then verified
independently on host `Shitbox`:

```
command -v nvidia-smi                  → NOT FOUND
lspci | grep -i nvidia                 → (no output; no NVIDIA device on the bus)
glxinfo | grep "OpenGL renderer"       → Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)
hardware_report.get_hardware_tier()    → {"tier": "igpu", "label": "Integrated GPU",
                                          "gpu_kind": "integrated", "ram_mb": 15632,
                                          "cores": 4}
/proc/cpuinfo                          → 11th Gen Intel Core i7-1165G7 @ 2.80GHz
```

**Decision:** The original E-1 objective is **false and withdrawn**. Executing
it would have written a fabricated hardware claim into the release docs — the
exact failure mode `QA_NOTES.md` exists to prevent.

1. **The dev machine is `igpu`**: integrated Intel Iris Xe, no discrete GPU, no
   CUDA, ~15.6 GB RAM, 8 logical cores.
2. **E-1 is rewritten** (see the rewritten task in `PUBLISH_PLAN.md`): the fix
   is *precision*, not inversion. "No GPU" becomes "no discrete GPU and no CUDA
   on the dev machine; integrated Intel Iris Xe, tier `igpu`".
3. **CUDA and dGPU tiers stay documented as supported-but-unverified-here.**
   The code paths exist; nothing on this host has ever exercised them. No doc
   may claim they are verified.
4. **QA-DOC-001 is corrected in place**, severity held at YEL, with the true
   evidence attached and the false claim struck.
5. This is consistent with the standing room note "Do NOT touch NVIDIA/CUDA
   drivers — CPU fallback is the accepted state", which reads as written by
   someone who also found no working CUDA here.

**Process consequence (the reason this ruling is numbered rather than a silent
fix):** a plan task and a QA entry both carried an unsourced hardware assertion
far enough to become assigned work. **Evidence lines in `QA_NOTES.md` must
paste real command output, not name a command.** The entry format's `Evidence:`
field is amended accordingly. Credit to `w-docs` for refusing the task rather
than completing it.

**Consequence for the release:** none to code. If the RTX 4060 Ti belongs to a
different host (the plan was drafted across machines), any GPU qualification
claim for that host needs its own dated evidence before it may appear in a doc.

## D-0040 — C-1's wake-import magic check is a denylist, not an ONNX allowlist

**Owner:** release-director (director ruling, 2026-07-29)

**Context:** `PUBLISH_PLAN.md` C-1 asks for a "magic-byte check" on wake-model
import, matching the dictation/clone/OCR upload paths. Worker `w-sec` stopped
before implementing and raised the conflict: ONNX is protobuf, which does **not
mandate field ordering**. A leading `0x08` (field 1 = `ir_version`) is a strong
convention, not a spec guarantee. An affirmative "must start with `0x08`" gate
would therefore reject some genuinely valid models — and would immediately
break `tests/test_server_wake_routes.py:214-224`, a passing test whose fixture
uploads `b"tiny classifier bytes"`, a file `w-sec` was not permitted to touch.

**Decision:** The magic check is a **denylist of known-wrong containers**, not
an ONNX allowlist.

1. **The size cap is the actual fix.** The RED vector is the unbounded
   `await file.read()`. Import streams through `upload_safety.stream_to_file`
   capped at `wake_models.MAX_IMPORT_BYTES` (20 MB), **imported from
   `wake_models`, not re-declared** — one source of truth per limit.
2. **Reject known-wrong leading bytes only:** PNG, JPEG, GIF, PDF, ZIP/PK,
   ELF, MZ/PE, RIFF, gzip, and a leading `<` (HTML/XML). Everything else
   proceeds to the existing downstream `wake_models` sha + loadability checks.
3. **`0x08` is never a hard gate.** A soft signal at most.
4. **Errors name what was detected**, not a generic 400.

**Why this shape, explicitly:** the two failure modes are not symmetric. A
false *reject* refuses a user's real wake model in a release whose entire bar
is "clean, hardened, simple to set up" (§5). A false *accept* writes bounded
garbage that the loadability check then refuses. The magic byte was never what
made this path safe; the cap is.

**Consequence:** `tests/test_server_wake_routes.py` stays green and untouched —
no existing passing test is weakened to accommodate an implementation choice,
and §1 rule 3 (no edits outside the claim list) holds. C-1's new tests must
pin all three behaviors: oversize rejected *by streaming*, PNG-header payload
rejected, and a plain non-container payload still **accepted** — that last one
is the regression guard that stops a later worker from "tightening" this
denylist into an allowlist and silently breaking real models.

**Not a weakened implementation.** A reviewer reading only the diff may mistake
the denylist for a shortcut. It is the ruled design; this entry is the record.

## D-0041 — A-1 was already fixed; the 96/97 board figure is stale

**Owner:** release-director (director ruling, 2026-07-29)

**Context:** `PUBLISH_PLAN.md` task A-1 was the wave's designated hardest job:
the Review Deck Read/Stop toggle "drops `POST /tts/stop`", the scenario
`review-overlay-rewrite-instruct-and-read` fails, and the board sits at 96/97.
The plan states the director had ruled it "genuinely broken… needs a real fix,
not a rerun." Worker `w-overlay` was given a dedicated slot for it.

`w-overlay` made **no code change** and reported the scenario already green,
tracing both halves of the fix to commit `ed1bede` (2026-07-29 05:47) — which
predates the `be2ebaa` baseline the plan cites as verified-red. The plan's
evidence (`app/tests/qa/out/…/qa-report.md`, 96/97) came from `91d19b8`, which
predates `ed1bede`. The QA report was simply never regenerated after the fix.

**Director verification (not taken on the worker's word):**

- `git show --stat ed1bede` touches both files: `review-overlay.html` (+10),
  `overlay-prod.mjs` (+38, −1).
- `review-overlay.html:633` now calls `setOverlayState('pending', 'Playback
  stopped.')` immediately after the stop POST. The in-file comment names the
  real defect: without it the button stayed "Stop" and the next press posted a
  **second** `/tts/stop` instead of starting a new read — the control was a dead
  end after one use.
- `overlay-prod.mjs:512-518` no longer checks the capture array flat after a
  `click()` that resolves on dispatch; it awaits the UI transition and then
  `expect.poll`s the count.
- **Three consecutive full-board runs, run by the director:** 97/97, 97/97,
  97/97, with `review-overlay-rewrite-instruct-and-read` ✅ PASS in all three.

**Decision:** A-1 is **COMPLETE with no code change**. `QA-OVL-001` moves to
`VERIFIED` — fixed by `ed1bede`, confirmed by three green boards.

**This clears two items on the §2 publishable bar simultaneously:** the 97/97
board *and* the "three consecutive full-board green runs" requirement.

**Process consequence — the third false premise this wave** (after D-0039's
hardware claim and D-0040's magic-byte assumption). All three shared one shape:
a plan statement asserted as verified, carrying evidence that was real but
**stale or never pasted**. A QA report path is not evidence of *current* state
unless it was regenerated at the commit being described. `QA_NOTES.md` evidence
lines must therefore carry **the commit they were captured at**, not just a path
— amended alongside the D-0039 pasted-output rule.

**Not a free pass.** A worker reporting "already fixed, no diff" is the easiest
possible handoff to fake and the director must always re-run rather than accept
it. Here the claim survived independent verification at every point.

## D-0042 — C-2 gates at request time and includes `/llm/generate_plan`

**Owner:** release-director (director ruling, 2026-07-29)

**Context:** `PUBLISH_PLAN.md` C-2 gates five unguarded dev-route prefixes behind
`BETTERFINGERS_DEV_ROUTES`. The director's spawn brief expressed a preference:
"prefer not mounting at all when the flag is off (a 404 that looks like the
route never existed) over mounting-then-rejecting." Worker `w-server` verified
the prefixes resolve to 10 route decorators, confirmed none appear in Electron's
`ROUTE_ALLOWLIST` (so QA-SEC-002's premise holds), and then stopped to report a
collision the brief had not anticipated.

**Two decisions.**

**1. Gate at REQUEST time, not import time — reversing the director's own
stated preference.** `include_router()` is evaluated at import. `server.py` is
imported once and is very large, so proving the default-OFF path would require
`importlib.reload` of the whole module — fragile, slow, and in direct conflict
with the `conftest.py` `setdefault` below. A request-time check lets the new
test `monkeypatch.delenv` and prove both directions in-process.

Security is equivalent: the handler never executes either way and the caller
receives 404. Import-time mounting buys only omission from the OpenAPI schema —
real but minor. **A guard that cannot be tested in both directions is a guard
nobody knows works.** Testability wins; the brief was wrong.

**2. `/llm/generate_plan` (`server.py:5555`) is IN scope** — 11 routes, not 10.
It has the identical unguarded shape and is likewise absent from the allowlist.
The task prose named `/llm/process` rather than the `/llm/` prefix. Closing ten
holes and knowingly shipping the eleventh because of that wording would follow
the letter of the task while failing its objective. **The scope freeze exists to
stop unrelated work, not to preserve a hole the worker is already standing in
front of.**

**Narrow claim granted:** `tests/conftest.py`, one line —
`os.environ.setdefault("BETTERFINGERS_DEV_ROUTES", "1")`, matching the existing
`BETTERFINGERS_LAZY_STARTUP` / `ALLOW_TINY_MODELS` precedent. This keeps
`test_mcp_client.py` and `test_server_platform_runtime.py` green **without
editing either**, which is why this beat the alternative of patching two test
files to accommodate a new guard.

**Required test coverage — three assertions, because the conftest line makes the
naive version vacuous:** flag absent (`delenv`) → 404; flag `"1"` → reachable;
and the gate helper returns `False` when the variable is unset, asserted
directly, so the **shipped default** is pinned independently of `conftest`. A
future conftest edit must not be able to flip production silently.

**Credit:** the worker asked rather than guessing, twice in one task. Both times
the answer changed the design.

## D-0043 — Voice-preset default is CUT; wake-model deletion is WIRED

**Owner:** release-director (director ruling, 2026-07-29)

**Context:** B-5 and B-8 were investigate-or-escalate tasks. Worker `w-parity2`
investigated and escalated rather than building UI, which is correct under §1
rule 1. Three rows remained blocked. Director-verified independently — all three
functions are defined and exported in `app/src/renderer/api/backend.js` and have
**zero callers anywhere else in the renderer**:

```
setDefaultVoicePreset   -> 0 callers outside api/backend.js
clearDefaultVoicePreset -> 0 callers outside api/backend.js
deleteWakeModel         -> 0 callers outside api/backend.js
```

All three are real, backend-supported, proxy-allowlisted capabilities
(`app/src/main/backendProxy.js:142` and `:144`) with no user-facing trigger.

The default under §1 rule 2 is **cut beats build**. These two rows resolve
differently, and the reason is the difference between a missing convenience and
a one-way door.

### 1. UI-07-126 + UI-15-012 (voice-preset make-default / clear-default) → `intentional_cut`

**Named replacement:** the voice-preset list's existing **Apply** action
(`features/voiceStudio.js` `renderVoicePresetList`, apply-on-click, with
`deleteVoicePreset` for removal).

Nothing the user can do is lost. "Default preset" is a convenience that saves one
click per session; Apply reaches the identical end state, and Delete already
exists. Adding a default-preset concept now means new UI, new persisted state,
and a new empty/conflict state to design — new scope at the finish line for zero
new capability. The two source rows describe one capability; both are cut
together.

### 2. UI-15-014 (wake-model deletion) → **WIRE** *(a deliberate build, recorded as this plan requires)*

**This one is not a missing convenience — the product already opened a door it
will not let the user close.** Utilities' Wake Word UI offers **Import** for a
user-supplied `.onnx` (`utilitiesWorkspace.js:1571`), and there is no removal
affordance anywhere in the app. Director-verified that no other route exists
either: the privacy wipe clears the wake **pretrigger buffer**
(`server.py:3886-3888`, `wipe_wake_pretrigger()`), **not imported model files**.

So a user who imports the wrong file — or any file — cannot remove it. Not from
the list, not from settings, not from a full privacy wipe. That is a data trap in
a release whose stated bar is "clean, hardened, and simple to set up", and it is
the kind of thing §5.5 ("no error state dead-ends") exists to prevent.

Building is justified here precisely because the alternative is shipping an
import feature with no undo. The work is minimal and additive: the backbone list
already renders rows, `deleteWakeModel` is already exported and already
proxy-allowlisted. Scope is one Delete action per imported-model row, with a
confirm step, plus QA coverage.

**Constraint:** only **imported** models are deletable. Built-in/downloaded
backbone models must not offer Delete — removing a shipped model is a different
operation with different consequences and is not in scope.

**Consequence for the ledger:** blocked 3 → 0. **Gate 11 becomes closable.**

## D-0044 — Gate 11 is ACCEPTED

**Owner:** release-director (director ruling, 2026-07-30)

**Gate 11 forbids any `blocked` row.** At `3d935c6` the ledger reads:

```
$ python3 tools/parity_validator.py
source rows : 438
ledger rows : 438
totals      : 411 wired / 27 intentional_cut / 0 blocked / 438 total
OK — ledger is internally consistent and bound to the source inventory.
```

From a wave-opening baseline of `398 / 23 / 17`. **Seventeen blocked rows closed:
eleven wired with real evidence, six cut under recorded rulings** (D-0036,
D-0037, D-0043). No row was hand-edited in `PARITY_INVENTORY.md`; every change
went through `parity_anchors.py` and a regenerated ledger.

**Supporting verification at the same commit, all director-run:**

| | |
|---|---|
| Production QA board | **99/99, three consecutive runs**, on a fresh build |
| Node suite | **1668 / 1668** |
| Python suite | **3098 passed, 0 failed** (clean env — see QA-DOC-005) |

The board is 99, not 97, because this wave added two scenarios (the onboarding
keyboard trap and the persona wizard). §2's "97/97 and three consecutive green
runs" is met and exceeded.

**Evidence standard applied.** Every row was reviewed against the task's own
criteria by re-running them independently, not by reading the handoff. Rows
requiring behavior were rejected if they offered existence checks; the ring-state
test was required to enumerate from the shipped contract rather than a copied
list; the chip test had to move sliders twice to two distinct value sets so a
static default could not fake it.

**What this gate does NOT assert**, stated so nobody over-reads it:

1. **That `glitch-ring.js` is live code.** UI-12-003 counts through a stale
   `PROD_EXTRA_PAGES` mapping (QA-BL-001). Mitigated — B-7 added enumeration
   coverage for `signalCore.js`, the ring production actually loads — but the
   bookkeeping is repaired post-publish, behind a churn proof.
2. **That the product is operator-approved.** Gate 11 is a parity gate. The
   human pass in `OPERATOR_QA.md` has not been performed, and two RED fixes
   (QA-FR-002, QA-UTIL-001) still need a person to confirm they *read* correctly
   — automated tests prove the mechanism, not the impression.
3. **That CI is green.** C-5's gates are committed but unproven, and `ruff` and
   `bandit` have never been run at all.

`RELEASE_BOARD.md` is updated to ACCEPTED accordingly. Gates 12/13 (package
qualification) remain open and are the next work.

---

## D-0045 — `UI-07-041` (`#settingInstantTyping`) is an `intentional_cut`, not `blocked`

**2026-07-31, director, Wave 14.**

Removing the Instant Typing checkbox from the shipping page flipped its parity
row from `wired` to `blocked`, taking the ledger from `411/27/0` to
`410/27/1`. The ledger was right to flag it: the item became *partially
anchored* — the `instant_typing` profile key still resolves in production while
the `#settingInstantTyping` handle no longer does — and a partially anchored
item is not wholly present on the shipping page.

What was missing was the ruling, not the removal.

**Ruling: `intentional_cut`.** The control was removed at the operator's
explicit direction (`OPERATOR_REVIEW.md`, P2 "Remove" list). It was already
disabled on Wayland, so for a large share of users it advertised a capability it
could not deliver — and a control that cannot do what it says is exactly the
class of defect Wave 14 exists to remove.

**The backend capability is untouched, and that is what makes this a cut rather
than a deletion.** `instant_typing` remains a real profile field defaulting to
`False` (`utils.py:798`); `injector.py:286` and `:545` still honour it. It also
remains in `SETTINGS_FIELD_KEYS` with no element — `readFieldStates()` skips
absent elements, so the field is simply never sent from this page and any
profile already carrying the flag keeps working. Nothing was removed from the
engine, and no default changed.

Ledger after the ruling: **410 wired / 28 intentional_cut / 0 blocked / 438
total**, validator OK. The delta against the Gate 11 baseline (`411/27/0`) is
exactly the one row this ruling covers — no other row moved.

**Found by running the full Python suite before merging to `main`, not by
inspection.** `tests/test_parity_regen.py` failed because the committed ledger
no longer matched its generator. Three other failures surfaced in the same run,
all from OR-13's new host-tooling gate short-circuiting tests that fake the
clipboard; those tests now state the precondition they had always implicitly
assumed. Had the merge gone ahead on the node suite alone, all four would have
landed on `main`.
