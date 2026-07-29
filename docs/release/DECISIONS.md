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

**Evidence:** [WAVE3_LIBRARY_CONTRACT.md](WAVE3_LIBRARY_CONTRACT.md) (ratified
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
