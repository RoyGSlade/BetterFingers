import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const { compareSemver, createUpdateController, safeError, safeNotes } =
  createRequire(import.meta.url)('../src/main/updateController.js');

function harness({ version = '1.1.0-alpha.3', busy = false } = {}) {
  const events = new Map();
  const calls = [];
  const updater = {
    on: (name, handler) => events.set(name, handler),
    checkForUpdates: async () => calls.push('check'),
    downloadUpdate: async () => calls.push('download'),
    quitAndInstall: () => calls.push('install'),
  };
  const activity = {
    busy,
    authoritative: { recording: busy, processing: false },
  };
  const controller = createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: version, updater,
    activityGuard: () => activity.busy,
    authoritativeActivityGuard: async () => activity.authoritative,
    prepareQuit: async () => calls.push('prepare'),
  });
  return { activity, calls, controller, events, updater };
}

test('development and non-Windows builds stay unsupported', async () => {
  const x = harness();
  for (const options of [
    { platform: 'win32', isPackaged: false },
    { platform: 'linux', isPackaged: true },
  ]) {
    const controller = createUpdateController({ ...options, updater: x.updater, currentVersion: '1.0.0' });
    assert.equal(controller.getState().status, 'unsupported');
    await controller.check();
  }
  assert.deepEqual(x.calls, []);
});

test('alpha and stable builds have fixed channels and safety flags', () => {
  const alpha = harness();
  assert.equal(alpha.updater.channel, 'alpha');
  assert.equal(alpha.updater.allowPrerelease, true);
  assert.equal(alpha.updater.autoDownload, false);
  assert.equal(alpha.updater.autoInstallOnAppQuit, false);
  assert.equal(alpha.updater.allowDowngrade, false);
  const stable = harness({ version: '1.1.0' });
  assert.equal(stable.updater.channel, 'latest');
  assert.equal(stable.updater.allowPrerelease, false);
});

test('semantic version comparison rejects equal, lower, and corrupt updates', () => {
  assert.equal(compareSemver('1.1.0-alpha.4', '1.1.0-alpha.3'), 1);
  assert.equal(compareSemver('1.1.0-alpha.2', '1.1.0-alpha.3'), -1);
  assert.equal(compareSemver('1.1.0', '1.1.0-alpha.99'), 1);
  assert.equal(compareSemver('garbage', '1.1.0'), null);
  const x = harness();
  x.events.get('update-available')({ version: '1.1.0-alpha.3' });
  assert.equal(x.controller.getState().status, 'up_to_date');
  x.events.get('update-available')({ version: '1.1.0-alpha.2' });
  assert.equal(x.controller.getState().status, 'up_to_date');
  x.events.get('update-available')({ version: 'not-semver' });
  assert.equal(x.controller.getState().errorCode, 'INVALID_METADATA');
});

test('release notes become bounded plain text and errors never expose raw details', () => {
  assert.equal(
    safeNotes('<script>steal()</script><p>Hello &amp; welcome</p><style>.x{}</style><b>friend</b>\0'),
    'Hello & welcome\nfriend',
  );
  assert.equal(safeError(new Error('C:\\Users\\Sam\\token.txt ECONNRESET secret-token')), 'NETWORK_UNAVAILABLE');
  assert.equal(safeError(new Error('signature belongs to Mallory')), 'INVALID_SIGNER');
  assert.equal(safeError(new Error('mystery at C:\\private\\file.exe')), 'UPDATE_FAILED');
});

test('check, download, and install are separate and duplicate-safe', async () => {
  const x = harness();
  assert.equal((await x.controller.download()).status, 'idle');
  await x.controller.check();
  await x.controller.check();
  assert.deepEqual(x.calls, ['check']);
  x.events.get('update-available')({
    version: '1.1.0-alpha.4', releaseDate: '2026-08-19T00:00:00Z',
    releaseNotes: '<b>Safer updater</b>', files: [{ size: 4096 }],
  });
  assert.equal(x.controller.getState().releaseNotes, 'Safer updater');
  assert.equal(x.controller.getState().bytesTotal, 4096);
  await x.controller.download();
  await x.controller.download();
  assert.deepEqual(x.calls, ['check', 'download']);
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4', transferred: 10, total: 10 });
  await x.controller.install();
  await x.controller.install();
  assert.deepEqual(x.calls, ['check', 'download', 'prepare', 'install']);
});

