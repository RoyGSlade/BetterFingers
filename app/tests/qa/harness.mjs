// Visual QA harness core (Tier-3 M3 qa-harness plan, D1).
//
// Drives the REAL Electron app against a stub HTTP(+WS) backend put into a
// deterministic state, so every scenario renders the same pixels and hits
// the same code paths every run -- no real Python backend, no real models,
// no network, no timing sleeps.
//
// THE SEAM (confirmed by reading app/src/main/sidecar.js): on launch the app
// checks if something is already listening on BETTERFINGERS_HOST:PORT: if a
// GET /health there returns 200 with a truthy `status` field, the app marks
// the backend "external" and NEVER spawns its own python3 process. Start the
// stub first, then point Electron at it -- no renderer patching, no app code
// changes.
//
// Auth: app/src/main/main.js always self-generates a random bearer token for
// backendProxy, whether the backend is spawned or external. The stub never
// validates the Authorization header (that's covered by the Python-side
// security tests, not this harness).

import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import { _electron as electron } from 'playwright';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const QA_ROOT = __dirname;
export const OUT_DIR = join(__dirname, 'out');
export const APP_DIR = join(__dirname, '..', '..'); // app/

// Elements masked in every screenshot by default (blacked out before the
// snapshot is taken) because their content is inherently non-deterministic
// across runs -- live log tails with real timestamps, and anything a
// scenario author opts in via `data-qa-mask`. Scenario-specific masks are
// concatenated onto this list, never replace it.
export const DEFAULT_MASK_SELECTORS = ['#sidecarLogsTail', '[data-qa-mask]'];

const FIXED_VIEWPORT = { width: 1280, height: 800 };

// --- UI target ---------------------------------------------------------------
//
// The app ships three dashboards, and they share ZERO element ids with each
// other, so window discovery and the readiness sentinel cannot be hard-coded
// to any one of them:
//
//   - `index`: the default, shipping `index.html` dashboard.
//   - `signal-desk`: the Signal Desk DESIGN/mockup preview page
//     (signal-desk-preview.html, behind BF_UI=signal-desk). Pinned here by
//     binding decision D-0007 -- existing scenarios (signal-desk-shell/
//     -sections/-talk) depend on this exact target continuing to point at
//     the preview page, so it must never be repointed at the production
//     composition root below.
//   - `signal-desk-prod`: the production Signal Desk composition root
//     (signal-desk.html, behind BF_UI=signal-desk-prod) that actually ships
//     to users once mounted. Scenarios that only make sense against real
//     production wiring (e.g. persona-learning's Studio "Teach from my
//     edits" panel, which lives only in signal-desk.html's Studio workspace,
//     never in the preview page) target this instead of `signal-desk` --
//     that keeps them from clobbering the preview target's committed
//     screenshots or asserting against markup the preview page never had.
//
// This is a RUN-level choice, not a per-scenario one, and deliberately so:
// launchApp's own close() comment documents that quitting Electron kills the
// parent runner process in this Electron/Playwright combo, which is why the
// whole suite reuses a single launch. Switching target mid-run would require
// relaunching with different env, so `BF_QA_UI` picks one target per run:
//
//   node tests/qa/run.mjs <area>                            # default UI
//   BF_QA_UI=signal-desk node tests/qa/run.mjs <area>       # Signal Desk preview
//   BF_QA_UI=signal-desk-prod node tests/qa/run.mjs <area>  # Signal Desk production root
export const UI_TARGETS = {
  index: {
    name: 'index',
    page: 'index.html',
    env: {},
    // Present as soon as the shell renders; also the thing that reports
    // backend health, so it doubles as the readiness signal.
    attachedSelector: '#backendStatus',
    readyTextSelector: '#backendStatus',
    readyTextPattern: /ready|active|running|external/i,
    outSubdir: '',
  },
  'signal-desk': {
    name: 'signal-desk',
    page: 'signal-desk-preview.html',
    env: { BF_UI: 'signal-desk' },
    attachedSelector: '.sd-shell',
    // Now a real signal: the status bar's STT cell is bound to backend state
    // and starts at "—", so waiting for it to say Loaded/Not loaded proves the
    // page actually reached the backend. (This was deliberately null while the
    // rail was hard-coded markup — waiting on a constant would have asserted a
    // truth the page was not telling.) "Not loaded" counts as ready: it is a
    // truthful answer from a reachable backend, which is what readiness means
    // here; only "—" means we have not heard back yet.
    readyTextSelector: '#sdStatusSttValue',
    readyTextPattern: /loaded/i,
    // Namespaced so a Signal Desk run cannot clobber the default UI's
    // committed screenshots.
    outSubdir: 'signal-desk',
  },
  'signal-desk-prod': {
    name: 'signal-desk-prod',
    page: 'signal-desk.html',
    env: { BF_UI: 'signal-desk-prod' },
    // Same shell + status-bar contract as 'signal-desk' above (both are the
    // Signal Desk redesign, just different pages) -- see that target's
    // comments for why each selector/pattern is what it is.
    attachedSelector: '.sd-shell',
    readyTextSelector: '#sdStatusSttValue',
    readyTextPattern: /loaded/i,
    // Own subdir, distinct from BOTH 'index' and 'signal-desk': a
    // signal-desk-prod run must not clobber the preview target's committed
    // screenshots (D-0007) or the default UI's.
    outSubdir: 'signal-desk-prod',
  },
};

