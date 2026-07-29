// The Stream Deck plugin, against a fake deck and a fake BetterFingers.
//
// No hardware exists on this project's machines. These tests prove the PROTOCOL
// and the action mapping and prove nothing about a physical deck; the manual
// steps that would are in integrations/streamdeck/QUALIFICATION.md, and the
// honest status is asserted at the bottom of this file so it cannot quietly
// become a claim of support.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const PLUGIN_DIR = path.join(REPO, 'integrations', 'streamdeck');
const require = createRequire(import.meta.url);

const { createPlugin, registrationMessage, PLUGIN_UUID, RELEASE_FOR } =
  require(path.join(PLUGIN_DIR, 'src', 'plugin.js'));

const MANIFEST = JSON.parse(fs.readFileSync(path.join(PLUGIN_DIR, 'manifest.json'), 'utf8'));

function uuid(actionId) {
  return `${PLUGIN_UUID}.${actionId}`;
}

/** A fake deck (collects what the plugin sends) and a fake BetterFingers. */
function harness({ replies = {}, fail = false } = {}) {
  const sent = [];
  const posted = [];
  const plugin = createPlugin({
    send: (message) => sent.push(message),
    post: async (routePath, body) => {
      posted.push({ path: routePath, body });
      if (fail) throw new Error('BetterFingers is not running');
      return replies[routePath] || { ok: true, status: 'ok' };
    },
  });
  return { plugin, sent, posted };
}

const APPEAR = (context, actionId, extra = {}) => ({
  event: 'willAppear',
  context,
  action: uuid(actionId),
  device: 'DEV1',
  payload: { settings: {}, title: '', coordinates: { column: 0, row: 0 }, ...extra },
});

// --- registration ------------------------------------------------------------

test('registration is the exact handshake the Stream Deck expects', () => {
  assert.deepEqual(
    registrationMessage({ registerEvent: 'registerPlugin', pluginUUID: 'ABC' }),
    { event: 'registerPlugin', uuid: 'ABC' },
  );
});

// --- the manifest ------------------------------------------------------------

test('the manifest declares one action per bindable BetterFingers action id', () => {
  // The Python side asserts the same equality from its end
  // (tests/test_stream_deck_config.py), so the two cannot drift apart without
  // one of the two suites going red.
  const declared = MANIFEST.Actions.map((a) => a.UUID).sort();
  const expected = [
    'application_profile.activate', 'capture.cancel', 'command.begin',
    'dictation.begin', 'dictation.toggle', 'emergency.stop',
    'latest.copy', 'latest.inject', 'latest.read',
    'persona.activate', 'workflow.run', 'writing_preset.activate',
  ].map(uuid).sort();
  assert.deepEqual(declared, expected);
});

test('the manifest never declares a release half as its own key', () => {
  // Binding "end dictation" to a key is how a recording gets stranded when the
  // begin half never fired.
  for (const releaseId of Object.values(RELEASE_FOR)) {
    assert.ok(!MANIFEST.Actions.some((a) => a.UUID === uuid(releaseId)), releaseId);
  }
});

test('only the parameterised actions carry a property inspector', () => {
  const withPI = MANIFEST.Actions.filter((a) => a.PropertyInspectorPath).map((a) => a.UUID);
  assert.deepEqual(withPI.sort(), [
    'application_profile.activate', 'persona.activate',
    'workflow.run', 'writing_preset.activate',
  ].map(uuid).sort());
});

test('every file the manifest points at exists', () => {
  for (const relative of [MANIFEST.CodePath, MANIFEST.PropertyInspectorPath]) {
    assert.ok(fs.existsSync(path.join(PLUGIN_DIR, relative)), relative);
  }
});

// --- key presses -------------------------------------------------------------

test('a key press sends exactly one dispatch, with the id from the action UUID', async () => {
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'latest.copy'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('latest.copy') });

  const dispatches = posted.filter((p) => p.path === '/input/dispatch');
  assert.equal(dispatches.length, 1);
  assert.equal(dispatches[0].body.action_id, 'latest.copy');
  assert.equal(dispatches[0].body.source, 'stream_deck');
  assert.equal(dispatches[0].body.device_key, 'stream_deck:DEV1');
});

test('a forged action id in settings cannot override the action UUID', async () => {
  // The key is what it was created as. Settings are user-editable JSON; the
  // action UUID is not.
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'latest.copy', {
    settings: { action_id: 'emergency.stop', param: 'x' },
  }));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('latest.copy') });

  const dispatch = posted.find((p) => p.path === '/input/dispatch');
  assert.equal(dispatch.body.action_id, 'latest.copy');
});

test('a key belonging to another plugin is refused and alerts', async () => {
  const { plugin, posted, sent } = harness();
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: 'com.someoneelse.plugin.copy' });
  assert.equal(posted.filter((p) => p.path === '/input/dispatch').length, 0);
  assert.deepEqual(sent, [{ event: 'showAlert', context: 'ctx1' }]);
});

test('the plugin can only send ids and a chosen name — never work', async () => {
  // The structural claim in deliverable 4: "The plugin owns NO workflow
  // definitions." A workflow key sends an id; there is no field on the wire
  // that could carry a step, a command, a message or a path.
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'workflow.run', {
    settings: { param: 'start_work_day', steps: [{ action: 'shell', command: 'rm -rf ~' }] },
  }));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('workflow.run') });

  const dispatch = posted.find((p) => p.path === '/input/dispatch');
  assert.deepEqual(Object.keys(dispatch.body).sort(),
    ['action_id', 'device_key', 'hold', 'param', 'source']);
  assert.equal(dispatch.body.param, 'start_work_day');
  assert.ok(!JSON.stringify(dispatch.body).includes('rm -rf'));
});

