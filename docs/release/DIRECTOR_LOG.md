# DIRECTOR LOG — publish wave (v0.2.0-alpha.1)

Progress record for the `PUBLISH_PLAN.md` execution wave. Written by the
director (`director-publish`), one entry per event. This file is a **log**, not
a plan: the plan is [`PUBLISH_PLAN.md`](PUBLISH_PLAN.md), the issue intake is
[`QA_NOTES.md`](QA_NOTES.md), the binding rulings are
[`DECISIONS.md`](DECISIONS.md). Nothing here overrides those.

- **Branch:** `publish/wave-13` (cut from `545e582` on `main`)
- **Baseline at cut:** parity `398 wired / 23 intentional_cut / 17 blocked / 438 total`, validator OK
- **Stop line (operator instruction):** stop when nothing is left but operator
  QA and the Linux/Windows install builds — i.e. WS-A/B/C/D/E closed, Gate 11
  accepted, F-1/F-2 not started. At that point `QA_NOTES.md` gets reworked into
  an operator-testable checklist.

## Standing rules for this wave

| Rule | Source |
|---|---|
| Workers run **no** git write commands; the director commits one-task-one-commit | operator ruling, 2026-07-29 |
| Workers spawn **no** sub-agents (no Agent/Task tool, no `collab_spawn`) | operator instruction |
| Nothing reaches `origin` without an explicit operator OK | operator ruling |
| A task is `COMPLETE` only after the director independently re-runs its Review commands | PUBLISH_PLAN §4 |
| A worker touching files outside its claim list has failed the task | PUBLISH_PLAN §1.3 |
| Max 3 Sonnet workers alive at once | collab hard cap |

## Task ledger

Status vocabulary per PUBLISH_PLAN §3: `OPEN`, `IN PROGRESS`, `NEEDS REVIEW`,
`COMPLETE`, `REJECTED (reason)`.

| Task | Lane | Status | Commit | Director verdict |
|---|---|---|---|---|
| A-1 Review Deck Read/Stop | w-overlay | **COMPLETE** | — (no change needed) | Premise was stale; already fixed in `ed1bede` (D-0041) |
| B-1 Onboarding rows | w-parity | **COMPLETE** | `5a4570d` | Delta exactly 3; trap test is real keystrokes |
| B-2 Talk rows | w-parity | **COMPLETE** | `ded3300` | Bound to pre-existing coverage, confirmed behavioral |
| B-3a Delivery = Paste | w-parity2 | **COMPLETE** | `2740396` | Gaming downgrade verified intact |
| B-3b Recording toggle | w-parity2 | **COMPLETE** | `28f1557` | Cut per D-0037 |
| B-4 Persona Wizard | w-parity | **COMPLETE** | `323ba30` | Walks all four steps + back/validation/save |
| B-5 Voice defaults + blend | w-parity2 / w-lastrows | **COMPLETE** | `323ba30`, `7428bb6` | 1 wired, 2 cut per D-0043 |
| B-6 Blend/modulation chips | w-parity / w-parity2 | **COMPLETE** | `323ba30`, `5b09e8e` | Chips proven functional, twice over |
| B-7 Ring states | w-parity2 | **COMPLETE** | `5b09e8e` | Enumeration-driven; signalCore coverage added on ruling |
| B-8 Wake model deletion | w-wakedel | **COMPLETE** | `098dfba` | Built per D-0043; fixed the list it depended on |
| C-1 Wake upload safety | w-sec | **COMPLETE** | `080cd90` | Denylist per D-0040 |
| C-2 Dev route gating | w-server | **COMPLETE** | `20a307b` | 11 routes; default verified outside pytest |
| C-3 project_generator guard | w-foundry | **COMPLETE** | `f0f2b33` | Survived 12 director-chosen escape probes |
| C-4 Wipe-gate unification | w-server | **COMPLETE** | `da21809` | 6/7 converted, 1 documented exception |
| C-5a/b/c CI gates | w-ci | **COMMITTED, NOT COMPLETE** | `70e13fe` | **Needs an operator-authorised push to prove green** |
| D-1 First-run audit | w-firstrun | **COMPLETE** | — (report) | Found the wave's only RED |
| D-2 Per-feature audit | w-firstrun | **COMPLETE** | — (report) | 4/5 pass; Library partial-fail |
| D-3 Talk download feedback | w-firstfix | **COMPLETE** | `630a4bc` | The RED. Director's objection withdrawn — worker was right |
| D-4 Library empty state | w-firstfix | **COMPLETE** | `52c1905` | Exactly one action, real navigation |
| E-1/E-2/E-3 Docs | w-docs | **COMPLETE** | `f321bbe` | E-1 rewritten — its premise was false |
| Regression repair | director | **COMPLETE** | `3d935c6` | Two failures the filtered suites hid |
| F-1/F-2 Package qualification | — | **NOT STARTED — past the operator's stop line** | — | — |

