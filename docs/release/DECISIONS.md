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

## D-0002 — Integration branch remains a coordinator action

**Owner:** release-director / coordinator

**Decision:** Create `release/true-betterfingers` from `093eaf2a…` only after
accepting the Wave 0 reconciliation.

**Reason:** The branch does not exist, and repository rules prohibit agents
from creating or switching branches.

**Consequence:** Gate 0 remains open and all implementation waves remain
blocked.

## D-0003 — Preserve and review the complete Wave 0 workset

**Owner:** release-director / coordinator

**Decision:** Retain for coordinator review and commit every exact Gate 0 path
listed in the [release plan workset](TRUE_BETTERFINGERS_RELEASE_PLAN.md#21-retained-wave-0-worktree):
`AGENTS.md`; `.claude`/`.codex` infrastructure and skills; `ACCOMPLISH.md`
repair C; UI/release/persona docs; the regenerated Signal Desk QA report; and
the 23 regenerated PNGs that are pixel-identical but byte-reencoded.

**Reason:** The live Wave 0 worktree contains active infrastructure,
documentation, evidence, and generated QA artifacts. It is inaccurate to
describe only collaboration/hierarchy infrastructure as dirty.

**Consequence:** Repairs A and B are implemented. Repair C remains in
progress. The coordinator must review and commit the full exact workset.
Claude authentication, an MCP restart onto the repaired configuration, and a
real authenticated Claude cross-client spawn remain external blockers before
Gate 0 can pass; the spawn evidence is incomplete.

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
