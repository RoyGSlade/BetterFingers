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
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
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
// The app ships two dashboards: the default `index.html` and the Signal Desk
// workspace UI behind BF_UI=signal-desk (see main/windows.js loadDashboard).
// They share ZERO element ids, so window discovery and the readiness sentinel
// cannot be hard-coded to either one.
//
// This is a RUN-level choice, not a per-scenario one, and deliberately so:
// launchApp's own close() comment documents that quitting Electron kills the
// parent runner process in this Electron/Playwright combo, which is why the
// whole suite reuses a single launch. Switching target mid-run would require
// relaunching with different env, so `BF_QA_UI` picks one target per run:
//
//   node tests/qa/run.mjs <area>                       # default UI
//   BF_QA_UI=signal-desk node tests/qa/run.mjs <area>  # Signal Desk
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
  await page.addInitScript(() => {
    try {
      localStorage.setItem('bf_onboarding_complete', 'true');
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
