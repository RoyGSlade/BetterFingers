# BetterFingers kickoff dispatches — Phase 0, Wave 0A

Paste the standing prompt from `worker-prompts.md` (shared core + role block)
into each session FIRST, then paste that session's dispatch below. All four
Wave 0A tasks run in parallel — their claims do not overlap. The coordinator
(you) opens Wave 0B only after all four handoffs are ACCEPTED.

---

## Worker A (`sonnet-backend`) — C0.3

```text
ROLE
You are sonnet-backend, working in the shared BetterFingers checkout.

TASK
C0.3: Recreate the supported Python environment from committed inputs and run
the cheap test suite, producing an exact recorded baseline.

READ FIRST
accomplish.md §2 (verified starting point), §9 Wave 0A row C0.3; the committed
environment inputs (requirements/pyproject/lock files, setup docs); the test
layout to identify which suite is the "cheap" (model-free) suite.

CLAIM
Pseudo-resource __python-env__ only. No source files unless you find a setup
defect — if you do, stop and post a question before claiming anything else.

DO NOT TOUCH
All production and test source. server.py. Node/Electron anything. No
dependency upgrades — recreate the environment exactly as committed.

CONTRACT
The environment must be reproducible from committed inputs alone. The output
of this task is evidence, not code: exact commands used, Python version,
resolver output, and the cheap suite's exact pass/fail/skip counts + duration.

STEPS
1. Recreate the environment from committed inputs; record every command.
2. Run the cheap (model-free) pytest suite once; capture exact results.
3. Classify any failure: environment defect vs pre-existing code issue.

VERIFY
Cheap suite completes; results recorded verbatim (counts, duration, failures
with one-line classification each).

HANDOFF
Use the repository HANDOFF format, release __python-env__, and stop.

STOP CONDITIONS
Stop and post a question if the environment cannot be recreated from committed
inputs, a dependency fails to resolve, or fixing anything would require
touching source files.
```

---

## Worker B (`sonnet-renderer`) — C0.4

```text
ROLE
You are sonnet-renderer, working in the shared BetterFingers checkout.

TASK
C0.4: Reconfirm the Node install, unit tests, Electron build, and model-free
smoke prerequisites, producing an exact recorded baseline.

READ FIRST
accomplish.md §2, §9 Wave 0A row C0.4; package.json scripts; app/ layout;
any existing smoke/QA scenario docs.

CLAIM
Pseudo-resource __electron-build__ only. No source files unless you find a
baseline defect — if you do, stop and post a question first.

DO NOT TOUCH
All production and test source. Python/backend anything. No dependency
upgrades; install exactly what the lockfile specifies.

CONTRACT
Output is evidence, not code: Node/npm versions, install result, exact
`npm run test:unit` results, exact `npm run build` result, and a statement of
whether model-free smoke prerequisites are ready (with what's missing if not).

STEPS
1. Confirm Node/npm versions; run the committed install; record results.
2. Run `npm run test:unit`; capture exact results.
3. Run `npm run build`; capture exact results.
4. Check model-free smoke prerequisites; record readiness.

VERIFY
`npm run test:unit` and `npm run build` both complete with results recorded
verbatim; smoke readiness explicitly stated.

HANDOFF
Use the repository HANDOFF format, release __electron-build__, and stop.

STOP CONDITIONS
Stop and post a question if install diverges from the lockfile, a unit test or
the build fails for a reason that would require source changes, or smoke
prerequisites need new tooling.
```

---

## Worker C (`sonnet-platform`) — C0.1

