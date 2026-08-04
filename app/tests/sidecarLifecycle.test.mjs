// Hardware-free process ownership tests for the Electron sidecar. The helper
// seam lets these tests prove signal targets without starting Python, models,
// an Electron window, or a desktop capture flow.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';

import {
  createSidecar,
  getOwnedProcessGroupId,
  killChildProcess,
  spawnOwnedBackend,
} from '../src/main/sidecar.js';

function fakeChild(pid = 4321, { onKill = null } = {}) {
  const child = new EventEmitter();
  child.pid = pid;
  child.killed = false;
  child.exitCode = null;
  child.signalCode = null;
  child.kill = (signal) => {
    if (typeof onKill === 'function') {
      onKill(signal, child);
    }
    return true;
  };
  return child;
}

test('POSIX owned spawn requests a detached process group and Windows stays attached', () => {
  const calls = [];
  const spawnImpl = (command, args, options) => {
    calls.push({ command, args, options });
    return { pid: 101 };
  };

  spawnOwnedBackend('stub-backend', ['--test'], { stdio: 'ignore' }, { platform: 'linux', spawnImpl });
  spawnOwnedBackend('stub-backend.exe', [], { windowsHide: true }, { platform: 'win32', spawnImpl });

  assert.equal(calls[0].options.detached, true);
  assert.equal(calls[1].options.detached, undefined);
  assert.equal(calls[1].options.windowsHide, true);
});

test('group ownership requires a separate session and never accepts Electron current group', () => {
  const childPid = 4321;
  const currentPid = process.pid;
  const separateSession = (pid) => pid === childPid
    ? { processGroupId: childPid, sessionId: 22 }
    : { processGroupId: 11, sessionId: 11 };
  const currentGroup = (pid) => pid === childPid
    ? { processGroupId: childPid, sessionId: 11 }
    : { processGroupId: childPid, sessionId: 11 };

  assert.equal(
    getOwnedProcessGroupId(childPid, { platform: 'linux', readStat: separateSession }),
    childPid,
  );
  assert.equal(
    getOwnedProcessGroupId(childPid, { platform: 'linux', readStat: currentGroup }),
    null,
  );
  assert.notEqual(currentPid, childPid);
});

test('owned POSIX stop sends negative-PID SIGTERM and does not direct-signal the child', async () => {
  const childPid = 4321;
  const signals = [];
  const child = fakeChild(childPid, {
    onKill: (signal) => signals.push(['direct', signal]),
  });
  const readStat = (pid) => pid === childPid
    ? { processGroupId: childPid, sessionId: 22 }
    : { processGroupId: 11, sessionId: 11 };
  const killImpl = (pid, signal) => {
    signals.push([pid, signal]);
    if (signal === 'SIGKILL') {
      child.signalCode = 'SIGKILL';
      child.emit('exit', null, 'SIGKILL');
    }
  };

  await killChildProcess(child, {
    platform: 'linux',
    readStat,
    killImpl,
    graceMs: 25,
  });

  assert.deepEqual(signals, [[-childPid, 'SIGTERM'], [-childPid, 'SIGKILL']]);
});

test('unknown group ownership falls back to direct child SIGTERM then bounded SIGKILL', async () => {
  const signals = [];
  const child = fakeChild(4322, {
    onKill: (signal, processRef) => {
      signals.push(signal);
      if (signal === 'SIGKILL') {
        processRef.exitCode = null;
        processRef.signalCode = 'SIGKILL';
        processRef.emit('exit', null, 'SIGKILL');
      }
    },
  });

  await killChildProcess(child, {
    platform: 'linux',
    readStat: () => null,
    graceMs: 5,
    killSettleMs: 25,
  });

  assert.deepEqual(signals, ['SIGTERM', 'SIGKILL']);
});

test('Windows stop keeps taskkill tree behavior', async () => {
  const calls = [];
  const child = fakeChild(7654);
  const killer = new EventEmitter();
  const spawnImpl = (command, args, options) => {
    calls.push({ command, args, options });
    return killer;
  };

  const stopping = killChildProcess(child, { platform: 'win32', spawnImpl });
  killer.emit('exit', 0, null);
  await stopping;

  assert.deepEqual(calls, [{
    command: 'taskkill',
    args: ['/pid', '7654', '/t', '/f'],
    options: { stdio: 'ignore', windowsHide: true },
  }]);
});