const REQUESTED_UI = process.env.BF_QA_UI || 'index';
if (!Object.hasOwn(UI_TARGETS, REQUESTED_UI)) {
  throw new Error(
    `Unknown BF_QA_UI="${REQUESTED_UI}". Known targets: ${Object.keys(UI_TARGETS).join(', ')}`,
  );
}

/** The UI target this run is exercising. */
export const TARGET = UI_TARGETS[REQUESTED_UI];

// --- Stub backend ------------------------------------------------------------
//
// `state` is a plain object keyed by "METHOD /path" (fixed paths) or
// "METHOD /path/:param" (one dynamic segment, matched positionally -- this
// API doesn't nest dynamic segments deeper than one level anywhere the
// renderer calls). Each value is either:
//   - a plain object / array -> served as 200 application/json
//   - { status, body }       -> served with that status code
//   - a function(req, {params, query, body}) -> object | {status, body},
//     called per-request for stateful routes (e.g. download progress that
//     changes across polls within one scenario).
// A request matching no entry gets a 404 AND a console.warn -- missing stubs
// must be loud, never silently pass through as an empty 200.
function matchRoute(state, method, pathname) {
  const exactKey = `${method} ${pathname}`;
  if (exactKey in state) return { key: exactKey, params: {} };

  const segments = pathname.split('/').filter(Boolean);
  for (const key of Object.keys(state)) {
    const [keyMethod, keyPath] = key.split(/ (.+)/).slice(0, 2);
    if (keyMethod !== method) continue;
    const keySegments = keyPath.split('/').filter(Boolean);
    if (keySegments.length !== segments.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < keySegments.length; i++) {
      if (keySegments[i].startsWith(':')) {
        params[keySegments[i].slice(1)] = segments[i];
      } else if (keySegments[i] !== segments[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { key, params };
  }
  return null;
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw) {
        resolve(undefined);
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (_e) {
        resolve(raw); // non-JSON body (e.g. multipart) -- scenarios needing
        // multipart introspection aren't in scope for the pilot; stub as a
        // plain 200 keyed by the route and ignore the body.
      }
    });
  });
}

// Minimal RFC6455 handshake so the renderer's voice-status WS doesn't spam
// reconnect-loop console noise into every screenshot. Confirmed non-blocking
// (backendProxy.js's _connectWs never throws into bootstrap on failure) --
// this is pure noise control, not a boot requirement.
const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
function acceptWebSocketUpgrade(req, socket) {
  const key = req.headers['sec-websocket-key'];
  if (!key) {
    socket.destroy();
    return;
  }
  const accept = createHash('sha1').update(key + WS_GUID).digest('base64');
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
      'Upgrade: websocket\r\n' +
      'Connection: Upgrade\r\n' +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  // No message handling needed -- the client only cares that the socket
  // stays open (or reconnects harmlessly if it doesn't). Idle is fine.
  socket.on('error', () => {});
}

/**
 * Start the stub backend. Returns { port, close(), setState(next) } -- the
 * mutable-state form lets a scenario mutate backendState mid-flight (e.g. a
 * download that transitions from "downloading" to "downloaded" across polls)
 * without restarting the server.
 */