```text
ROLE
You are sonnet-platform, working in the shared BetterFingers checkout.

TASK
C0.1: Make the collaboration MCP client-neutral and Codex-compatible.

READ FIRST
accomplish.md §6 in full (especially "Cross-client hardening required in
Phase 0"); .claude/collab-mcp/collab_lib.py, hooks.py, server.py,
test_collab.py; .claude/skills/collab/SKILL.md; .claude/settings.json.

CLAIM
.claude/collab-mcp/collab_lib.py, .claude/collab-mcp/hooks.py,
.claude/collab-mcp/server.py, .claude/collab-mcp/test_collab.py,
.codex/config.toml, .codex/hooks.json, AGENTS.md

DO NOT TOUCH
All product source (backend and renderer). server.py at repo root. Existing
message/claim database contents.

CONTRACT
Per accomplish.md §6: client-neutral session identity (explicit env session ID
with safe process-ancestor fallback for both `claude` and `codex`); Codex
project-scoped MCP config; Codex instructions in AGENTS.md; Codex hooks for
session status, inbox delivery, and apply_patch claim checks; apply_patch
touching another session's claimed path must be rejected; document that shell
commands may not write source files. Existing Claude-side behavior must remain
working — additive changes only to the wire format and DB schema.

STEPS
1. Introduce the client-neutral session identity in collab_lib.py.
2. Add .codex/config.toml MCP entry and .codex/hooks.json; write AGENTS.md.
3. Implement the apply_patch claim check in hooks.
4. Extend test_collab.py: E2E with one simulated Claude and one simulated
   Codex client sharing sessions, claims, messages, and one rejected
   conflicting claim.

VERIFY
python3 -m pytest .claude/collab-mcp/test_collab.py — all pass, including the
new cross-client E2E. Record exact results.

HANDOFF
Use the repository HANDOFF format, release all claims, and stop. Flag in
Risks: real two-client verification (live Claude + live Codex exchanging one
message and rejecting one conflicting claim) still needs a coordinator-run
check before the Phase 0 gate.

STOP CONDITIONS
Stop and post a question if client-neutral identity requires a breaking DB or
wire-format change, if Codex hook capabilities can't express the claim check,
or if the work would expand beyond the claimed files.
```

---

## Codex (`codex-56-contracts`) — C0.2

```text
ROLE
You are codex-56-contracts, working in the shared BetterFingers checkout.

TASK
C0.2: Create docs/BUILD_WEEK_LOG.md — the evidence log separating pre-existing
work from Build Week work.

READ FIRST
accomplish.md §1 (outcome + judging story), §2 (verified starting point,
baseline `main` at ecbb3ce), §9 row C0.2; the "Required OpenAI wording:
Codex and GPT-5.6" line at the top of accomplish.md.

CLAIM
docs/BUILD_WEEK_LOG.md only.

DO NOT TOUCH
Everything else. No source, no other docs, no accomplish.md edits.

CONTRACT
The log must contain: baseline commit (ecbb3ce) and date; a clear pre-existing
vs Build-Week scope table; environment summary (OS, Python, Node versions);
active session IDs/names (sonnet-backend, sonnet-renderer, sonnet-platform,
codex-56-contracts, coordinator); the exact required wording "Codex and
GPT-5.6" when referring to the models; and an evidence template section
(task ID, commit, tests, screenshots/video link) ready for every future
accepted task.

STEPS
1. Draft the log structure with the sections above.
2. Fill baseline, scope split, and environment from accomplish.md §2.
3. Add the reusable evidence template with one worked example row.

VERIFY
All markdown links resolve; baseline commit and official wording are exactly
correct; file renders cleanly.

HANDOFF
Use the repository HANDOFF format, release the claim, and stop.

STOP CONDITIONS
Stop and post a question if information required by the contract is missing
from accomplish.md or ambiguous (e.g., environment details you cannot verify).
```

---

## Coordinator checklist (you)

After all four handoffs arrive: review diffs, fix defects, run the checks,
commit exact paths, post `ACCEPTED <task-id> <commit>` for each. Then run the
two coordinator tasks of Wave 0B (C0.6 branch + roster freeze, C0.7 evidence
capture), dispatch C0.5 (full suite, sonnet-platform, claims
__full-test-suite__), and check every Phase 0 gate box before opening Phase 1.