test('a real detached stub is recognized as its own group and can be stopped', {
  skip: process.platform !== 'linux',
}, async (t) => {
  const child = spawnOwnedBackend(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    stdio: 'ignore',
  });
  t.after(async () => {
    await killChildProcess(child, { graceMs: 25, killSettleMs: 25 });
  });

  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(getOwnedProcessGroupId(child.pid), child.pid);
  await killChildProcess(child, { graceMs: 25, killSettleMs: 25 });
  assert.equal(child.signalCode, 'SIGTERM');
});

test('a health response that completes after public stop cannot restart or orphan the backend', async () => {
  let releaseHealth;
  const healthPending = new Promise((resolve) => {
    releaseHealth = resolve;
  });
  const timerCallbacks = [];
  let spawnCount = 0;
  const child = fakeChild(9001, {
    onKill: (signal, processRef) => {
      if (signal === 'SIGTERM') {
        processRef.signalCode = signal;
        processRef.emit('exit', null, signal);
      }
    },
  });
  const sidecar = createSidecar({
    platform: 'linux',
    port: 8123,
    devCommand: 'stub-backend',
    isTcpPortOpenImpl: async () => false,
    spawnProcess: () => {
      spawnCount += 1;
      return child;
    },
    waitForHealthyImpl: async () => ({ status: 'ok' }),
    fetchImpl: async () => ({ ok: true, json: async () => ({ schema_version: 1, backend_version: 'test' }) }),
    readHealthImpl: async () => healthPending,
    setIntervalImpl: (callback) => {
      timerCallbacks.push(callback);
      return { unref() {} };
    },
    clearIntervalImpl: () => {},
    readStat: () => null,
    stopGraceMs: 25,
  });

  await sidecar.start();
  assert.equal(spawnCount, 1);
  assert.equal(timerCallbacks.length, 1);

  const healthPoll = timerCallbacks[0]();
  await new Promise((resolve) => setImmediate(resolve));
  await sidecar.stop();
  releaseHealth(null);
  await healthPoll;
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(spawnCount, 1, 'the stale monitor callback must not launch a replacement');
  assert.equal(sidecar.getPid(), null);
  assert.equal(sidecar.getStatus().state, 'stopped');
});

test('a stale start finalizer cannot clear a deliberate replacement start', async (t) => {
  let releaseFirstWait = () => {};
  let releaseSecondWait = () => {};
  let waitCallCount = 0;
  let spawnCount = 0;
  const children = [];
  const sidecar = createSidecar({
    platform: 'linux',
    port: 8125,
    devCommand: 'stub-backend',
    isTcpPortOpenImpl: async () => false,
    spawnProcess: () => {
      const child = fakeChild(9100 + spawnCount, {
        onKill: (signal, processRef) => {
          processRef.signalCode = signal;
        },
      });
      spawnCount += 1;
      children.push(child);
      return child;
    },
    waitForHealthyImpl: async () => {
      waitCallCount += 1;
      return new Promise((resolve) => {
        if (waitCallCount === 1) {
          releaseFirstWait = resolve;
        } else {
          releaseSecondWait = resolve;
        }
      });
    },
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({ schema_version: 1, backend_version: 'test' }),
    }),
    readStat: () => null,
    stopGraceMs: 1,
  });

  let firstStart = null;
  let secondStart = null;
  t.after(async () => {
    releaseFirstWait({ status: 'ok' });
    releaseSecondWait({ status: 'ok' });
    await Promise.allSettled([firstStart, secondStart].filter(Boolean));
    await sidecar.stop();
  });

  firstStart = sidecar.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(spawnCount, 1);

  await sidecar.stop();
  secondStart = sidecar.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(spawnCount, 2);

  releaseFirstWait({ status: 'ok' });
  assert.equal(await firstStart, null);

  const thirdStart = sidecar.start();
  assert.strictEqual(thirdStart, secondStart);
  assert.equal(spawnCount, 2, 'the stale finalizer must not trigger a third spawn');

  releaseSecondWait({ status: 'ok' });
  await secondStart;
  assert.equal(children.length, 2);
});

test('repeated public stops and external ownership remain safe', async () => {
  let healthReads = 0;
  const sidecar = createSidecar({
    platform: 'linux',
    port: 8124,
    isTcpPortOpenImpl: async () => true,
    readHealthImpl: async () => {
      healthReads += 1;
      return { status: 'ok', active_job_count: 0 };
    },
  });

  const result = await sidecar.start();
  assert.equal(result.external, true);
  assert.equal(sidecar.getStatus().state, 'external');
  await sidecar.stop();
  await sidecar.stop();
  assert.equal(healthReads, 1);
  assert.equal(sidecar.getStatus().state, 'external');
  assert.equal(sidecar.getPid(), null);
});