export function startStubBackend(initialState = {}) {
  let state = initialState;
  const warnedUnknown = new Set();

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    const method = req.method.toUpperCase();
    const match = matchRoute(state, method, url.pathname);

    if (!match) {
      const label = `${method} ${url.pathname}`;
      if (!warnedUnknown.has(label)) {
        warnedUnknown.add(label);
        // eslint-disable-next-line no-console
        console.warn(`[qa-harness stub] no stub for ${label} -- returning 404 (add it to backendState)`);
      }
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ detail: `no stub for ${label}` }));
      return;
    }

    const body = await readBody(req);
    const query = Object.fromEntries(url.searchParams.entries());
    let entry = state[match.key];
    if (typeof entry === 'function') {
      entry = await entry(req, { params: match.params, query, body });
    }
    const { status, payload } =
      entry && typeof entry === 'object' && 'status' in entry && 'body' in entry
        ? { status: entry.status, payload: entry.body }
        : { status: 200, payload: entry };

    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(payload ?? null));
  });

  server.on('upgrade', (req, socket) => {
    if (url_pathnameOf(req.url) === '/ws/voice_status') {
      acceptWebSocketUpgrade(req, socket);
    } else {
      socket.destroy();
    }
  });

  function url_pathnameOf(reqUrl) {
    try {
      return new URL(reqUrl, 'http://127.0.0.1').pathname;
    } catch (_e) {
      return reqUrl;
    }
  }

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        port,
        close: () => new Promise((r) => server.close(() => r())),
        setState: (next) => {
          state = next;
        },
        getState: () => state,
      });
    });
  });
}

// --- App launch ---------------------------------------------------------------

/**
 * Launch the real Electron app pointed at the stub backend. Returns
 * { app, page, close() }. Handles the onboarding-dismiss + backend-ready
 * poll exactly like app/tests/electron-smoke.spec.js so scenarios start from
 * the same known-good state that suite already validates.
 */
export async function launchApp({ backendPort, target = TARGET }) {
  const launchEnv = { ...process.env, ...target.env };
  delete launchEnv.ELECTRON_RUN_AS_NODE;
  delete launchEnv.ELECTRON_NO_ATTACH_CONSOLE;
  launchEnv.BETTERFINGERS_HOST = '127.0.0.1';
  launchEnv.BETTERFINGERS_PORT = String(backendPort);
  // Determinism addendum (orchestrator Phase 0 ack): fixed locale/TZ so any
  // rendered dates/times are stable across machines and runs.
  launchEnv.TZ = 'UTC';
  launchEnv.LANG = 'en_US.UTF-8';

  // BF_QA_USER_DATA_DIR: run against a throwaway Electron profile instead of
  // the developer's real one. Two reasons, both real:
  //
  //  - main.js takes a single-instance lock keyed on the userData path, so a
  //    QA run and the actual app are mutually exclusive. Anyone with the app
  //    open has to close it to run the suite, which is exactly the friction
  //    that stops people running it.
  //  - the suite otherwise inherits whatever is in the developer's
  //    localStorage (pref_message_rescue_enabled, dismissal flags, ...), so
  //    "deterministic across runs" quietly means "deterministic on my machine".
  //
  // Opt-in rather than default: switching every existing scenario to a blank
  // profile changes their starting state, and that belongs in its own change
  // with its own baseline comparison, not smuggled in here.
  const args = ['.', '--force-device-scale-factor=1'];
  if (process.env.BF_QA_USER_DATA_DIR) {
    args.push(`--user-data-dir=${process.env.BF_QA_USER_DATA_DIR}`);
  }

  const app = await electron.launch({
    cwd: APP_DIR,
    args,
    env: launchEnv,
  });

  const isTargetPage = (w) => w.url().includes(target.page);
  const windows = app.windows();
  let page = windows.find(isTargetPage);
  if (!page) {
    page = await app.waitForEvent('window', { predicate: isTargetPage, timeout: 20000 });
  }

  await page.setViewportSize(FIXED_VIEWPORT);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector(target.attachedSelector, { state: 'attached', timeout: 15000 });

  // Skip the modal first-run onboarding overlay -- it blocks every other
  // interaction. Same trick electron-smoke.spec.js uses.
  //
  // Guarded on bf_qa_no_auto_dismiss (QA-only seam, D-durable-consent-qa):
  // Playwright has no removeInitScript, and an addInitScript callback re-runs
  // on EVERY reload/navigation of this page for the rest of its life -- so a
  // first-run scenario that clears bf_onboarding_complete via page.evaluate()
  // would see this same init script silently re-set it out from under it on
  // its very next reload. localStorage is the only channel that survives a
  // reload and is readable from an init script, so a second, distinct key
  // that this function never sets itself -- only enterFirstRunState /
  // enterCompletedProfileState opt into it -- is the only way to switch this
  // auto-dismiss off for the rest of the run. No existing scenario or target
  // ever sets bf_qa_no_auto_dismiss, so the condition below is always false
  // for them and this is byte-identical to the unconditional setItem it
  // replaces.
  //
  // SINGLE-SHOT, deliberately: the sentinel suppresses auto-dismiss for
  // exactly the ONE load that follows it being set, then removes itself. A
  // sticky sentinel would be a live grenade in this suite -- run.mjs reuses a
  // single Electron window for every scenario, so once a first-run scenario
  // turned auto-dismiss off for good, every LATER scenario (persona-learning,
  // the prod section/console sweep, anything added next) would reload into a
  // raised consent gate and fail for a reason that has nothing to do with what
  // it was testing. Single-shot means a first-run scenario gets its ungated
  // boot and the very next reload is back to normal, so scenario ORDER stops
  // mattering. This is why enterFirstRunState() below sets the sentinel
  // immediately before its own reload and never has to clean up after itself.
  await page.addInitScript(() => {
    try {
      if (localStorage.getItem('bf_qa_no_auto_dismiss') === 'true') {
        localStorage.removeItem('bf_qa_no_auto_dismiss');
      } else {
        localStorage.setItem('bf_onboarding_complete', 'true');
      }
    } catch (_e) {
      /* ignore */
    }
  });
  await page.reload();
  await page.setViewportSize(FIXED_VIEWPORT);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector(target.attachedSelector, { state: 'attached', timeout: 15000 });

  const onboardingDecline = page.locator('button:has-text("Decline & quit")');
  const onboardingGetStarted = page.locator('button:has-text("Get started")');
  if (await onboardingGetStarted.isVisible().catch(() => false)) {
    await onboardingGetStarted.click().catch(() => {});
  } else if (await onboardingDecline.isVisible().catch(() => false)) {
    // Shouldn't happen (we set bf_onboarding_complete first) but don't hang
    // a whole scenario run on a dialog if it does.
    await onboardingDecline.click().catch(() => {});
  }

  await page
    .locator(target.attachedSelector)
    .waitFor({ state: 'attached', timeout: 15000 });
  if (target.readyTextSelector) {
    await waitForText(page.locator(target.readyTextSelector), target.readyTextPattern, 15000);
  }

  return {
    app,
    page,
    target,
    // NOTE: Playwright's ElectronApplication.close() was observed to kill the
    // PARENT node process outright in this Electron/Playwright version combo
    // (confirmed via a minimal repro: awaiting app.close() never returns to
    // the caller -- the whole script exits mid-await instead). Quitting from
    // inside the Electron process itself via app.evaluate is reliable and
    // lets the caller's code after close() actually run.
    close: () => app.evaluate(({ app: electronApp }) => electronApp.quit()).catch(() => {}),
  };
}

