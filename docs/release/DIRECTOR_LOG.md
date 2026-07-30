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
| A-1 Review Deck Read/Stop | w-overlay | OPEN | — | — |
| B-1 Onboarding evidence rows | — | OPEN | — | — |
| B-2 Talk evidence rows | — | OPEN | — | — |
| B-3a Delivery = Paste | — | OPEN (ruled D-0036) | — | — |
| B-3b Recording toggle | — | OPEN (ruled D-0037) | — | — |
| B-4 Persona Wizard QA | — | OPEN | — | — |
| B-5 Voice defaults + blend | — | OPEN | — | — |
| B-6 Blend/modulation chips | — | OPEN | — | — |
| B-7 Ring states | — | OPEN | — | — |
| B-8 Wake model deletion | — | OPEN | — | — |
| C-1 Wake upload safety | w-sec | OPEN | — | — |
| C-2 Dev route gating | — | OPEN | — | — |
| C-3 project_generator target_dir | w-sec | OPEN | — | — |
| C-4 Wipe-gate unification | — | OPEN | — | — |
| C-5a/b/c CI gates | — | OPEN | — | — |
| D-1 First-run audit | — | OPEN | — | — |
| D-2 Per-feature setup paths | — | OPEN | — | — |
| E-1/E-2/E-3 Doc corrections | w-docs | **COMPLETE** | `f321bbe` | Accepted — all three re-verified independently |
| F-1/F-2 Package qualification | — | BLOCKED (Gate 11) — past the stop line | — | — |

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
