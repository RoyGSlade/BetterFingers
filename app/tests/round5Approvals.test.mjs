// Round 5 (Codex re-check 4): blockers 2 and 3 at the approval broker, the proxy, the preload
// and the Studio. Run with: node --test app/tests/round5Approvals.test.mjs
//
// Blocker 2: renaming a persona moved its examples with no ticket and no native preview. Phase 0
// turns renaming off: main's broker and the preload expose none, the dashboard proxy refuses the
// route, and the Studio's rename control is hidden.
// Blocker 3: count fallbacks authorised content the native dialog did not show. Clearing one
// persona's learned examples and deleting a persona now show the COMPLETE example list or give
// Close only; the global learned clear and the privacy wipes are explicit broad-scope actions
// whose dialog states the scope plainly and whose ticket binds exactly that scope; a wipe whose
// category labels do not fit gets Close only (there is no "N kinds of data" form); the factory
// reset keeps "erase everything" plus its typed phrase.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', 'src');
const broker = require('../src/main/approvalBroker.js');
const { createApprovalBroker, fewShotItems, displayWidth, MAX_DISPLAY_LINES, WRAP_WIDTH } = broker;

const SECRET = Buffer.from(Array.from({ length: 32 }, (_, i) => i));
const TOO_MANY = 'Too many to show here: delete examples one at a time, or use Settings > Privacy > Erase all learned examples';
const RENAME_OFF = 'Renaming is turned off for now; create a new persona and copy the voice.';

function payloadOf(ticket) {
  const expected = crypto.createHmac('sha256', SECRET).update(ticket.payload, 'ascii').digest('hex');
  assert.equal(ticket.sig, expected);
  return JSON.parse(Buffer.from(ticket.payload, 'base64url').toString('utf8'));
}

function makeBroker({ answers = [0], handlers = {}, budgets = {} } = {}) {
  const queue = [...answers];
  const dialog = {
    shown: [],
    async showMessageBox(...args) {
      const options = args[args.length - 1];
      dialog.shown.push(options);
      return { response: queue.length ? queue.shift() : 1 };
    },
  };
  const calls = [];
  const backend = {
    async send(method, route, body) {
      calls.push({ method, path: route, body });
      const handler = handlers[`${method} ${route}`];
      if (!handler) return { ok: true, status: 200, body: {} };
      return typeof handler === 'function' ? handler(body) : handler;
    },
  };
  let clock = 1_000_000;
  const instance = createApprovalBroker({ secret: SECRET, dialog, backend, now: () => { clock += 1000; return clock; }, getBudgets: () => budgets });
  return { instance, dialog, calls };
}

const approving = (options) => Array.isArray(options.buttons) && options.buttons.length > 1;
const closeOnly = (options) => Array.isArray(options.buttons) && options.buttons.length === 1 && options.buttons[0] === 'Close';
// The text a person reads, with the visible wrap markers taken out again (wrapping keeps every
// character, so an example shown in full is a substring of this).
const unwrapped = (options) => `${options.message}\n${options.detail || ''}`.replace(/\n {3}↳ /g, '');

function assertFits(options, lines = MAX_DISPLAY_LINES) {
  const message = String(options.message).split('\n');
  const detail = String(options.detail || '').split('\n');
  assert.ok(message.length * 2 + detail.length <= lines, `the dialog draws ${message.length * 2 + detail.length} lines`);
  for (const line of [...message, ...detail]) assert.ok(displayWidth(line) <= WRAP_WIDTH, `a ${displayWidth(line)}-wide line`);
}

function examples(count, width = 8, prefix = 'e') {
  return Array.from({ length: count }, (_, i) => ({
    id: `${prefix}${i}`,
    raw: `said${i} ${'x'.repeat(width)}`.slice(0, Math.max(6, width + 6)),
    out: `Out${i} ${'y'.repeat(width)}`.slice(0, Math.max(6, width + 6)),
  }));
}

// ---- blocker 2: persona rename is off --------------------------------------------------------

test('blocker 2: the dashboard proxy refuses the persona rename route', () => {
  const proxy = require('../src/main/backendProxy.js');
  for (const route of ['/personas/Coach/rename', '/personas/Coach%20Two/rename']) {
    assert.notEqual(proxy._validateRequest('POST', route), null, route);
  }
});