/**
 * Point the SAME already-launched app at a new backend state without
 * relaunching Electron. Quitting Electron between scenarios was found to
 * terminate the whole runner process in this environment (see close()'s
 * comment) -- reusing one launch for the entire run and resetting state +
 * reloading is both the workaround and the better design (matches
 * electron-smoke.spec.js's single beforeAll launch for its whole suite).
 */
export async function resetBackendState(page, stub, newState, target = TARGET) {
  stub.setState(newState);
  await page.reload();
  await page.setViewportSize(FIXED_VIEWPORT);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector(target.attachedSelector, { state: 'attached', timeout: 15000 });
  if (target.readyTextSelector) {
    await waitForText(page.locator(target.readyTextSelector), target.readyTextPattern, 15000);
  }
}

export async function waitForText(locator, pattern, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastText = '';
  while (Date.now() < deadline) {
    lastText = (await locator.textContent().catch(() => '')) || '';
    if (pattern.test(lastText)) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`Timed out waiting for text matching ${pattern} (last saw: "${lastText}")`);
}

// --- Durable-consent QA seam (D-durable-consent-qa) ---------------------------
//
// Production Signal Desk gates onboarding on the durable record in
// app/src/main/onboardingStore.js (<root>/onboarding.json), reached from the
// renderer only through IPC (see signalDeskApp.js's resolveOnboardingGate call
// and ipc.js's onboarding:* handlers) -- there is no window.__onboarding debug
// handle on this page, and this file must not add one. These helpers drive the
// same durable state a real profile would have, by writing/deleting the actual
// file the main process reads, exactly like a real install would produce it.
//
// A helper here is only honest if it cannot silently degrade into operating on
// someone's REAL profile -- see qaDataRoot()'s null-refusal, used by both
// state-entering functions below.

