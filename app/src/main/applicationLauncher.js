// Platform launch adapters for restricted workflows (Wave 9, D-0011) —
// main process.
//
// THE ONE RULE. Every launch is `(command, argv[])`. Never a string, never a
// shell, never a template with a user value interpolated into it. `spawn` is
// always called with `shell: false`, and `applicationLauncher.test.mjs` asserts
// that for every method and for an entry whose fields are packed with shell
// metacharacters — because that is the assertion that still fails if somebody
// later "simplifies" this to a single command string. Argument arrays are not a
// style preference here; they are the reason a confirmed executable path
// containing `; rm -rf ~` is a path that does not exist rather than two
// commands.
//
// LINUX PRIORITY, in the order `resolveLaunchPlan` applies when an entry does
// not pin a method:
//
//   1. .desktop entry      — what the desktop itself would run, including the
//                            vendor's own environment setup.
//   2. flatpak id          — the sandboxed install, addressed by app id.
//   3. registered URI      — the app's own scheme, handed to xdg-open.
//   4. confirmed executable — the path the user confirmed, run directly.
//   5. steam / launcher URI — the store's deep link, also via xdg-open.
//
// The order is "most likely to start the application the way the user normally
// starts it" first: a bare executable for a flatpak or Steam title usually
// exists and usually launches something subtly different (no sandbox, no
// runtime, no store overlay), which looks like it worked and is not what the
// user approved.
//
// WINDOWS IS DESIGNED, NOT QUALIFIED. `resolveWindowsLaunchPlan` is real,
// mockable code with the same argv-array contract, and it is marked
// `qualified: false` with a reason. There is no Windows host on this project,
// so nobody has watched it launch anything. Shipping it as "supported" on the
// strength of it looking right is the kind of claim this release exists to stop
// making; the honest status travels with the plan object so the caller and the
// UI cannot lose it.

const nodeChildProcess = require('node:child_process');
const { LAUNCH_METHODS } = require('./applicationRegistry');

// Mirrors backend/services/action_validator.py STEP_STATUS_CODES. Status codes
// only — a launcher error string routinely quotes a path, and a path is
// personal, so it never reaches the run history.
const STATUS_OK = 'ok';
const STATUS_FAILED = 'failed';
const STATUS_NOT_FOUND = 'not_found';
const STATUS_TIMEOUT = 'timeout';
const STATUS_SKIPPED = 'skipped';
const STATUS_REFUSED = 'refused';
const STATUS_UNAVAILABLE = 'unavailable';

const STEP_STATUS_CODES = [
  STATUS_OK, STATUS_FAILED, STATUS_NOT_FOUND, STATUS_TIMEOUT,
  STATUS_SKIPPED, STATUS_REFUSED, STATUS_UNAVAILABLE,
];

// The tools each method reaches for. Named constants so a test can assert the
// exact argv without repeating a literal that could drift.
const DESKTOP_LAUNCH_COMMAND = 'gtk-launch';
const FLATPAK_COMMAND = 'flatpak';
const OPEN_COMMAND = 'xdg-open';
const FOCUS_COMMAND = 'xdotool';
const WINDOWS_OPEN_COMMAND = 'explorer.exe';

const WINDOWS_UNQUALIFIED_REASON =
  'The Windows launcher has not been run on a Windows machine by this project, '
  + 'so it is written and testable but not qualified. Treat it as unverified.';

function nonEmpty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Which method an entry should use.
 *
 * An explicit, usable `launch_method` always wins — the user chose it in the
 * confirm form and a priority table quietly overriding that would make the
 * preview wrong. The priority order only decides for entries that did not pin
 * one.
 */