test('blocker 2: neither the broker, the IPC layer nor any preload exposes a rename', () => {
  const { instance } = makeBroker();
  assert.deepEqual(Object.keys(instance).filter((key) => /rename/i.test(key)), []);
  const ipc = fs.readFileSync(path.join(SRC, 'main', 'ipc.js'), 'utf8');
  assert.ok(!/persona[^'"\n]*rename|rename[^'"\n]*persona/i.test(ipc), 'no persona rename channel in ipc.js');
  for (const file of fs.readdirSync(path.join(SRC, 'preload'))) {
    const source = fs.readFileSync(path.join(SRC, 'preload', file), 'utf8');
    assert.ok(!/rename/i.test(source), `${file} exposes nothing that renames`);
  }
});

test('blocker 2: the renderer has no rename call and the Studio rename control is hidden with the message', async () => {
  const api = fs.readFileSync(path.join(SRC, 'renderer', 'api', 'backend.js'), 'utf8');
  assert.ok(!/renamePersona/.test(api), 'renderer/api/backend.js has no renamePersona');
  assert.ok(!/PERSONAS_URL[^\n]*\/rename/.test(api));
  const studio = fs.readFileSync(path.join(SRC, 'renderer', 'features', 'studioWorkspace.js'), 'utf8');
  assert.ok(!/renamePersona/.test(studio), 'the Studio never calls a rename');
  assert.ok(studio.includes(RENAME_OFF), 'the Studio says why renaming is unavailable');
  const caps = await import('../src/renderer/config/alphaCapabilities.js');
  assert.equal(caps.ALPHA_CAPABILITIES.personaRename, false);
  assert.ok(caps.ALPHA_CAPABILITY_SELECTORS.personaRename.includes('#sdPersonaRenameButton'));
});

// ---- blocker 3: per-persona learned clear and persona deletion ------------------------------

test('blocker 3: clearing a persona’s learned examples shows every example in full when it fits', async () => {
  const list = examples(3);
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'GET /personas/Coach/examples': { ok: true, status: 200, body: { examples: list } } },
  });
  const result = await instance.clearLearnedExamples({ persona: 'Coach' });
  assert.equal(result.ok, true);
  const options = dialog.shown[0];
  assert.ok(approving(options));
  assertFits(options);
  for (const item of list) {
    assert.ok(unwrapped(options).includes(item.raw), `${item.raw} is shown`);
    assert.ok(unwrapped(options).includes(item.out), `${item.out} is shown`);
  }
  const del = calls.find((c) => c.method === 'DELETE');
  assert.deepEqual(payloadOf(del.body.approval).bind, broker.learnedClearBind('Coach', fewShotItems(list)));
});

test('blocker 3: a learned list too long to show gets Close only, with the way forward, and nothing is signed', async () => {
  const list = [{ id: 'long', raw: 'a long example '.repeat(40), out: 'its long rewrite '.repeat(40) }];
  const { instance, dialog, calls } = makeBroker({
    answers: [0, 0], handlers: { 'GET /personas/Coach/examples': { ok: true, status: 200, body: { examples: list } } },
  });
  const result = await instance.clearLearnedExamples({ persona: 'Coach' });
  assert.equal(result.ok, false);
  assert.equal(dialog.shown.length, 1);
  assert.ok(closeOnly(dialog.shown[0]), 'Close is the only button');
  assert.ok(unwrapped(dialog.shown[0]).includes(TOO_MANY));
  assert.ok(String(result.error).includes(TOO_MANY), 'the page is told the same thing');
  assert.ok(!calls.some((c) => c.method === 'DELETE'), 'nothing was forwarded');
});

test('blocker 3: deleting a persona whose examples do not fit gets Close only', async () => {
  const few = examples(40).map(({ raw, out }) => ({ raw, out }));
  const { instance, dialog, calls } = makeBroker({
    answers: [0, 0], handlers: { 'GET /personas/Custom': { ok: true, status: 200, body: { few_shot: few } } },
  });
  const result = await instance.deletePersona({ name: 'Custom' });
  assert.equal(result.ok, false);
  assert.ok(closeOnly(dialog.shown[0]));
  assert.ok(/Too many to show here: delete examples one at a time/.test(unwrapped(dialog.shown[0])));
  assert.ok(!calls.some((c) => c.method === 'DELETE'));
});

