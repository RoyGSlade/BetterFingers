// Round 4 (Codex re-check 3): findings 1, 2, 3 and 6 at the approval broker and the proxy.
// Run with: node --test app/tests/round4Approvals.test.mjs
//
// Finding 2: untrusted newlines bypassed the dialog's line budget. A persona name with 45
// newlines produced a 46-line message, 52 detail lines and an approving button, because the
// budget counted array elements, not the lines the toolkit would draw.
// Finding 1 (broker side): a non-canonical persona name ("Sam!ple") looked like a NEW persona
// with no examples, so the broker's no-change shortcut skipped the dialog.
// Finding 3: clearing learned examples, the global learning wipe, deleting a persona and the
// privacy wipes took a renderer boolean; now each is a native dialog bound to its scope.
// Finding 6: adding a learned example at the cap evicted another one, unseen.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const broker = require('../src/main/approvalBroker.js');
const {
  createApprovalBroker, linesDigest, fewShotItems, displayWidth, MAX_DISPLAY_LINES, WRAP_WIDTH,
} = broker;

const SECRET = Buffer.from(Array.from({ length: 32 }, (_, i) => i));
const NL45 = `Sam${'\n'.repeat(45)}ple`;

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
    async send(method, path, body) {
      calls.push({ method, path, body });
      const handler = handlers[`${method} ${path}`];
      if (!handler) return { ok: true, status: 200, body: {} };
      return typeof handler === 'function' ? handler(body) : handler;
    },
  };
  let clock = 1_000_000;
  const instance = createApprovalBroker({ secret: SECRET, dialog, backend, now: () => { clock += 1000; return clock; }, getBudgets: () => budgets });
  return { instance, dialog, calls };
}

// What the toolkit would actually draw: the message (bold, larger) counts double per line.
function drawnLines(options) {
  const message = String(options.message).split('\n');
  const detail = String(options.detail || '').split('\n');
  return { message, detail, total: message.length * 2 + detail.length };
}

function assertFits(options) {
  const { message, detail, total } = drawnLines(options);
  assert.ok(total <= MAX_DISPLAY_LINES, `the dialog draws ${total} lines (budget ${MAX_DISPLAY_LINES})`);
  for (const line of [...message, ...detail]) assert.ok(displayWidth(line) <= WRAP_WIDTH, `a ${displayWidth(line)}-wide line`);
  assert.ok(!/[\u0000-\u0008\u000B-\u001F\u007F]/.test(`${options.title}${options.message}${options.detail}`), 'no raw control characters');
}

function approving(options) {
  return Array.isArray(options.buttons) && options.buttons.length > 1;
}

// ---- finding 2: the line budget counts what is drawn ---------------------------------------

test('finding 2: a persona name with 45 newlines never reaches an approving dialog or the backend', async () => {
  const stored = { ok: true, status: 200, body: { few_shot: [{ raw: 'a', out: 'b' }] } };
  const { instance, dialog, calls } = makeBroker({
    answers: [0, 0],
    handlers: { [`GET /personas/${encodeURIComponent(NL45)}`]: stored },
  });
  const result = await instance.savePersona({ name: NL45, body: { prompt: 'p', few_shot: [] } });
  assert.equal(result.ok, false);
  assert.ok(!dialog.shown.some(approving), 'no approving button was offered');
  assert.ok(!calls.some((c) => c.method === 'POST'), 'nothing was forwarded');
});

test('finding 2: a workflow name with 45 newlines is drawn as one visible line, inside the budget', async () => {
  const lines = ['1. Launch Obsidian'];
  const { instance, dialog } = makeBroker({
    answers: [1],
    handlers: { 'POST /workflows/preview': { ok: true, status: 200, body: {
      ok: true, workflow_id: 'w', name: NL45, preview_lines: lines, preview_sha256: linesDigest(lines), steps_sha256: 'a'.repeat(64),
    } } },
  });
  await instance.approveWorkflow('w');
  assert.equal(dialog.shown.length, 1);
  const options = dialog.shown[0];
  assert.ok(options.message.includes('⏎'), 'the newlines are shown as ⏎');
  if (approving(options)) assertFits(options);
});

test('finding 2: an application display name with newlines is visible and counted', async () => {
  const before = { id: 'notes', display_name: NL45, launch_method: 'executable', executable: '/usr/bin/notes' };
  const after = { ...before, executable: '/usr/bin/other' };
  const { instance, dialog } = makeBroker({ answers: [1] });
  await instance.confirmApplicationReplace({ before, after });
  const options = dialog.shown[0];
  assert.ok(`${options.message}${options.detail}`.includes('⏎'));
  if (approving(options)) assertFits(options);
});

