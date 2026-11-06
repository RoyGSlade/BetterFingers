// The sidecar's on-disk raw log versus a factory reset.
//
// Reproduced in the packaged app (F1): the backend's factory reset deletes
// sidecar_backend_raw.log, but the Electron main process keeps appending every
// backend stdout/stderr line to it, so the file was back within the same second
// (the access-log lines of the reset request itself) and "Check what's left"
// reported `sidecar_raw_log` still present right after a reset that had verified.
// The fix is that main stops writing the file for the rest of the session once a
// reset has run; the in-memory buffer (what the app shows) is unaffected.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { createSidecar } from '../src/main/sidecar.js';

function fakeChild(pid = 7001) {
  const child = new EventEmitter();
  child.pid = pid;
  child.killed = false;
  child.exitCode = null;
  child.signalCode = null;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = (signal) => {
    child.signalCode = signal;
    child.emit('exit', null, signal);
    return true;
  };
  return child;
}

async function startedSidecar(t, extra = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-rawlog-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const logPath = path.join(dir, 'sidecar_backend_raw.log');
  const child = fakeChild();
  const sidecar = createSidecar({
    platform: 'linux',
    port: 8190,
    devCommand: 'stub-backend',
    userDataPath: logPath,
    isTcpPortOpenImpl: async () => false,
    spawnProcess: () => child,
    waitForHealthyImpl: async () => ({ status: 'ok' }),
    fetchImpl: async () => ({ ok: true, json: async () => ({ schema_version: 1, backend_version: 'test' }) }),
    readHealthImpl: async () => ({ status: 'ok' }),
    setIntervalImpl: () => ({ unref() {} }),
    clearIntervalImpl: () => {},
    readStat: () => null,
    stopGraceMs: 25,
    ...extra,
  });
  await sidecar.start();
  t.after(async () => { await sidecar.stop(); });
  return { sidecar, child, logPath };
}

test('by default the raw log is written, as before', async (t) => {
  const { sidecar, child, logPath } = await startedSidecar(t);
  assert.equal(sidecar.isRawLogEnabled(), true);
  child.stdout.emit('data', Buffer.from('hello from the backend\n'));
  assert.match(fs.readFileSync(logPath, 'utf8'), /hello from the backend/);
});

test('once disabled, nothing more reaches disk and a deleted log is not recreated', async (t) => {
  const { sidecar, child, logPath } = await startedSidecar(t);
  child.stdout.emit('data', Buffer.from('before the reset\n'));
  assert.ok(fs.existsSync(logPath));

  sidecar.setRawLogEnabled(false);
  fs.rmSync(logPath); // what the backend's factory reset does
  child.stdout.emit('data', Buffer.from('INFO: 127.0.0.1 - "POST /privacy/factory-reset" 200 OK\n'));
  child.stderr.emit('data', Buffer.from('a warning after the reset\n'));

  assert.equal(sidecar.isRawLogEnabled(), false);
  assert.equal(fs.existsSync(logPath), false, 'the reset log must stay gone until the app restarts');
});

test('the in-memory log the app shows keeps collecting while the file is off', async (t) => {
  const { sidecar, child } = await startedSidecar(t);
  sidecar.setRawLogEnabled(false);
  child.stdout.emit('data', Buffer.from('still visible in the app\n'));
  assert.ok(sidecar.getLogs().some((line) => line.includes('still visible in the app')));
});

test('re-enabling resumes the file (a reset that never ran must not leave logging off)', async (t) => {
  const { sidecar, child, logPath } = await startedSidecar(t);
  sidecar.setRawLogEnabled(false);
  sidecar.setRawLogEnabled(true);
  child.stdout.emit('data', Buffer.from('logging again\n'));
  assert.match(fs.readFileSync(logPath, 'utf8'), /logging again/);
});

test('a restart of the backend while disabled does not write the session separator either', async (t) => {
  const { sidecar, logPath } = await startedSidecar(t);
  sidecar.setRawLogEnabled(false);
  fs.rmSync(logPath, { force: true });
  await sidecar.stop();
  await sidecar.start();
  assert.equal(fs.existsSync(logPath), false);
});

test('only an exact boolean turns it back on', async (t) => {
  const { sidecar } = await startedSidecar(t);
  sidecar.setRawLogEnabled(false);
  sidecar.setRawLogEnabled('yes');
  assert.equal(sidecar.isRawLogEnabled(), false);
  sidecar.setRawLogEnabled(true);
  assert.equal(sidecar.isRawLogEnabled(), true);
});

test('a credential in backend output never reaches the log buffer or the raw log file (Phase 0 item 10)', async (t) => {
  const { sidecar, child, logPath } = await startedSidecar(t);
  const secret = 'ab12cd34'.repeat(8);
  child.stdout.emit('data', Buffer.from(`INFO: 127.0.0.1 - "GET /ws/voice_status?token=${secret} HTTP/1.1" 101\n`));
  child.stderr.emit('data', Buffer.from(`debug Authorization: Bearer ${secret}\n`));
  const buffered = sidecar.getLogs().join('\n');
  assert.ok(!buffered.includes(secret), 'in-memory buffer');
  assert.ok(buffered.includes('/ws/voice_status'), 'the rest of the line survives');
  assert.ok(!fs.readFileSync(logPath, 'utf8').includes(secret), 'raw log file');
});