test('progress stays finite, nonnegative, clamped, and monotonic', async () => {
  const x = harness();
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await x.controller.download();
  x.events.get('download-progress')({ percent: 80, transferred: 8, total: 10 });
  x.events.get('download-progress')({ percent: 20, transferred: 2, total: 5 });
  x.events.get('download-progress')({ percent: Number.POSITIVE_INFINITY, transferred: Number.NaN, total: -1 });
  const state = x.controller.getState();
  assert.deepEqual(
    { percent: state.percent, transferred: state.bytesTransferred, total: state.bytesTotal },
    { percent: 80, transferred: 8, total: 10 },
  );
  assert.equal(Object.isFrozen(state), true);
  assert.doesNotThrow(() => structuredClone(state));
});

test('recording blocks install while retaining ready state and a safe reason', async () => {
  const x = harness({ busy: true });
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await x.controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
  assert.equal(x.controller.getState().errorCode, 'ACTIVE_DICTATION');
  await x.controller.install();
  assert.deepEqual(x.calls, ['download']);
  assert.equal(x.controller.getState().status, 'ready');
  x.activity.busy = false;
  x.activity.authoritative.recording = false;
  x.controller.refreshInstallEligibility();
  assert.equal(x.controller.getState().errorCode, null);
  await x.controller.install();
  assert.deepEqual(x.calls, ['download', 'prepare', 'install']);
});

test('renderer idle cannot override authoritative recording or processing state', async () => {
  for (const authoritative of [
    { recording: true, processing: false },
    { recording: false, processing: true },
  ]) {
    const x = harness({ busy: false });
    x.activity.authoritative = authoritative;
    x.events.get('update-available')({ version: '1.1.0-alpha.4' });
    await x.controller.download();
    x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
    await x.controller.install();
    assert.deepEqual(x.calls, ['download']);
    assert.equal(x.controller.getState().status, 'ready');
    assert.equal(x.controller.getState().errorCode, 'ACTIVE_DICTATION');
  }
});

test('unavailable or malformed authoritative state fails closed and remains retryable', async () => {
  for (const authoritative of [null, {}, { recording: false }, { recording: 'no', processing: false }]) {
    const x = harness({ busy: false });
    x.activity.authoritative = authoritative;
    x.events.get('update-available')({ version: '1.1.0-alpha.4' });
    await x.controller.download();
    x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
    await x.controller.install();
    assert.deepEqual(x.calls, ['download']);
    assert.equal(x.controller.getState().status, 'ready');
    assert.equal(x.controller.getState().errorCode, 'RUNTIME_STATUS_UNAVAILABLE');

    x.activity.authoritative = { recording: false, processing: false };
    await x.controller.install();
    assert.deepEqual(x.calls, ['download', 'prepare', 'install']);
  }
});

test('authoritative guard errors fail closed before shutdown', async () => {
  const x = harness({ busy: false });
  const controller = createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0-alpha.3', updater: x.updater,
    activityGuard: () => false,
    authoritativeActivityGuard: async () => { throw new Error('backend token rejected at C:\\private'); },
    prepareQuit: async () => x.calls.push('prepare'),
  });
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
  await controller.install();
  assert.deepEqual(x.calls, ['download']);
  assert.equal(controller.getState().status, 'ready');
  assert.equal(controller.getState().errorCode, 'RUNTIME_STATUS_UNAVAILABLE');
});

test('a missing authoritative guard fails closed even when renderer activity says idle', async () => {
  const x = harness({ busy: false });
  const controller = createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0-alpha.3', updater: x.updater,
    activityGuard: () => false,
    prepareQuit: async () => x.calls.push('prepare'),
  });
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
  await controller.install();
  assert.deepEqual(x.calls, ['download']);
  assert.equal(controller.getState().status, 'ready');
  assert.equal(controller.getState().errorCode, 'RUNTIME_STATUS_UNAVAILABLE');
});