test('finding 2: content whose drawn lines exceed the budget gets only the Close button', async () => {
  const lines = Array.from({ length: 6 }, (_, i) => `${i}. ${'line\n'.repeat(8)}`);
  const { instance, dialog, calls } = makeBroker({
    answers: [0],
    handlers: { 'POST /workflows/preview': { ok: true, status: 200, body: {
      ok: true, workflow_id: 'w', name: 'W', preview_lines: lines, preview_sha256: linesDigest(lines), steps_sha256: 'a'.repeat(64),
    } } },
  });
  const result = await instance.approveWorkflow('w');
  assert.equal(result.ok, false);
  assert.deepEqual(dialog.shown[0].buttons, ['Close']);
  assert.ok(!calls.some((c) => c.path === '/workflows/approve'));
});

// ---- finding 1: canonical persona names at the broker ------------------------------------

test('finding 1: the broker refuses a non-canonical persona name before any lookup or dialog', async () => {
  for (const name of ['Sam!ple', ' Sample', 'Sample ', 'Sam\u200bple', "Sa'mple"]) {
    const { instance, dialog, calls } = makeBroker({ answers: [0] });
    const result = await instance.savePersona({ name, body: { prompt: 'p', few_shot: [] } });
    assert.equal(result.ok, false, name);
    assert.match(result.error, /Sample/, 'the canonical name is suggested');
    assert.equal(dialog.shown.length, 0);
    assert.equal(calls.length, 0);
  }
});

// ---- finding 3: destructive example transitions --------------------------------------------

const LEARNED = [{ id: 'e1', raw: 'hey', out: 'Hey.' }, { id: 'e2', raw: 'bye', out: 'Bye.' }];

test('finding 3: the dashboard proxy no longer reaches the collection or persona deletes', () => {
  const proxy = require('../src/main/backendProxy.js');
  assert.notEqual(proxy._validateRequest('DELETE', '/personas/Coach/examples'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/personas/Coach/examples?confirm=true'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/personas/Coach'), null);
  for (const name of ['clearPersonaLearning', 'wipePrivacyData', 'factoryReset']) {
    assert.equal(proxy[name], undefined, `backendProxy.${name} (a renderer-boolean gate) is gone`);
  }
});

test('finding 3: clearing one persona’s learned examples shows the scope and binds the list', async () => {
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'GET /personas/Coach/examples': { ok: true, status: 200, body: { examples: LEARNED } } },
  });
  const result = await instance.clearLearnedExamples({ persona: 'Coach' });
  assert.equal(result.ok, true);
  const shown = `${dialog.shown[0].message}\n${dialog.shown[0].detail}`;
  assert.ok(shown.includes('Coach') && shown.includes('2 learned examples'));
  assert.equal(dialog.shown[0].defaultId, 1, 'Cancel is the default');
  const del = calls.find((c) => c.method === 'DELETE');
  assert.equal(del.path, '/personas/Coach/examples');
  const payload = payloadOf(del.body.approval);
  assert.equal(payload.purpose, 'persona.learned_clear');
  assert.deepEqual(payload.bind, broker.learnedClearBind('Coach', fewShotItems(LEARNED)));
});

test('finding 3: declining a clear sends nothing, whatever the page says', async () => {
  const { instance, calls } = makeBroker({
    answers: [1], handlers: { 'GET /personas/Coach/examples': { ok: true, status: 200, body: { examples: LEARNED } } },
  });
  assert.equal((await instance.clearLearnedExamples({ persona: 'Coach', confirm: true })).ok, false);
  assert.ok(!calls.some((c) => c.method === 'DELETE'));
});

test('finding 3: the global learning wipe is a native dialog bound to the whole collection', async () => {
  const snapshot = { personas: [{ name: 'Coach', examples: LEARNED }, { name: 'Writer', examples: [{ id: 'w', raw: 'x', out: 'y' }] }] };
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'GET /privacy/persona-learning/preview': { ok: true, status: 200, body: snapshot } },
  });
  const result = await instance.clearAllLearning({ confirm: true });
  assert.equal(result.ok, true);
  const shown = dialog.shown[0].detail;
  assert.ok(shown.includes('3 learned examples') && shown.includes('Coach') && shown.includes('Writer'));
  const del = calls.find((c) => c.method === 'DELETE');
  assert.equal(del.path, '/privacy/persona-learning');
  const payload = payloadOf(del.body.approval);
  assert.equal(payload.purpose, 'persona.learned_clear_all');
  assert.deepEqual(payload.bind, broker.learnedClearAllBind(broker.learnedCollectionDigest(snapshot.personas)));
});

test('finding 3: deleting a custom persona shows its examples and binds its list', async () => {
  const few = [{ raw: 'a', out: 'b' }];
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'GET /personas/Custom': { ok: true, status: 200, body: { few_shot: few } } },
  });
  const result = await instance.deletePersona({ name: 'Custom' });
  assert.equal(result.ok, true);
  assert.ok(dialog.shown[0].detail.includes('1 example'));
  const del = calls.find((c) => c.method === 'DELETE');
  assert.equal(del.path, '/personas/Custom');
  const payload = payloadOf(del.body.approval);
  assert.equal(payload.purpose, 'persona.delete');
  assert.deepEqual(payload.bind, broker.personaDeleteBind('Custom', fewShotItems(few)));
});

