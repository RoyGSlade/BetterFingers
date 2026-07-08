# Review Findings — Fix Log

Tracking doc for the six review findings addressed on branch `master-plan`.
Each entry: the claim, verification against current code, and the fix.

Status legend: ✅ fixed · 🔎 verified real before fixing

---

## HIGH 1 — Review overlay backend calls were unauthenticated ✅

**Claim:** `review-overlay.html` hardcodes `BACKEND_ORIGIN` and sends no auth
headers, so Accept/Rewrite/Read/Cancel 401 under the Electron sidecar token
(server.py enforces `Authorization: Bearer …` on every non-WS route).

**Verified:** `fetchJson`/`postJson` in `review-overlay.html` sent no
`Authorization` header. The review window loads the same `preload.js` as the
dashboard, so `window.betterFingers.authToken` was already available there —
it just wasn't used.

**Fix:** Read `window.betterFingers.authToken` in the overlay and merge a
`Bearer` header into every request via an `authHeaders()` helper in `fetchJson`.
Files: `app/src/renderer/review-overlay.html`.

---

## HIGH 2 — Dashboard could not reopen from tray after being closed ✅

**Claim:** Tray menu/click and the `app:show` IPC only call `onShow` when
`getMainWindow()` already returns a window, so a closed dashboard (window ===
null) can never be recreated. Contradicts MANUAL_QA_CHECKLIST.md.

**Verified:** `onShow` in `main.js` is `() => focusMainWindow(ensureMainWindow())`
— it *does* recreate the window — but three call sites gated it behind
`if (window && onShow)`, and `getMainWindow()` returns `null` after the window
is closed. So the recreate path was unreachable from the tray.

**Fix:** Call `onShow()` unconditionally (when defined) in the tray "Open
Dashboard" menu item, the tray click handler, and the `app:show` IPC handler.
`ensureMainWindow()` inside `onShow` handles the null case.
Files: `app/src/main/tray.js`, `app/src/main/ipc.js`.

---

## MEDIUM 3 — Backend host/port config was not actually unified ✅

**Claim:** Main/sidecar honor `BETTERFINGERS_HOST`/`BETTERFINGERS_PORT` via
`config.js`, but the renderer API (`api/backend.js`) and the review overlay
still hardcode `127.0.0.1:8000`, so a non-default port renders the header but
leaves the backend offline.

**Verified:** `backend.js:1` and `review-overlay.html:302` hardcoded the origin;
the WS URL was hardcoded too. The renderer/overlay run sandboxed and can't read
the main-process env directly.

**Fix:** Expose the resolved origin through the preload bridge as
`window.betterFingers.backendOrigin` (new `app:get-backend-origin-sync` IPC that
returns `config.js`'s `BACKEND_ORIGIN`). Renderer and overlay now derive their
origin (and the renderer its `ws://` URL) from it, falling back to the hardcoded
default only if the bridge is absent.
Files: `app/src/main/config.js` (export already present), `app/src/main/main.js`,
`app/src/main/ipc.js`, `app/src/preload/preload.js`, `app/src/renderer/api/backend.js`,
`app/src/renderer/review-overlay.html`.

---

## MEDIUM 4 — Confidence was dropped from the live overlay payload ✅

**Claim:** Backend includes `confidence` in the `preview_ready` broadcast
(server.py:1135), but `updateVoiceStatus()` builds the draft without it, so the
initial overlay payload lacks confidence (dashboard only recovers after
`refreshDrafts()`).

**Verified:** The draft literal in `updateVoiceStatus()` copied token_count,
token_limit, long_text, etc. but not `confidence`.

**Fix:** Add `confidence: message.confidence` to the draft object.
Files: `app/src/renderer/main.js`.

---

## MEDIUM 5 — Linux audio ducking was disabled in the UI on all non-Windows ✅

**Claim:** Backend reports Linux+`pactl` supports ducking
(`supports_audio_ducking` in `/capabilities`), but the renderer forces the
warning/disabled state unless the platform is Windows.

**Verified:** `updatePlatformWarnings()` keyed the warning, the disabled
checkbox, and the badge purely off `isWindows`, ignoring
`capabilities.supports_audio_ducking` (which `/capabilities` returns directly).

**Fix:** Drive the warning text, the checkbox enabled/disabled state, and the
platform badge off `capabilities.supports_audio_ducking` instead of `isWindows`.
Files: `app/src/renderer/main.js`.

---

## LOW/MED 6 — Electron Playwright tests unreliable + stale doc count ✅

**Claim:** `electron-smoke.spec.js` spreads `process.env`, so an inherited
`ELECTRON_RUN_AS_NODE=1` breaks launch; tests also assume onboarding is already
complete, so a clean profile blocks tab clicks. Docs say 262 tests; the Python
suite is 307.

**Verified:** `beforeAll` passed `env: { ...process.env, … }` (would forward
`ELECTRON_RUN_AS_NODE`); no step dismissed the first-run onboarding overlay
(gated by `localStorage['bf_onboarding_complete'] === 'true'`). `pytest --co`
reports 307; MANUAL_QA_CHECKLIST.md lines 4 and 154 said 262.

**Fix:** Strip `ELECTRON_RUN_AS_NODE`/`ELECTRON_NO_ATTACH_CONSOLE` from the
launch env; after first load, set the onboarding flag via `addInitScript` and
reload so tab-click tests run against a dismissed overlay. Update the doc counts
to 307.
Files: `app/tests/electron-smoke.spec.js`, `docs/MANUAL_QA_CHECKLIST.md`.
