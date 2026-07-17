# BetterFingers Remediation — Change Log

This log is the coordination point for the phased remediation. Each work
iteration reads it, does one bounded/committable chunk, and appends here.
**Never mix unrelated behavior changes in one commit.** Work happens on branch
`remediation/phased-loop`.

---

## Baseline (Phase 0 — recorded 2026-07-16)

Reference baseline claimed by the plan; treated as the "must stay green" bar.
Full suites are **not** re-run inside a 3-minute loop iteration — targeted
checks (`py_compile`, focused `pytest`) are used per chunk instead.

| Signal | Baseline |
| --- | --- |
| Python tests | 1,229 passing |
| Electron unit tests | 40 passing |
| Production build | passing |
| CodeQL | passing |
| E2E CI | passing |

Repo state at Phase 0: branch `main`, clean tree, up to date with `origin/main`.
A `feat/windows-vulkan-fallback` branch already exists (Phase 4-related, not
touched by this loop yet).

### Release levels

| Level | Requirements |
| --- | --- |
| Development | Existing tests remain green |
| Friends alpha | Phases 1–4 complete |
| Public alpha | Phases 1–7 complete, signed installers |
| 1.0 | Reliability benchmark, injection matrix, DataRegistry, modular architecture complete |

---

## Phase / task tracker

Legend: ✅ done · 🚧 in progress · ⬜ not started

- **Phase 0 — Baseline** 🚧
  - ✅ 0.a Create tracking changelog (this file)
  - ⬜ 0.b Regression-test placeholders for every confirmed issue
- **Phase 1 — Truthful privacy wipe** 🚧 (release blocking)
  - ✅ 1.1 Correct the HTTP contract (`/privacy/wipe` no longer 200 on failure)
  - ⬜ 1.2 Make the renderer defensive (`if (!result?.ok) throw`; show what/why/retry)
  - 🚧 1.3 End-to-end contract tests (route-level status test added; more cases pending)
- **Phase 2 — Unified data-lifecycle (DataRegistry)** ⬜ (release blocking)
- **Phase 3 — Support-report privacy** ⬜ (release blocking)
- **Phase 4 — Runtime & process boundaries** ⬜ (release blocking)
- **Phase 5 — API/renderer security boundary** ⬜
- **Phase 6 — Backend modularization** ⬜
- **Phase 7 — Renderer modularization** ⬜
- **Phase 8 — Quality/dependency/release gates** ⬜
- **Phase 9 — KISS boundary** ⬜

---

## Iteration log

### Iteration 1 — 2026-07-16 — Phase 0 + Phase 1.1

**Context found.** The backend already computes a *truthful* wipe result:
`server._perform_privacy_wipe()` quiesces the pipeline, drains output, deletes,
verifies postconditions, and returns `{ok, error, message, cleared,
postconditions}`. Function-level truthfulness is well covered by
`tests/test_privacy_wipe_verified.py`. **The only defect at the HTTP layer was
that the route returned every result as HTTP 200**, so a failed wipe looked
successful to any HTTP client.

**Changed.**
- `server.py`: `/privacy/wipe` route now maps the result to an honest status
  via new `_wipe_status_code()` helper, returning a `JSONResponse`:
  - `200` — every postcondition passed (`ok is True`)
  - `409` — `wipe_already_running` or `pipeline_did_not_quiesce`
  - `503` — `output_did_not_quiesce` (a subsystem could not drain)
  - `500` — `ok is False` with no pre-deletion abort code (deletion ran but a
    postcondition/verification failed)
  The structured payload is preserved byte-for-byte; `_perform_privacy_wipe`
  return type is unchanged so all existing function-level tests still pass.
- `tests/test_privacy_wipe_contract.py`: new route-level contract test
  asserting the status/payload mapping for success, already-running (409),
  pipeline-stall (409), output-stall (503), and postcondition-failure (500).

**Why.** Phase 1.1 definition of done: "an unsuccessful operation does not
return HTTP 200 as though it succeeded." Backend already knew the truth; the
route was laundering it into a 200.

**Verification.** `python -m py_compile server.py` + focused
`pytest tests/test_privacy_wipe_contract.py tests/test_privacy_wipe_verified.py`.

**Next up →** Phase 1.2: make the renderer defensive. Find the privacy-wipe
handler in `app/src/renderer/main.js`, ensure it throws unless
`result?.ok === true`, and surface what was deleted / what was not / which
postcondition failed / whether retry is safe. Never display "Your data was
wiped" unless `ok === true`.
