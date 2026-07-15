# QA Visual Walkbook

A reusable harness that drives the REAL Electron app against a deterministic
stub backend, asserts each state's behavior, screenshots it, and writes a
human-reviewable walkbook (`app/tests/qa/out/qa-report.md`) showing how
everything is supposed to work and look. It is a test suite that happens to
produce a picture book, not a camera — every scenario has real Playwright
assertions and the run exits non-zero if any of them fail.

## Running it

```
cd app
npm run build       # only if the renderer/main process changed underneath you
npm run qa:screens              # all scenarios
npm run qa:screens -- baseline  # only scenarios in one area
```

**RAM/e2e discipline (hard rule, this repo's collab protocol):** claim the
pseudo-path `__electron-e2e__` before any build or `qa:screens` run and
release it right after — never run this concurrently with another session's
Playwright/Electron work. See the `collab` skill.

The report lands at `app/tests/qa/out/qa-report.md`, with screenshots under
`app/tests/qa/out/<area>/<name>.png`. Both are committed to the repo — this
is the "curated, deliberately checked-in" path the top-level `.gitignore`
comment about `app/artifacts/` refers to, not a throwaway output directory.

## How the harness works (`app/tests/qa/harness.mjs`)

- **The seam**: `app/src/main/sidecar.js` checks whether something is already
  listening on `BETTERFINGERS_HOST:BETTERFINGERS_PORT` before spawning its own
  Python backend. If `GET /health` there returns 200 with a truthy `status`
  field, the app marks the backend `"external"` and never spawns a real
  `python3` process. `startStubBackend()` starts a plain Node `http` server
  first; `launchApp()` points Electron at it via those two env vars. No
  renderer patching, no app source changes.
- **Auth**: `app/src/main/main.js` always self-generates a random bearer token
  for the backend proxy, whether the backend is spawned or external. The stub
  never validates the `Authorization` header — that's covered by the
  Python-side security tests, not this harness.
- **One Electron launch per run, not per scenario.** Quitting Electron
  (`ElectronApplication.close()`, and even `app.quit()` called from inside the
  Electron process) was found to be able to terminate the whole Node runner
  process in this Electron/Playwright version combo. `run.mjs` launches once,
  then calls `resetBackendState(page, stub, newState)` between scenarios
  (mutates the stub's in-memory state, reloads the page, waits for
  `#backendStatus` to settle again) instead of relaunching. Electron is only
  quit once, at the very end, right before the process exits anyway — so it
  doesn't matter if that kills the process, because we wanted it dead at that
  point regardless. The report is written and the exit code computed *before*
  that final close call, not in a `finally` after it.
- **Unknown routes are loud.** A request that matches no `backendState` entry
  gets a 404 and a `console.warn` — a missing stub must never silently look
  like an empty success.

## Determinism rules

- Fixed 1280×800 viewport, `--force-device-scale-factor=1`, `TZ=UTC`.
- No real backend, no real models, no network calls beyond the stub.
- No timing `sleep()`s in scenario code — use Playwright's auto-retrying
  `expect(...)` / `waitForSelector` instead.
- `snap()` disables CSS animations/transitions and emulates
  `prefers-reduced-motion` before every screenshot.
- `snap()` masks `DEFAULT_MASK_SELECTORS` (defined once in `harness.mjs`,
  currently `#sidecarLogsTail` and any `[data-qa-mask]` element) on every
  screenshot. Add `data-qa-mask` to an element in your own session's
  renderer code if it renders something inherently non-deterministic
  (live timestamps, random ids) — don't invent a second masking mechanism.
- If a scenario needs extra masks (e.g. a wake-score number that jitters),
  pass them via the screenshot's `opts.mask` array — they're added to the
  defaults, never replace them.

## Scenario schema (`app/tests/qa/scenarios/*.mjs`)

```js
{
  area: 'voice-control',        // groups scenarios in the report + output dir
  name: 'listening-active',     // unique within area; also the screenshot filename
  kind: 'standard',             // or 'negative-control' -- see below
  description: 'One paragraph, present tense: what should be visible and true ' +
                'in this state. This text becomes the walkbook caption.',
  backendState: () => ({ ...coldBoot(), 'GET /wake/status': { ... } }),
  async navigate(page) { await page.click('#tabButtonSettings'); ... },
  async expects(page) { await expect(page.locator('...')).toBeVisible(); },
  screenshots: [{ name: 'listening-active', opts: { mask: ['#wakeScoreFill'] } }],
}
```

`backendState` is a plain object keyed by `"METHOD /path"` (or
`"METHOD /path/:param"` for one dynamic segment — this API never nests
dynamic segments deeper than that). A value is a plain object/array (served
as 200 JSON), `{status, body}`, or a function `(req, {params, query, body})`
for stateful routes (e.g. download progress that changes across polls).
Start from `scenarios/fixtures/cold-boot.mjs`'s `coldBoot()` and override only
what your scenario needs to change — don't restate the whole bootstrap
surface per scenario.

### Negative controls

Some scenarios exist specifically to prove the harness catches a lying
backend — e.g. a stub that reports `listening: true` while `enabled: false`
must FAIL a truthfulness assertion, not pass one. Mark these
`kind: 'negative-control'`. The runner inverts pass/fail for them: the
scenario's own suite stays green only if `expects()` actually THROWS against
the lying stub. If `expects()` unexpectedly passes, that's the real failure —
it means the harness failed to catch the lie. The report renders these
distinctly (tagged `` `negative-control` ``) with the outcome spelled out.

## Adding a scenario

1. Add or extend a file under `app/tests/qa/scenarios/`, exporting an array of
   scenarios matching the schema above.
2. Import it into `app/tests/qa/scenarios/index.mjs`'s `scenarios` array.
3. Run `npm run qa:screens -- <your-area>` and check the screenshot + report
   look right before committing.

**Standing policy: every new user-facing state ships with a scenario.** If
you land a feature with a UI state a user can actually reach (a new settings
panel, a new status banner, a new error state), it needs a QA scenario in the
same change, not as follow-up work. This is a definition-of-done item, not a
nice-to-have.

## Coordinating stub shapes with the owning session

Route response shapes in `scenarios/fixtures/*.mjs` are copied from the real
FastAPI handlers, not guessed — but they drift as those handlers change. If
you're adding scenarios for a surface you don't own (e.g. `/wake/*`,
`/models/resources`, `/doctor`), treat the owning session's published
contract (if they've posted one) as the source of truth, and post a
`collab_post` question listing your planned stub payloads so they can correct
drift against their actual implementation before you commit.