## Log

### 2026-07-29 · Wave opened

- Pulled `main` to `545e582`; cut `publish/wave-13`.
- Verified the plan's stated baseline independently:
  `python3 tools/parity_validator.py` → `398 wired / 23 intentional_cut /
  17 blocked / 438 total`, "ledger is internally consistent and bound to the
  source inventory". The plan's header numbers are accurate.
- **Ruled D-0037** (UI-06-016 recording toggle → `intentional_cut`, replacement
  `#sdCaptureStartButton`/`#sdCaptureStopButton`). Evidence: the legacy
  `#toggleRecordingButton` exists only in `index.html` + `main.js:155`;
  `features/runtime.js:78-80` paints it behind an `if` that never fires on the
  shipping page; Wave 2 replaced it with the explicit start/stop pair bound by
  `features/talkCapture.js`, which still falls back to
  `api.toggleRecording()` → `POST /runtime/recording/toggle`. B-3b unblocked.
- **Ruled D-0038** (release identity → `Donaven Crenshaw
  <dcworks@donavencrenshaw.com>`), closing parked board item #2. Supersedes
  D-0008 for identity purposes only. The `app/package.json` edit lands with
  WS-F, not as a drive-by.
- Board seeded: 17 wave tasks, 4 standing notes (git authority, worker rules,
  rulings, baseline).
- Spawned 3 Sonnet workers (the cap): `w-overlay` (A-1), `w-sec` (C-1 → C-3),
  `w-docs` (WS-E).

### 2026-07-29 · The permission gate

Workers' shell calls block on director review, and undecided requests auto-deny
after 10 minutes — so hand-reviewing every `grep` risked stalling three workers
while I was mid-review of a fourth. Installed a director-authored safelist
(`scratchpad/gate.py`): strictly read-only / test-only command shapes
auto-approve; **everything else still stops for a human read.** Deny-by-default.
Refused shapes include shell chaining, redirects to files, `git` writes, bare
`pytest` (loads ~6.5 GB), pipes into a shell, `python3 -c`, and `find` rooted
outside the repo. Validated against 26 cases before going live.

Two defects found in the gate itself while it ran, both worth recording:

1. **It failed closed on grep alternation.** `grep "a\|b"` was being split as a
   shell pipeline. Harmless direction, but noisy — fixed with a quote- and
   escape-aware splitter.
2. **It was reading truncated commands.** `director.py perms` truncates its
   listing at ~200 chars. The gate was matching the safelist against that
   *truncated* text, so a command with a safe prefix and a dangerous tail past
   the cutoff (`grep …200 chars… ; rm -rf`) could have auto-approved on the
   strength of text no one ever saw. **This was a real hole, not a nuisance.**
   Fixed by reading `permissions.json` directly and always judging the complete
   command. Regression-tested with exactly that payload.