test('blocker 3: signing an undisplayed example list is impossible (clear and delete, every size)', async () => {
  for (const width of [4, 60, 150]) {
    for (let count = 1; count <= 30; count += 1) {
      const list = examples(count, width, `w${width}-`);
      const cases = [
        ['clearLearnedExamples', { persona: 'Coach' }, 'GET /personas/Coach/examples', { examples: list }],
        ['deletePersona', { name: 'Coach' }, 'GET /personas/Coach', { few_shot: list.map(({ raw, out }) => ({ raw, out })) }],
      ];
      for (const [method, args, route, body] of cases) {
        for (const budgets of [{}, { lines: 14 }]) {
          const { instance, dialog, calls } = makeBroker({ answers: [0, 0], handlers: { [route]: { ok: true, status: 200, body } }, budgets });
          await instance[method](args);
          const forwarded = calls.some((c) => c.method === 'DELETE');
          const label = `${method} ${count}x${width} ${JSON.stringify(budgets)}`;
          if (!forwarded) {
            assert.ok(dialog.shown.every((o) => !approving(o)), `${label}: no approving dialog without forwarding`);
            continue;
          }
          const shown = dialog.shown.filter(approving);
          assert.equal(shown.length, 1, label);
          assertFits(shown[0], budgets.lines || MAX_DISPLAY_LINES);
          for (const item of list) {
            assert.ok(unwrapped(shown[0]).includes(item.raw) && unwrapped(shown[0]).includes(item.out), `${label}: example ${item.id} was signed but not shown`);
          }
          assert.ok(!/too long to show|open the persona/i.test(shown[0].detail), `${label}: no "read it elsewhere" in an approving dialog`);
        }
      }
    }
  }
});

// ---- blocker 3: the global learned clear is a broad-scope action ----------------------------

test('blocker 3: the global learned clear states its scope plainly and the ticket binds that scope', async () => {
  const snapshot = { personas: [{ name: 'Coach', examples: examples(2) }, { name: 'Writer', examples: examples(1) }] };
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'GET /privacy/persona-learning/preview': { ok: true, status: 200, body: snapshot } },
  });
  const result = await instance.clearAllLearning({});
  assert.equal(result.ok, true);
  const options = dialog.shown[0];
  assert.ok(approving(options));
  assert.ok(unwrapped(options).includes('All learned examples for all personas: 3 examples'), options.detail);
  const del = calls.find((c) => c.method === 'DELETE');
  assert.equal(del.path, '/privacy/persona-learning');
  const payload = payloadOf(del.body.approval);
  assert.equal(payload.purpose, 'persona.learned_clear_all');
  assert.deepEqual(payload.bind, { scope: 'all_personas', example_count: '3' });
  assert.deepEqual(payload.bind, broker.learnedClearAllBind(3));
});

test('blocker 3: the global clear stays approvable at any size, because what it shows is the scope', async () => {
  const personas = Array.from({ length: 200 }, (_, i) => ({ name: `Persona number ${i} with a long name`, examples: examples(5, 120, `p${i}-`) }));
  for (const budgets of [{}, { lines: 12 }]) {
    const { instance, dialog, calls } = makeBroker({
      answers: [0], budgets, handlers: { 'GET /privacy/persona-learning/preview': { ok: true, status: 200, body: { personas } } },
    });
    assert.equal((await instance.clearAllLearning({})).ok, true);
    assert.ok(approving(dialog.shown[0]));
    assertFits(dialog.shown[0], budgets.lines || MAX_DISPLAY_LINES);
    assert.ok(unwrapped(dialog.shown[0]).includes('All learned examples for all personas: 1000 examples'));
    assert.deepEqual(payloadOf(calls.find((c) => c.method === 'DELETE').body.approval).bind, broker.learnedClearAllBind(1000));
  }
});

test('blocker 3: with nothing learned the global clear asks nothing and deletes nothing', async () => {
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'GET /privacy/persona-learning/preview': { ok: true, status: 200, body: { personas: [] } } },
  });
  const result = await instance.clearAllLearning({});
  assert.equal(result.ok, true);
  assert.equal(dialog.shown.length, 0);
  assert.ok(!calls.some((c) => c.method === 'DELETE'));
});