test('concurrent install requests are single-flight before the authoritative check resolves', async () => {
  const x = harness({ busy: false });
  let releaseAuthority;
  const authority = new Promise((resolve) => { releaseAuthority = resolve; });
  const controller = createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0-alpha.3', updater: x.updater,
    activityGuard: () => false,
    authoritativeActivityGuard: () => authority,
    prepareQuit: async () => x.calls.push('prepare'),
  });
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });

  const first = controller.install();
  const duplicate = controller.install();
  assert.equal((await duplicate).status, 'ready');
  releaseAuthority({ recording: false, processing: false });
  await first;

  assert.deepEqual(x.calls, ['download', 'prepare', 'install']);
  assert.equal(controller.getState().status, 'installing');
});

test('renderer activity cannot clear an unavailable authoritative status', async () => {
  const x = harness({ busy: false });
  x.activity.authoritative = null;
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await x.controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
  await x.controller.install();
  assert.equal(x.controller.getState().errorCode, 'RUNTIME_STATUS_UNAVAILABLE');

  x.activity.busy = false;
  x.controller.refreshInstallEligibility();
  assert.equal(x.controller.getState().errorCode, 'RUNTIME_STATUS_UNAVAILABLE');

  x.activity.authoritative = { recording: false, processing: false };
  await x.controller.install();
  assert.deepEqual(x.calls, ['download', 'prepare', 'install']);
});

test('install revalidates ready state after the authoritative check resolves', async () => {
  const x = harness({ busy: false });
  let releaseAuthority;
  const authority = new Promise((resolve) => { releaseAuthority = resolve; });
  const controller = createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0-alpha.3', updater: x.updater,
    activityGuard: () => false,
    authoritativeActivityGuard: () => authority,
    prepareQuit: async () => x.calls.push('prepare'),
  });
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });

  const install = controller.install();
  x.events.get('error')(new Error('network disconnected'));
  releaseAuthority({ recording: false, processing: false });
  await install;

  assert.deepEqual(x.calls, ['download']);
  assert.equal(controller.getState().status, 'error');
  assert.equal(controller.getState().errorCode, 'NETWORK_UNAVAILABLE');
});

test('errors retry and listeners unsubscribe cleanly', async () => {
  const x = harness();
  const seen = [];
  const unsubscribe = x.controller.subscribe((state) => seen.push(state.status));
  x.updater.checkForUpdates = async () => { throw Object.assign(new Error('offline'), { code: 'ENETUNREACH' }); };
  await x.controller.check();
  assert.equal(x.controller.getState().errorCode, 'NETWORK_UNAVAILABLE');
  x.updater.checkForUpdates = async () => x.calls.push('retry');
  await x.controller.check();
  assert.equal(x.controller.getState().status, 'checking');
  const count = seen.length;
  unsubscribe();
  x.events.get('update-not-available')();
  assert.equal(seen.length, count);
});

test('a synchronous installer launch failure invokes recovery and leaves a safe error', async () => {
  const x = harness();
  let recovered = 0;
  x.updater.quitAndInstall = () => { throw new Error('installer failed at C:\\private\\update.exe'); };
  const controller = createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0-alpha.3', updater: x.updater,
    authoritativeActivityGuard: async () => ({ recording: false, processing: false }),
    prepareQuit: async () => x.calls.push('prepare'),
    recoverFromFailedInstall: async () => { recovered += 1; },
  });
  x.events.get('update-available')({ version: '1.1.0-alpha.4' });
  await controller.download();
  x.events.get('update-downloaded')({ version: '1.1.0-alpha.4' });
  await controller.install();
  assert.equal(recovered, 1);
  assert.equal(controller.getState().status, 'error');
  assert.equal(controller.getState().errorCode, 'UPDATE_FAILED');
});