/**
 * The expanded BETTERFINGERS_DATA_DIR override, or null when it is unset.
 *
 * Deliberately mirrors ONLY the override branch of resolveUserDataRoot()
 * (app/src/main/userDataRoot.js), not its full precedence chain (APPDATA,
 * legacy ~/BetterFingers, platform default) -- those branches exist so a real
 * install finds a sensible root with no configuration. A QA helper that fell
 * through to one of them on a developer's own machine would read/write that
 * developer's real onboarding.json, which is both destructive and would
 * fabricate a "first run" result that was never produced against an isolated
 * root. Returning null instead lets callers refuse outright.
 */
export function qaDataRoot() {
  const override = process.env.BETTERFINGERS_DATA_DIR;
  if (!override) return null;
  if (override === '~') return homedir();
  if (override.startsWith('~/') || override.startsWith('~\\')) {
    return join(homedir(), override.slice(2));
  }
  return override;
}

/**
 * The pure record enterCompletedProfileState({via: 'record'}) writes to
 * <root>/onboarding.json -- the exact shape onboardingStore.recordAcceptance()
 * produces (schema_version 1, consent_version 1, accepted true, an ISO
 * accepted_at, no completed_steps). Exported standalone, with no Electron/fs
 * dependency of its own, so its shape is unit-testable without Electron (see
 * tests/qaFirstRun.test.mjs) -- the assertion it makes honest is "this is what
 * a real accepted profile's file actually contains", not "this is whatever a
 * QA helper happened to write".
 */
export function seededAcceptedRecord({ now = () => new Date() } = {}) {
  return {
    schema_version: 1,
    consent_version: 1,
    accepted: true,
    accepted_at: now().toISOString(),
    completed_steps: [],
  };
}

/**
 * Puts the CURRENT page into a genuine first-run state: no durable
 * onboarding.json, no legacy bf_onboarding_complete flag, and the
 * bf_qa_no_auto_dismiss sentinel set so launchApp's init script (see above)
 * does not re-set that flag out from under this on the reload below. The
 * sentinel is single-shot -- it covers exactly that one reload and clears
 * itself -- so this leaves nothing behind for the next scenario to trip over,
 * and the run does not depend on where in the order these scenarios sit.
 *
 * Refuses outright when qaDataRoot() is null -- see its own comment. Running
 * a first-run scenario against the real default root would silently destroy
 * a real onboarding.json and hand back a fabricated "first run" result.
 *
 * Deliberately waits ONLY on target.attachedSelector, not readyTextSelector:
 * signalDeskApp.js resolves the onboarding gate over IPC asynchronously and
 * independently of the status bar's own refresh, so waiting on
 * readyTextSelector here would not hang -- but it also proves nothing about
 * first-run state, and this function's job ends at "the page reloaded into a
 * clean profile", not "the onboarding gate has finished resolving". Scenario
 * `expects()` blocks use Playwright's auto-retrying locator assertions
 * (expect(...).toBeVisible()) to observe the gate once it resolves, which is
 * the honest place for that wait to live.
 */
export async function enterFirstRunState(page, { target = TARGET } = {}) {
  const root = qaDataRoot();
  if (!root) {
    throw new Error(
      'enterFirstRunState refuses to run without BETTERFINGERS_DATA_DIR set: with no override, ' +
        "onboardingStore would resolve to this machine's REAL user-data root, and deleting " +
        'onboarding.json there would destroy a real consent record while reporting a fabricated ' +
        '"first run" result. Set BETTERFINGERS_DATA_DIR to a throwaway directory (and export it ' +
        'before launching the QA run, so the Electron subprocess inherits the same override) ' +
        'before running first-run scenarios.',
    );
  }

  await page.evaluate(() => {
    try {
      localStorage.setItem('bf_qa_no_auto_dismiss', 'true');
      localStorage.removeItem('bf_onboarding_complete');
    } catch (_e) {
      /* ignore */
    }
  });

  try {
    rmSync(join(root, 'onboarding.json'), { force: true });
  } catch (_e) {
    /* best-effort, same tolerance onboardingStore.clearForFactoryReset uses */
  }

  await page.reload();
  await page.setViewportSize(FIXED_VIEWPORT);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector(target.attachedSelector, { state: 'attached', timeout: 15000 });
}

