// Phase 0 items 6 and 11: a deny-by-default permission policy and a strict CSP on
// every shipped page.
// Run with: node --test app/tests/sessionSecurity.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const RENDERER = path.resolve(HERE, '..', 'src', 'renderer');
const {
  RENDERER_CSP,
  decidePermission,
  installSessionSecurity,
} = require('../src/main/sessionSecurity.js');
const { RENDERER_PAGES } = require('../src/main/senderValidation.js');

const RENDERER_DIR = '/opt/app/resources/app.asar/out/renderer';
const OPTIONS = { rendererDir: RENDERER_DIR, devOrigin: undefined };
const DASH = { id: 1 };
const OVERLAY = { id: 2 };
const OWN_PAGE = `file://${RENDERER_DIR}/signal-desk.html`;

function ask(permission, { wc = DASH, details = {} } = {}) {
  return decidePermission({
    permission,
    webContents: wc,
    details: { isMainFrame: true, requestingUrl: OWN_PAGE, ...details },
    captureWebContents: DASH,
    rendererOptions: OPTIONS,
  });
}

// --- permission policy -------------------------------------------------------

test('microphone is allowed only for the dashboard window asking for audio alone', () => {
  assert.equal(ask('media', { details: { mediaTypes: ['audio'] } }), true);
  assert.equal(ask('media', { details: { mediaType: 'audio', mediaTypes: undefined } }), true);
});

test('camera, audio+video and unknown media are refused', () => {
  assert.equal(ask('media', { details: { mediaTypes: ['video'] } }), false);
  assert.equal(ask('media', { details: { mediaTypes: ['audio', 'video'] } }), false);
  assert.equal(ask('media', { details: { mediaTypes: [] } }), false);
  assert.equal(ask('media', { details: { mediaType: 'unknown', mediaTypes: undefined } }), false);
});

test('microphone is refused for every other window, subframe or foreign page', () => {
  const audio = { mediaTypes: ['audio'] };
  assert.equal(ask('media', { wc: OVERLAY, details: audio }), false, 'overlay window');
  assert.equal(ask('media', { details: { ...audio, isMainFrame: false } }), false, 'subframe');
  assert.equal(ask('media', { details: { ...audio, requestingUrl: 'https://evil.example/' } }), false, 'remote page');
  assert.equal(ask('media', { details: { ...audio, requestingUrl: `file://${RENDERER_DIR}/evil.html` } }), false, 'unknown file');
});

test('with no capture window registered nothing is allowed', () => {
  assert.equal(decidePermission({
    permission: 'media', webContents: DASH, captureWebContents: null,
    details: { isMainFrame: true, requestingUrl: OWN_PAGE, mediaTypes: ['audio'] },
    rendererOptions: OPTIONS,
  }), false);
});

test('every other web permission is refused even from the dashboard', () => {
  for (const permission of [
    'clipboard-read', 'clipboard-sanitized-write', 'display-capture', 'geolocation', 'notifications',
    'midi', 'midiSysex', 'hid', 'serial', 'usb', 'bluetooth', 'fullscreen', 'openExternal',
    'pointerLock', 'idle-detection', 'window-management', 'persistent-storage', 'unknown',
  ]) {
    assert.equal(ask(permission), false, permission);
  }
});

// --- installation ------------------------------------------------------------

function fakeSession() {
  const ses = {
    handlers: {},
    listeners: {},
    setPermissionRequestHandler(fn) { ses.handlers.request = fn; },
    setPermissionCheckHandler(fn) { ses.handlers.check = fn; },
    setDevicePermissionHandler(fn) { ses.handlers.device = fn; },
    on(name, fn) { ses.listeners[name] = fn; },
    webRequest: { onHeadersReceived(fn) { ses.handlers.headers = fn; } },
  };
  return ses;
}

test('installSessionSecurity wires a deny-by-default request, check and device handler', () => {
  const ses = fakeSession();
  installSessionSecurity(ses, {
    getCaptureWebContents: () => DASH,
    rendererOptions: () => OPTIONS,
    devOrigin: undefined,
  });

  const verdicts = [];
  ses.handlers.request(OVERLAY, 'media', (v) => verdicts.push(v), { isMainFrame: true, requestingUrl: OWN_PAGE, mediaTypes: ['audio'] });
  ses.handlers.request(DASH, 'clipboard-read', (v) => verdicts.push(v), { isMainFrame: true, requestingUrl: OWN_PAGE });
  ses.handlers.request(DASH, 'media', (v) => verdicts.push(v), { isMainFrame: true, requestingUrl: OWN_PAGE, mediaTypes: ['audio'] });
  assert.deepEqual(verdicts, [false, false, true]);

  assert.equal(ses.handlers.check(DASH, 'clipboard-read', 'file:///', { requestingUrl: OWN_PAGE }), false);
  assert.equal(ses.handlers.check(OVERLAY, 'media', 'file:///', { mediaType: 'audio', requestingUrl: OWN_PAGE }), false);
  assert.equal(ses.handlers.device(), false);

  // A handler that throws must fail closed, not open.
  const exploding = [];
  ses.handlers.request({ get id() { throw new Error('boom'); } }, 'media', (v) => exploding.push(v), null);
  assert.deepEqual(exploding, [false]);
});

test('device pickers are cancelled', () => {
  const ses = fakeSession();
  installSessionSecurity(ses, { devOrigin: undefined });
  for (const picker of ['select-hid-device', 'select-serial-port', 'select-usb-device']) {
    let prevented = false;
    let chosen = null;
    ses.listeners[picker]({ preventDefault() { prevented = true; } }, {}, (id) => { chosen = id; });
    assert.equal(prevented, true, picker);
    assert.equal(chosen, '', picker);
  }
});

test('dev-server documents get the CSP as a response header, other responses are untouched', () => {
  const ses = fakeSession();
  installSessionSecurity(ses, { devOrigin: 'http://localhost:5173' });
  let out;
  ses.handlers.headers({ url: 'http://localhost:5173/signal-desk.html', resourceType: 'mainFrame', responseHeaders: { 'content-security-policy': ['default-src *'] } }, (r) => { out = r; });
  assert.deepEqual(out.responseHeaders, { 'Content-Security-Policy': [RENDERER_CSP] });
  ses.handlers.headers({ url: 'https://evil.example/x.html', resourceType: 'mainFrame', responseHeaders: { a: ['b'] } }, (r) => { out = r; });
  assert.deepEqual(out.responseHeaders, { a: ['b'] });
  ses.handlers.headers({ url: 'http://localhost:5173/x.js', resourceType: 'script', responseHeaders: { a: ['b'] } }, (r) => { out = r; });
  assert.deepEqual(out.responseHeaders, { a: ['b'] });
});