// --- holds -------------------------------------------------------------------

test('a holdable key sends begin on keyDown and end on keyUp', async () => {
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'dictation.begin'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('dictation.begin') });
  await plugin.handle({ event: 'keyUp', context: 'ctx1', action: uuid('dictation.begin') });

  const ids = posted.filter((p) => p.path === '/input/dispatch').map((p) => p.body.action_id);
  assert.deepEqual(ids, ['dictation.begin', 'dictation.end']);
});

test('a holdable keyDown declares the hold, so an unplug can release it', async () => {
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'command.begin'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('command.begin') });
  assert.equal(posted.find((p) => p.path === '/input/dispatch').body.hold, true);
});

test('a non-holdable key does not claim a hold, and its keyUp does nothing', async () => {
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'emergency.stop'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('emergency.stop') });
  await plugin.handle({ event: 'keyUp', context: 'ctx1', action: uuid('emergency.stop') });

  const dispatches = posted.filter((p) => p.path === '/input/dispatch');
  assert.equal(dispatches.length, 1);
  assert.equal(dispatches[0].body.hold, false);
});

// --- device lifecycle --------------------------------------------------------

test('a disconnect asks BetterFingers to release, rather than sending release ids itself', async () => {
  // D-0026: one release mechanism. If the plugin tried to send `dictation.end`
  // on unplug it would be guessing at what was held, and it would be a second
  // unplug path nobody exercises until it is broken.
  const { plugin, posted } = harness();
  await plugin.handle({ event: 'deviceDidDisconnect', device: 'DEV1' });

  assert.deepEqual(posted.map((p) => p.path), ['/stream-deck/device/disconnected']);
  assert.deepEqual(posted[0].body, { device: 'DEV1' });
});

test('a connect reports the device so the dashboard can name it', async () => {
  const { plugin, posted } = harness();
  await plugin.handle({
    event: 'deviceDidConnect', device: 'DEV1',
    deviceInfo: { name: 'Stream Deck XL', size: { columns: 8, rows: 4 } },
  });
  assert.equal(posted[0].path, '/stream-deck/device');
  assert.equal(posted[0].body.name, 'Stream Deck XL');
});

// --- the mirror --------------------------------------------------------------

test('a key that appears is mirrored, and one that disappears is forgotten', async () => {
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'latest.read', { title: 'Read it' }));
  assert.equal(posted[0].path, '/stream-deck/key');
  assert.equal(posted[0].body.title, 'Read it');

  await plugin.handle({ event: 'willDisappear', context: 'ctx1', action: uuid('latest.read') });
  assert.deepEqual(posted.at(-1), { path: '/stream-deck/key/forget', body: { context: 'ctx1' } });
  assert.deepEqual(plugin.knownKeys(), []);
});

test('changed settings re-mirror so the dashboard does not go stale', async () => {
  const { plugin, posted } = harness();
  await plugin.handle(APPEAR('ctx1', 'persona.activate'));
  await plugin.handle({
    event: 'didReceiveSettings', context: 'ctx1', action: uuid('persona.activate'),
    payload: { settings: { param: 'True Janitor' } },
  });
  assert.equal(posted.at(-1).body.settings.param, 'True Janitor');
});

// --- feedback ----------------------------------------------------------------

test('a refusal alerts on the key and a success does not', async () => {
  const { plugin, sent } = harness({
    replies: { '/input/dispatch': { ok: false, status: 'needs_param' } },
  });
  await plugin.handle(APPEAR('ctx1', 'persona.activate'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('persona.activate') });
  assert.deepEqual(sent, [{ event: 'showAlert', context: 'ctx1' }]);
});

test('a key that succeeded shows OK', async () => {
  const { plugin, sent } = harness();
  await plugin.handle(APPEAR('ctx1', 'latest.copy'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('latest.copy') });
  assert.deepEqual(sent, [{ event: 'showOk', context: 'ctx1' }]);
});

test('BetterFingers not running alerts on the key rather than throwing', async () => {
  // The deck sits there all day; the app comes and goes. This is the common
  // case, not an exception.
  const { plugin, sent } = harness({ fail: true });
  await plugin.handle(APPEAR('ctx1', 'latest.copy'));
  await plugin.handle({ event: 'keyDown', context: 'ctx1', action: uuid('latest.copy') });
  assert.deepEqual(sent, [{ event: 'showAlert', context: 'ctx1' }]);
});

test('a failed mirror is silent — the key still works', async () => {
  const { plugin, sent } = harness({ fail: true });
  await plugin.handle(APPEAR('ctx1', 'latest.copy'));
  assert.deepEqual(sent, []);
});

test('an unknown Stream Deck event is ignored rather than mishandled', async () => {
  const { plugin, posted, sent } = harness();
  await plugin.handle({ event: 'systemDidWakeUp' });
  await plugin.handle({});
  assert.deepEqual(posted, []);
  assert.deepEqual(sent, []);
});

// --- honesty -----------------------------------------------------------------

test('the qualification document says unqualified, in the first line', () => {
  const doc = fs.readFileSync(path.join(PLUGIN_DIR, 'QUALIFICATION.md'), 'utf8');
  assert.match(doc.split('\n')[0], /NOT QUALIFIED/);
  assert.match(doc, /No Stream Deck hardware exists/);
  // And it lists real steps rather than gesturing at "manual testing".
  assert.ok(doc.split('\n').filter((line) => /^\| \d+ \|/.test(line)).length >= 12);
});