/**
 * Puts the CURRENT page into a completed-onboarding state, proving one of the
 * two ways a real profile reaches it:
 *
 *   - via: 'record' (default) -- writes seededAcceptedRecord() to
 *     <root>/onboarding.json and clears the legacy flag, so the durable
 *     record is the ONLY reason the gate stays down.
 *   - via: 'legacy-flag' -- deletes onboarding.json and sets
 *     bf_onboarding_complete='true' in localStorage instead, proving the
 *     one-shot migrateLegacyCompletion() path rather than the durable record.
 *
 * Both set the single-shot bf_qa_no_auto_dismiss sentinel first (see
 * launchApp). Without it, launchApp's own init script would unconditionally
 * stomp bf_onboarding_complete='true' on the reload below regardless of which
 * path this call is trying to exercise --
 * which would make 'record' pass for the wrong reason (the legacy flag it
 * never touched) and make 'legacy-flag' impossible to exercise at all, since
 * the durable-record absence it relies on would be masked by a flag this
 * function never asked for.
 *
 * Refuses outright when qaDataRoot() is null, for the same reason
 * enterFirstRunState does.
 */
export async function enterCompletedProfileState(page, { via = 'record', target = TARGET } = {}) {
  const root = qaDataRoot();
  if (!root) {
    throw new Error(
      'enterCompletedProfileState refuses to run without BETTERFINGERS_DATA_DIR set -- see ' +
        'enterFirstRunState for why operating on the real default root is unacceptable here.',
    );
  }
  if (via !== 'record' && via !== 'legacy-flag') {
    throw new Error(`enterCompletedProfileState: unknown via="${via}" (expected 'record' or 'legacy-flag')`);
  }

  const recordPath = join(root, 'onboarding.json');

  if (via === 'record') {
    mkdirSync(root, { recursive: true });
    writeFileSync(recordPath, JSON.stringify(seededAcceptedRecord(), null, 2));
    await page.evaluate(() => {
      try {
        localStorage.setItem('bf_qa_no_auto_dismiss', 'true');
        localStorage.removeItem('bf_onboarding_complete');
      } catch (_e) {
        /* ignore */
      }
    });
  } else {
    try {
      rmSync(recordPath, { force: true });
    } catch (_e) {
      /* best-effort, same tolerance onboardingStore.clearForFactoryReset uses */
    }
    await page.evaluate(() => {
      try {
        localStorage.setItem('bf_qa_no_auto_dismiss', 'true');
        localStorage.setItem('bf_onboarding_complete', 'true');
      } catch (_e) {
        /* ignore */
      }
    });
  }

  await page.reload();
  await page.setViewportSize(FIXED_VIEWPORT);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector(target.attachedSelector, { state: 'attached', timeout: 15000 });
  // Unlike enterFirstRunState, waiting on readyTextSelector here is safe AND
  // meaningful: a completed profile never shows the modal, so nothing about
  // this wait can be blocked by a gate that is supposed to be down.
  if (target.readyTextSelector) {
    await waitForText(page.locator(target.readyTextSelector), target.readyTextPattern, 15000);
  }
}

// --- Screenshots ---------------------------------------------------------------

/**
 * Screenshot `page` to app/tests/qa/out/<area>/<name>.png. Disables
 * animations/transitions and reduced-motion-sensitive effects, masks
 * DEFAULT_MASK_SELECTORS plus any scenario-supplied selectors.
 */
export async function snap(page, area, name, { mask = [] } = {}) {
  await page.emulateMedia({ reducedMotion: 'reduce' }).catch(() => {});
  await page
    .addStyleTag({
      content: '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
    })
    .catch(() => {});

  const maskSelectors = [...DEFAULT_MASK_SELECTORS, ...mask];
  const maskLocators = maskSelectors.map((sel) => page.locator(sel));

  // Namespaced per target so a Signal Desk run cannot overwrite the default
  // UI's committed screenshots with pictures of a different app.
  const dir = join(OUT_DIR, TARGET.outSubdir, area);
  mkdirSync(dir, { recursive: true });
  const filePath = join(dir, `${name}.png`);
  await page.screenshot({ path: filePath, mask: maskLocators });
  return filePath;
}

export function ensureOutDir() {
  mkdirSync(OUT_DIR, { recursive: true });
}

export function writeReportFile(relativePath, content) {
  // Same namespacing as snap(): a Signal Desk run must not overwrite the
  // default UI's walkbook with a report about a different app.
  const filePath = join(OUT_DIR, TARGET.outSubdir, relativePath);
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, content);
  return filePath;
}