test('finding 3: a privacy wipe shows what the mode deletes and binds mode, scope and options', async () => {
  const modes = { ok: true, modes: { clear_conversations: { categories: [
    { id: 'drafts', label: 'Drafts' }, { id: 'persona_learning', label: 'Learned persona examples' },
  ] } } };
  const { instance, dialog, calls } = makeBroker({ answers: [0], handlers: { 'GET /privacy/modes': { ok: true, status: 200, body: modes } } });
  const result = await instance.wipePrivacy({ mode: 'clear_conversations', wipeVoices: true });
  assert.equal(result.ok, true);
  assert.ok(dialog.shown[0].detail.includes('Learned persona examples'));
  const post = calls.find((c) => c.method === 'POST');
  assert.equal(post.path, '/privacy/wipe');
  assert.equal(post.body.wipe_voices, true);
  const payload = payloadOf(post.body.approval);
  assert.equal(payload.purpose, 'privacy.wipe');
  assert.deepEqual(payload.bind, broker.privacyWipeBind('clear_conversations', ['drafts', 'persona_learning'], { wipeVoices: true }));
});

// ---- finding 6: eviction is shown and bound -----------------------------------------------

test('finding 6: adding at the cap shows the example that will be removed and binds the complete result', async () => {
  const plan = {
    persona: 'Coach', duplicate: false,
    before: [['hey', 'Hey.'], ['bye', 'Bye.']], after: [['bye', 'Bye.'], ['new', 'New.']],
    evicted: [{ id: 'e1', raw: 'hey', out: 'Hey.' }],
  };
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'POST /personas/Coach/examples/preview': { ok: true, status: 200, body: plan } },
  });
  const result = await instance.addPersonaExample({ persona: 'Coach', raw: 'new', out: 'New.' });
  assert.equal(result.ok, true);
  const detail = dialog.shown[0].detail;
  assert.ok(/removed/i.test(detail) && detail.includes('Hey.'), 'the evicted example is shown');
  const post = calls.find((c) => c.path === '/personas/Coach/examples');
  const payload = payloadOf(post.body.approval);
  assert.equal(payload.purpose, 'persona.example');
  assert.deepEqual(payload.bind, broker.learnedAddBind('Coach', 'new', 'New.', plan.before, plan.after));
});

test('finding 6: a plan whose result is not "before, minus the evicted, plus the new one" is refused', async () => {
  const plan = {
    persona: 'Coach', duplicate: false,
    before: [['hey', 'Hey.'], ['bye', 'Bye.']], after: [['new', 'New.']],
    evicted: [{ id: 'e1', raw: 'hey', out: 'Hey.' }],
  };
  const { instance, dialog, calls } = makeBroker({
    answers: [0], handlers: { 'POST /personas/Coach/examples/preview': { ok: true, status: 200, body: plan } },
  });
  assert.equal((await instance.addPersonaExample({ persona: 'Coach', raw: 'new', out: 'New.' })).ok, false);
  assert.equal(dialog.shown.length, 0);
  assert.ok(!calls.some((c) => c.path === '/personas/Coach/examples'));
});

test('finding 3: a factory reset lists the whole scope when it fits and still offers approval on a short screen', async () => {
  const ids = ['raw_recordings', 'drafts', 'history_db', 'temp_audio', 'persona_learning', 'contacts', 'cloned_voices', 'personas',
    'dictionary', 'macros', 'user_profile', 'wake_models', 'audio_privacy_journal', 'mcp_config', 'graph_data', 'debug_log',
    'sidecar_raw_log', 'voice_presets', 'profiles', 'app_state', 'overlay_position', 'overlay_appearance', 'onboarding_consent',
    'app_profiles', 'launcher_workflows', 'application_registry', 'controller_bindings', 'stream_deck_config', 'model_runtime_metadata'];
  const categories = ids.map((id, i) => ({ id, label: `Category label ${id.replace(/_/g, ' ')}`, may_contain_user_text: i < 8 }));
  const handlers = { 'GET /privacy/modes': { ok: true, status: 200, body: { ok: true, modes: { factory_reset: { categories } } } } };
  for (const budgets of [{}, { lines: 14 }]) {
    const { instance, dialog, calls } = makeBroker({ answers: [0], handlers, budgets });
    const result = await instance.factoryReset({ confirm: 'DELETE EVERYTHING', deleteDownloadedModels: false });
    assert.equal(result.ok, true, JSON.stringify(budgets));
    const options = dialog.shown[0];
    assert.ok(approving(options), 'an approving dialog');
    assert.ok(options.detail.includes(`${ids.length} kinds of data`));
    const { total } = drawnLines(options);
    assert.ok(total <= (budgets.lines || MAX_DISPLAY_LINES), `${total} lines drawn`);
    const post = calls.find((c) => c.method === 'POST');
    assert.equal(post.path, '/privacy/factory-reset');
    assert.equal(post.body.confirm, 'DELETE EVERYTHING', 'the phrase is still forwarded');
    assert.deepEqual(payloadOf(post.body.approval).bind, broker.privacyWipeBind('factory_reset', ids, { deleteModels: false }));
  }
});