Escalations that reached me and were approved by hand after reading them in
full: chained read-only `git status; git log`; the `nvidia-smi` + tier probe;
system hardware probes; an `xxd` magic-byte loop; and `mkdir` + isolated
`BETTERFINGERS_DATA_DIR` for QA runs (w-overlay isolating the board from the
owner's real data dir — the right instinct, unprompted).

### 2026-07-29 · D-0039 — a false premise caught before it reached the docs

`w-docs` was told, by the plan itself, that this machine has an RTX 4060 Ti and
that `KNOWN_LIMITATIONS.md` was wrong to say otherwise. It ran the probe, could
not reproduce the claim, **refused the task, and escalated** rather than writing
it. Director verification confirmed the worker: no NVIDIA device, tier `igpu`.

The plan task and the QA entry were both wrong. Had the worker complied, the
release docs would have gained a fabricated hardware claim — with a QA process
signing off on it. Ruled as **D-0039**: E-1 rewritten as a precision fix,
QA-DOC-001 corrected in place with real pasted evidence, and the `QA_NOTES.md`
entry format amended — **`Evidence:` must be pasted output, never the name of a
command.** The original QA-DOC-001 cited two commands and pasted neither; that
is exactly how the false claim travelled far enough to become assigned work.

### 2026-07-29 · D-0040 — C-1's magic check, ruled against the plan's literal wording

`w-sec` stopped before implementing C-1's magic-byte check and raised a design
conflict: ONNX is protobuf, which does not mandate field ordering, so a leading
`0x08` is a convention rather than a guarantee. An affirmative allowlist would
risk rejecting users' valid wake models — and would have broken a passing test
(`test_server_wake_routes.py:214-224`) that the worker was not allowed to touch.

Ruled: the size cap is the actual fix; the magic check is a **denylist** of
known-wrong containers. Neither of the worker's proposed options was taken —
both would have edited a green test to accommodate an implementation choice.

### 2026-07-29 · WS-E accepted (`f321bbe`)

Re-ran every Review command myself rather than trusting the handoff — notably
the `434|267|396` grep, which `w-docs` had summarized as "omitted here for
length". All clean: no surviving false GPU claim, every stale parity number
dated or live-with-commit, zero `@app.on_event` sites, `isDeletionOutcome()`
confirmed handling the `{ok, recreated}` dict, and **no gate's accept status
altered** (the one way a docs task could do real damage). Accepted.

### 2026-07-30 · The last three rows, and the bug hiding behind one of them

B-5 and B-8 were investigate-or-escalate. `w-parity2` investigated and escalated
rather than building UI — correct under §1 rule 1 — and I verified its finding
independently: `setDefaultVoicePreset`, `clearDefaultVoicePreset` and
`deleteWakeModel` are all exported from `api/backend.js` with **zero callers
anywhere else in the renderer**, all three proxy-allowlisted. Real, backend-
supported, UI-absent capabilities.

**D-0043** resolved them in opposite directions, and the distinction is the
point: a missing *convenience* versus a *one-way door*.

- Voice-preset make-default → **cut**. Apply already reaches the identical end
  state; a default concept means new UI, new persisted state and a new conflict
  state for zero new capability.
- Wake-model deletion → **built**. Utilities offers Import for a user-supplied
  `.onnx` and had no removal path *anywhere* — and the privacy wipe does not
  cover it (`server.py:3886-3888` wipes the pretrigger buffer, not model files).
  A user who imported the wrong file could never remove it. Shipping an import
  feature with no undo is not a defensible alpha.

Building that then surfaced **QA-UTIL-001**, a defect bigger than the row: the
wake backbone list **never rendered in production at all**. The renderer read
`res.backbones` where the backend returns `{"models": …}`, and `backbone.installed`
where entries carry `downloaded`. The engine badge could therefore never read
"Ready" — the screen told every user their wake engine was not installed while
it was working fine. It read plausibly because the LLM and Whisper payloads on
the *same screen* genuinely do use `installed`. Ruled in scope: without it the
authorised Delete button would have been unreachable dead code.

### 2026-07-30 · Two regressions the filtered suites hid

The full `node --test` suite came back **1666/1668**. Both failures were mine to
own:

1. `qaFirstRun.test.mjs` pinned onboarding-prod at 6 scenarios; B-1 legitimately
   added a 7th. **I accepted B-1 on a filtered run.**
2. The "no renderer page hardcodes a version number" guard failed on a *comment*
   B-3a added to `signal-desk.html`. The guard greps the file and cannot tell
   comment from markup.

Fixed by updating the count (keeping the pin — it guards against losing a
scenario) and rewording the comment (keeping the guard — the renderer genuinely
must not invent a version). **The lesson is procedural and worth more than either
fix: a green filtered run is not evidence of a green suite.** Every task in this
wave was reviewed by re-running its *own* Review commands; that is necessary and
was not sufficient.

### 2026-07-30 · Final verification at `3d935c6`

Run on a **fresh build**, because the QA harness executes `app/out/`, not source:

- Production QA board: **99/99, three consecutive runs.** The board grew from 97
  to 99 — this wave added the onboarding keyboard-trap scenario and the persona
  wizard scenario — so §2's "97/97" bar is met and exceeded.
- Node suite: **1668 / 1668**.
- Parity ledger: **411 wired / 27 intentional_cut / 0 blocked / 438 total**,
  validator OK. **Gate 11's parity bar is met.**

### 2026-07-30 · Where this stops

Per the operator's stop line, the wave ends with WS-A/B/C/D/E closed and F-1/F-2
untouched. Two things are deliberately NOT claimed as done:

1. **C-5's CI gates are committed but unproven.** Their Done-when requires a
   green run on a push, and no push has been authorised. Worse, `ruff` and
   `bandit` are not installed on this machine, so their baselines are **genuinely
   unknown** — possibly clean, possibly hundreds of findings. Nobody should plan
   triage on an assumption here.
2. **Operator QA has not been performed.** [`OPERATOR_QA.md`](OPERATOR_QA.md) is
   the script for it. §1.10 and §5.1/§5.2 exist specifically to confirm the two
   RED fixes read correctly to a human — automated tests prove the mechanism, not
   the impression.

**Eight plan or QA statements proved false or stale during this wave** — a
fabricated GPU claim, an ONNX magic-byte assumption, an already-fixed "broken"
test, a stale QA report, a wrongly-named caller module, two miscounted call-site
tallies, and a parity mapping pointing at dead code. Every single one was caught
by a worker running the command instead of trusting the brief, and in one case a
worker was right against my own explicit instruction. That is the habit worth
carrying into the next wave.

### 2026-07-30 · A 42-failure false alarm, and what it cost

The first full Python run came back **42 failed / 3056 passed** and looked like a
serious regression. It was not. I had exported `BETTERFINGERS_DATA_DIR` and
`BF_QA_USER_DATA_DIR` for the QA board **in the same shell**, and they leaked
into pytest.

Diagnosed rather than assumed, in this order: the failing file passed 28/28 in
isolation and 45/45 under `-k` (so: pollution, not a defect) → re-ran the branch
with `env -u` on both variables → **3098 passed, 0 failed** → and to be certain
the wave had not introduced latent pollution, built a throwaway worktree at
pre-wave `main` and ran the same suite there: **3074 passed, 0 failed**. The
branch adds 24 net new passing tests and breaks nothing.

**The error was mine, in the verification command, not in the code.** Two things
come out of it worth keeping:

1. Filed as **QA-DOC-005**: the QA board *requires* those two variables and
   pytest is *poisoned* by them. A trap whose failure mode impersonates a
   regression deserves a sign, and it is now in `OPERATOR_QA.md` §0.
2. The comparison against pre-wave `main` was the right instinct and cheap
   (~4 min). When a suite goes red late, establishing whether it was ever green
   beats staring at the failures.

### 2026-07-30 · Gate 11 ACCEPTED (D-0044)

`411 wired / 27 intentional_cut / 0 blocked / 438 total` at `3d935c6`. Seventeen
blocked rows closed from a 398/23/17 baseline — eleven wired with evidence, six
cut under D-0036, D-0037 and D-0043. `RELEASE_BOARD.md` updated; Wave 12 is
unblocked and not started.

The gate is deliberately narrow. It does not assert operator sign-off, and it
does not assert CI green. Both are stated in the ruling so nobody reads a parity
gate as a shipping decision.

### 2026-07-30 · Wave closed — what is left is exactly what the operator asked to be left

WS-A, WS-B, WS-C, WS-D and WS-E are closed and reviewed. What remains:

1. **Operator QA** — [`OPERATOR_QA.md`](OPERATOR_QA.md), written for this. §1.10
   and §5.1–5.2 exist specifically to confirm the two RED fixes read correctly to
   a human.
2. **C-5's CI gates** — committed, unproven, and needing an operator-authorised
   push. `ruff` and `bandit` baselines are genuinely unknown.
3. **F-1 / F-2** — the AppImage and .exe builds. Untouched, per the stop line.

Nothing has been pushed. `main` is untouched. All work is on `publish/wave-13`.