function chooseMethod(entry) {
  const declared = String((entry && entry.launch_method) || '').trim();
  const has = {
    desktop_entry: nonEmpty(entry && entry.desktop_entry),
    flatpak: nonEmpty(entry && entry.flatpak_id),
    uri: nonEmpty(entry && entry.uri),
    executable: nonEmpty(entry && entry.executable),
    steam: nonEmpty(entry && entry.steam_uri),
  };
  if (LAUNCH_METHODS.includes(declared) && has[declared]) return declared;
  for (const method of LAUNCH_METHODS) {
    if (has[method]) return method;
  }
  return '';
}

/**
 * Linux launch plan: `{ ok, method, command, args, qualified, reason }`.
 *
 * `args` is always an array, including when it is empty. Callers must not
 * "helpfully" join it.
 */
function resolveLaunchPlan(entry) {
  if (!entry || typeof entry !== 'object') {
    return { ok: false, reason: 'There is no application to launch.', method: '', command: '', args: [] };
  }
  if (!entry.confirmed) {
    return {
      ok: false,
      method: '',
      command: '',
      args: [],
      reason: 'That application has not been confirmed, so BetterFingers will not start it.',
    };
  }
  const method = chooseMethod(entry);
  switch (method) {
    case 'desktop_entry':
      return {
        ok: true,
        method,
        // gtk-launch takes the desktop-entry NAME; the trailing .desktop is
        // optional and is trimmed so both spellings behave identically.
        command: DESKTOP_LAUNCH_COMMAND,
        args: [String(entry.desktop_entry).replace(/\.desktop$/, '')],
        qualified: true,
        reason: '',
      };
    case 'flatpak':
      return {
        ok: true, method, command: FLATPAK_COMMAND,
        args: ['run', String(entry.flatpak_id)], qualified: true, reason: '',
      };
    case 'uri':
      return {
        ok: true, method, command: OPEN_COMMAND,
        args: [String(entry.uri)], qualified: true, reason: '',
      };
    case 'executable':
      return {
        ok: true, method, command: String(entry.executable),
        args: [], qualified: true, reason: '',
      };
    case 'steam':
      return {
        ok: true, method, command: OPEN_COMMAND,
        args: [String(entry.steam_uri)], qualified: true, reason: '',
      };
    default:
      return {
        ok: false, method: '', command: '', args: [],
        reason: 'That application has no launch method recorded.',
      };
  }
}

/**
 * Windows launch plan — same contract, honestly unqualified.
 *
 * Deliberately narrow: an executable is run directly, a URI (including a Steam
 * deep link) is handed to explorer.exe, which is the documented way to open a
 * registered protocol without a shell. `.desktop` and flatpak have no meaning
 * here and are reported as such rather than silently falling through to
 * something that happens to run.
 */
function resolveWindowsLaunchPlan(entry) {
  const base = { qualified: false, unqualified_reason: WINDOWS_UNQUALIFIED_REASON };
  if (!entry || typeof entry !== 'object' || !entry.confirmed) {
    return { ...base, ok: false, method: '', command: '', args: [],
      reason: 'That application has not been confirmed, so BetterFingers will not start it.' };
  }
  if (nonEmpty(entry.executable)) {
    return { ...base, ok: true, method: 'executable', command: String(entry.executable), args: [], reason: '' };
  }
  if (nonEmpty(entry.uri)) {
    return { ...base, ok: true, method: 'uri', command: WINDOWS_OPEN_COMMAND, args: [String(entry.uri)], reason: '' };
  }
  if (nonEmpty(entry.steam_uri)) {
    return { ...base, ok: true, method: 'steam', command: WINDOWS_OPEN_COMMAND, args: [String(entry.steam_uri)], reason: '' };
  }
  return {
    ...base, ok: false, method: '', command: '', args: [],
    reason: 'On Windows this application needs a program path or a link; a .desktop entry '
      + 'or flatpak id cannot be used here.',
  };
}

/**
 * @param {object} deps
 * @param {function} [deps.spawn]     node:child_process spawn
 * @param {string}   [deps.platform]  process.platform
 */