// ---- blocker 3: privacy wipes list every category label, or Close only -----------------------

const PERSONAL_DATA_LABELS = ['Raw recordings', 'Draft JSON', 'Transcription history (SQLite)',
  'Temporary audio & conversion artifacts', 'Learned persona examples', 'Contacts', 'Cloned voices & metadata', 'Personas',
  'Personal dictionary', 'Macros', 'Personal profile (vibe, work style, hobbies)', 'Wake models & training artifacts',
  'Audio privacy recovery journal', 'MCP configuration', 'Graph data', 'Debug log', 'Sidecar backend raw log',
  'Application profiles & pins', 'Launch workflows & run history', 'Confirmed applications', 'Controller bindings',
  'Stream Deck configuration'];

function modesWith(mode, labels) {
  const categories = labels.map((label, i) => ({ id: `cat_${i}`, label, may_contain_user_text: i < 8 }));
  return { categories, handlers: { 'GET /privacy/modes': { ok: true, status: 200, body: { ok: true, modes: { [mode]: { categories } } } } } };
}

test('blocker 3: clearing personal data shows every category label (the real 22) and binds them', async () => {
  const { categories, handlers } = modesWith('clear_personal_data', PERSONAL_DATA_LABELS);
  const { instance, dialog, calls } = makeBroker({ answers: [0], handlers });
  const result = await instance.wipePrivacy({ mode: 'clear_personal_data', wipeVoices: false });
  assert.equal(result.ok, true);
  const options = dialog.shown[0];
  assert.ok(approving(options));
  assertFits(options);
  for (const label of PERSONAL_DATA_LABELS) assert.ok(unwrapped(options).includes(label), `${label} is listed`);
  assert.ok(!/kinds? of data are deleted \(|and \d+ more/.test(unwrapped(options)), 'no counted remainder');
  const post = calls.find((c) => c.method === 'POST');
  assert.deepEqual(payloadOf(post.body.approval).bind, broker.privacyWipeBind('clear_personal_data', categories.map((c) => c.id), { wipeVoices: false }));
});

test('blocker 3: wipe labels that do not fit get Close only, never "N kinds of data"', async () => {
  const labels = Array.from({ length: 60 }, (_, i) => `A rather long category label number ${i}`);
  for (const mode of ['clear_conversations', 'clear_personal_data']) {
    const { handlers } = modesWith(mode, labels);
    const { instance, dialog, calls } = makeBroker({ answers: [0, 0], handlers });
    const result = await instance.wipePrivacy({ mode, wipeVoices: true });
    assert.equal(result.ok, false, mode);
    assert.equal(dialog.shown.length, 1);
    assert.ok(closeOnly(dialog.shown[0]), `${mode}: Close only`);
    assert.ok(!/kinds of data/.test(unwrapped(dialog.shown[0])));
    assert.ok(!calls.some((c) => c.method === 'POST'), `${mode}: nothing was forwarded`);
  }
});

test('blocker 3: the factory reset keeps "erase everything" and its typed phrase on any screen', async () => {
  const labels = Array.from({ length: 29 }, (_, i) => `Category label ${i}`);
  const { categories, handlers } = modesWith('factory_reset', labels);
  for (const budgets of [{}, { lines: 14 }]) {
    const { instance, dialog, calls } = makeBroker({ answers: [0], handlers, budgets });
    const result = await instance.factoryReset({ confirm: 'DELETE EVERYTHING', deleteDownloadedModels: false });
    assert.equal(result.ok, true, JSON.stringify(budgets));
    const options = dialog.shown[0];
    assert.ok(approving(options));
    assertFits(options, budgets.lines || MAX_DISPLAY_LINES);
    assert.match(options.message, /Erase everything/);
    assert.ok(/everything BetterFingers stores/.test(options.detail), options.detail);
    assert.ok(!/kinds of data/.test(unwrapped(options)), 'no category count stands in for the scope');
    const post = calls.find((c) => c.method === 'POST');
    assert.equal(post.body.confirm, 'DELETE EVERYTHING');
    assert.deepEqual(payloadOf(post.body.approval).bind, broker.privacyWipeBind('factory_reset', categories.map((c) => c.id), { deleteModels: false }));
  }
});