function createApplicationLauncher({
  spawn = nodeChildProcess.spawn,
  platform = process.platform,
} = {}) {
  const isWindows = platform === 'win32';

  function planFor(entry) {
    return isWindows ? resolveWindowsLaunchPlan(entry) : resolveLaunchPlan(entry);
  }

  /**
   * Spawn one plan. Returns a status CODE, never an error message.
   *
   * Detached with stdio ignored so a launched application does not die with
   * BetterFingers and does not hold a pipe nobody reads. `shell: false` is
   * passed explicitly rather than relied on as the default: the default is what
   * a future edit changes without noticing, and an explicit `false` is what a
   * test can assert.
   */
  function runPlan(plan) {
    if (!plan || !plan.ok) return { status: STATUS_REFUSED, plan: plan || null };
    try {
      const child = spawn(plan.command, plan.args, {
        shell: false,
        detached: true,
        stdio: 'ignore',
      });
      if (child && typeof child.unref === 'function') child.unref();
      if (child && typeof child.on === 'function') {
        // A spawn error arrives asynchronously; swallowing it here is the point
        // — an unhandled 'error' event on a detached child would take the main
        // process down, and the user's workflow already reported its status.
        child.on('error', () => {});
      }
      return { status: STATUS_OK, plan };
    } catch (error) {
      const code = error && error.code === 'ENOENT' ? STATUS_NOT_FOUND : STATUS_FAILED;
      return { status: code, plan };
    }
  }

  function launch(entry) {
    return runPlan(planFor(entry));
  }

  /** Open a URI or a folder path through the platform opener. */
  function open(target) {
    if (!nonEmpty(target)) return { status: STATUS_REFUSED, plan: null };
    const command = isWindows ? WINDOWS_OPEN_COMMAND : OPEN_COMMAND;
    return runPlan({
      ok: true, method: 'uri', command, args: [String(target)],
      qualified: !isWindows,
    });
  }

  /**
   * Raise an application's window.
   *
   * X11 only, and it says so: there is no portable focused-window control on
   * Wayland, and this project's standing rule is that an unavailable capability
   * reports `unavailable` rather than pretending to work. Same honesty the
   * Wave 7 detection note applies to reading the focused window.
   */
  function focus(entry, { sessionType = process.env.XDG_SESSION_TYPE } = {}) {
    if (isWindows) {
      return { status: STATUS_UNAVAILABLE, plan: null, qualified: false,
        unqualified_reason: WINDOWS_UNQUALIFIED_REASON };
    }
    if (String(sessionType || '').toLowerCase() === 'wayland') {
      return { status: STATUS_UNAVAILABLE, plan: null };
    }
    const key = String((entry && (entry.executable || entry.id)) || '').trim();
    if (!key) return { status: STATUS_REFUSED, plan: null };
    const base = key.split(/[\\/]/).pop();
    return runPlan({
      ok: true,
      method: 'focus',
      command: FOCUS_COMMAND,
      args: ['search', '--class', base, 'windowactivate', '%1'],
      qualified: true,
    });
  }

  return {
    launch,
    open,
    focus,
    planFor,
    isWindows,
    windowsQualified: false,
    windowsUnqualifiedReason: WINDOWS_UNQUALIFIED_REASON,
  };
}

module.exports = {
  createApplicationLauncher,
  resolveLaunchPlan,
  resolveWindowsLaunchPlan,
  chooseMethod,
  STEP_STATUS_CODES,
  STATUS_OK,
  STATUS_FAILED,
  STATUS_NOT_FOUND,
  STATUS_TIMEOUT,
  STATUS_SKIPPED,
  STATUS_REFUSED,
  STATUS_UNAVAILABLE,
  DESKTOP_LAUNCH_COMMAND,
  FLATPAK_COMMAND,
  OPEN_COMMAND,
  FOCUS_COMMAND,
  WINDOWS_OPEN_COMMAND,
  WINDOWS_UNQUALIFIED_REASON,
};
