// Phase 0 items 1-3: the approval broker. A renderer can ask for a dialog; it can
// never obtain a "yes". Run with: node --test app/tests/approvalBroker.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const broker = require('../src/main/approvalBroker.js');
const {
  createApprovalBroker, signTicket, linesDigest, textDigest, draftSendBind, personaExampleBind,
  makeVisible, wrapLine, displayLines, MAX_DISPLAY_LINES,
} = broker;

const SECRET = Buffer.from(Array.from({ length: 32 }, (_, i) => i));

// ---- helpers ------------------------------------------------------------------

function verifyTicket(ticket, { purpose, subject, bind, secret = SECRET }) {
  const expected = crypto.createHmac('sha256', secret).update(ticket.payload, 'ascii').digest('hex');
  assert.equal(ticket.sig, expected, 'signature must be the HMAC of the payload string');
  const payload = JSON.parse(Buffer.from(ticket.payload.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'));
  assert.equal(payload.v, 1);
  assert.equal(payload.purpose, purpose);
  assert.equal(payload.subject, subject);
  assert.deepEqual(payload.bind, bind);
  assert.ok(payload.exp - payload.iat <= 120);
  assert.match(payload.nonce, /^[0-9a-f]{32}$/);
  return payload;
}

function fakeDialog(answers) {
  const queue = [...answers];
  const dialog = {
    shown: [],
    async showMessageBox(...args) {
      const options = args.length === 2 ? args[1] : args[0];
      dialog.shown.push({ options, parent: args.length === 2 ? args[0] : null });
      const next = queue.length ? queue.shift() : 1;
      if (next instanceof Error) throw next;
      return { response: next };
    },
  };
  return dialog;
}

function fakeBackend(handlers = {}) {
  const calls = [];
  return {
    calls,
    async send(method, path, body, timeoutMs) {
      calls.push({ method, path, body, timeoutMs });
      const handler = handlers[`${method} ${path}`];
      if (!handler) return { ok: true, status: 200, body: {} };
      return typeof handler === 'function' ? handler(body) : handler;
    },
  };
}

function makeBroker({ answers = [0], handlers = {}, nowMs = 1_000_000, secret = SECRET, registry = [] } = {}) {
  const dialog = fakeDialog(answers);
  const backend = fakeBackend(handlers);
  let clock = nowMs;
  const instance = createApprovalBroker({
    secret, dialog, backend, listApplications: () => registry, now: () => clock,
    getParentWindow: () => ({ isDestroyed: () => false }),
  });
  return { instance, dialog, backend, advance: (ms) => { clock += ms; } };
}

const PREVIEW_LINES = ['1. Launch Obsidian (flatpak run md.obsidian.Obsidian)', '2. Switch the application profile to writing_app'];
function previewBody(lines = PREVIEW_LINES, overrides = {}) {
  return {
    ok: true, workflow_id: 'studio_setup', name: 'Studio setup', preview_lines: lines,
    preview_sha256: linesDigest(lines), steps_sha256: 'a'.repeat(64), refusals: [], ...overrides,
  };
}
function previewHandler(lines, overrides) {
  return { 'POST /workflows/preview': { ok: true, status: 200, body: previewBody(lines, overrides) } };
}

// ---- cross-language contract --------------------------------------------------

test('digests match the backend byte for byte (shared test vectors with tests/test_approvals.py)', () => {
  assert.equal(linesDigest(['Open Notepad', 'héllo ☃', '']), 'a155a24a76eab50aa86eb05acf8f13b0a0242b5fc2e198a52216e9f27b96e55b');
  assert.equal(draftSendBind('paste', 'Hello wörld', false).text_sha256,
    '6d1e91489f85c8e2029be2e905b54a773f23aa89325aef24c7ce7555f998a23d');
  assert.equal(personaExampleBind('Streamer', 'raw é', 'out').example_sha256,
    '4b54f4d0277810671e855eedd541b4a2e7899678ef13d303f6bf3a413ce4de73');
  assert.deepEqual(draftSendBind('paste', 'x', true), { action: 'paste', text_sha256: textDigest('x'), open_chat: '1' });
});

test('length framing: ["ab","c"] and ["a","bc"] hash differently', () => {
  assert.notEqual(linesDigest(['ab', 'c']), linesDigest(['a', 'bc']));
  assert.notEqual(linesDigest(['a\nb']), linesDigest(['a', 'b']));
});

test('a signed ticket has the documented shape and a verifiable signature', () => {
  const ticket = signTicket({ secret: SECRET, purpose: 'draft.send', subject: '7', bind: { a: 'b' }, nowMs: 5_000_000 });
  assert.deepEqual(Object.keys(ticket).sort(), ['payload', 'sig']);
  const payload = verifyTicket(ticket, { purpose: 'draft.send', subject: '7', bind: { a: 'b' } });
  assert.equal(payload.iat, 5000);
  assert.equal(payload.exp, 5060);
});

test('two tickets for the same thing never share a nonce', () => {
  const make = () => signTicket({ secret: SECRET, purpose: 'draft.send', subject: '1', bind: {} });
  assert.notEqual(JSON.parse(Buffer.from(make().payload, 'base64url')).nonce, JSON.parse(Buffer.from(make().payload, 'base64url')).nonce);
});

test('a missing or short key cannot sign', () => {
  for (const secret of [undefined, Buffer.alloc(0), Buffer.alloc(31), 'a'.repeat(64)]) {
    assert.throws(() => signTicket({ secret, purpose: 'x', subject: 'y', bind: {} }), /approval key unavailable/);
  }
});

// ---- display ------------------------------------------------------------------

test('wrapping keeps every character of every line (no silent truncation)', () => {
  const samples = [
    'x'.repeat(500), `${'word '.repeat(80)}tail`, 'é'.repeat(200), '😀'.repeat(150), 'a b'.repeat(100),
    '   leading spaces and a very long run '.repeat(8), '',
  ];
  for (const line of samples) {
    const pieces = wrapLine(line, 40);
    const rebuilt = pieces.map((piece, index) => (index === 0 ? piece : piece.replace(/^ {3}↳ /, ''))).join('');
    assert.equal(rebuilt, line);
    assert.ok(pieces.every((piece) => Array.from(piece).length <= 40 + 5));
  }
});

test('invisible and bidirectional characters are shown, not hidden', () => {
  const sneaky = 'https://good.example​/‮exe.txt\u0000';
  const shown = makeVisible(sneaky);
  assert.ok(shown.includes('<U+200B>') && shown.includes('<U+202E>') && shown.includes('<U+0000>'));
  assert.ok(!/[​‮\u0000]/.test(shown));
  assert.equal(makeVisible('line one\tTabbed'), 'line one\tTabbed', 'tabs are ordinary whitespace');
  assert.equal(makeVisible('café ☃ ✓'), 'café ☃ ✓', 'ordinary non-ASCII is untouched');
});

test('displayLines splits on newlines and keeps blank lines', () => {
  assert.deepEqual(displayLines('a\n\nb\r\nc'), ['a', '', 'b', 'c']);
});

// ---- workflow approval ----------------------------------------------------------

test('the dialog shows the complete preview, defaults to Cancel and cancels on dismissal', async () => {
  const { instance, dialog } = makeBroker({ answers: [1], handlers: previewHandler() });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  const { options } = dialog.shown[0];
  assert.equal(options.defaultId, 1);
  assert.equal(options.cancelId, 1);
  assert.deepEqual(options.buttons, ['Approve', 'Cancel']);
  assert.equal(options.noLink, true);
  for (const line of PREVIEW_LINES) assert.ok(options.detail.includes(line), line);
});

test('declining approves nothing: the backend is never asked to approve', async () => {
  for (const answer of [1, -1, 2, undefined, null, 'yes', true]) {
    const { instance, backend } = makeBroker({ answers: [answer], handlers: previewHandler() });
    const result = await instance.approveWorkflow('studio_setup');
    assert.equal(result.ok, false, String(answer));
    assert.ok(!backend.calls.some((call) => call.path === '/workflows/approve'), `answer ${String(answer)}`);
  }
});

test('a dialog that throws is a no', async () => {
  const { instance, backend } = makeBroker({ answers: [new Error('no display')], handlers: previewHandler() });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  assert.ok(!backend.calls.some((call) => call.path === '/workflows/approve'));
});

test('clicking Approve signs a ticket bound to the digests of what was shown and posts it', async () => {
  const { instance, backend, dialog } = makeBroker({
    answers: [0],
    handlers: { ...previewHandler(), 'POST /workflows/approve': { ok: true, status: 200, body: { ok: true } } },
  });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, true);
  assert.equal(dialog.shown.length, 1);
  const post = backend.calls.find((call) => call.path === '/workflows/approve');
  assert.deepEqual(post.body.preview, PREVIEW_LINES, 'the lines posted are the lines shown');
  assert.equal(post.body.workflow_id, 'studio_setup');
  verifyTicket(post.body.approval, {
    purpose: 'workflow.approve', subject: 'studio_setup',
    bind: { preview_sha256: linesDigest(PREVIEW_LINES), steps_sha256: 'a'.repeat(64) },
  });
});

test('the preview comes from the backend, never from the renderer', async () => {
  const { instance, backend } = makeBroker({ answers: [1], handlers: previewHandler() });
  // approveWorkflow takes ONE argument; anything else a renderer smuggles in is ignored.
  assert.equal(instance.approveWorkflow.length, 1);
  await instance.approveWorkflow('studio_setup', ['1. Do something harmless'], { preview_lines: ['x'] });
  const asked = backend.calls.find((call) => call.path === '/workflows/preview');
  assert.deepEqual(Object.keys(asked.body).sort(), ['context', 'workflow_id']);
});

test('the registry in the preview context is main\'s own, the same one the run gate uses', async () => {
  const registry = [{ id: 'obsidian', confirmed: true }];
  const { instance, backend } = makeBroker({ answers: [1], handlers: previewHandler(), registry });
  await instance.approveWorkflow('studio_setup');
  assert.deepEqual(backend.calls[0].body.context, { registry });
});

test('a preview whose digest does not match its lines is refused before any dialog', async () => {
  const { instance, dialog } = makeBroker({ handlers: previewHandler(PREVIEW_LINES, { preview_sha256: 'f'.repeat(64) }) });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  assert.equal(dialog.shown.length, 0);
});

test('a preview that cannot be shown in full is refused, never clipped', async () => {
  const long = Array.from({ length: MAX_DISPLAY_LINES + 5 }, (_, i) => `${i + 1}. step`);
  const { instance, dialog, backend } = makeBroker({ handlers: previewHandler(long) });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  assert.match(result.error, /too long to review/);
  assert.equal(dialog.shown.length, 0);
  assert.ok(!backend.calls.some((call) => call.path === '/workflows/approve'));
});

test('a long line is wrapped in the dialog, every character present', async () => {
  const line = `1. Launch Obsidian (${'/very/long/path/'.repeat(30)}obsidian)`;
  const { instance, dialog } = makeBroker({ answers: [1], handlers: previewHandler([line]) });
  await instance.approveWorkflow('studio_setup');
  const detail = dialog.shown[0].options.detail;
  const rebuilt = detail.split('\n').filter((l) => l.includes('/very/long/path/') || /^ {3}↳ /.test(l))
    .map((l, i) => (i === 0 ? l : l.replace(/^ {3}↳ /, ''))).join('');
  assert.ok(rebuilt.includes(line), 'the wrapped text rebuilds the original line');
  assert.ok(detail.includes('↳'), 'the wrap is marked');
});

test('refusals from the backend preview are reported, with no dialog', async () => {
  const { instance, dialog } = makeBroker({ handlers: previewHandler([], { ok: false, refusals: [{ code: 'unknown_application' }] }) });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  assert.equal(result.status, 409);
  assert.equal(dialog.shown.length, 0);
});

test('bad ids are refused without touching the backend', async () => {
  for (const id of ['', '../x', 'a b', 'x'.repeat(100), null, undefined, {}]) {
    const { instance, backend } = makeBroker();
    assert.equal((await instance.approveWorkflow(id)).ok, false);
    assert.equal(backend.calls.length, 0);
  }
});

test('hidden characters in a workflow preview are visible in the dialog', async () => {
  const lines = ['1. Open https://good.example​.evil.example/'];
  const { instance, dialog } = makeBroker({ answers: [1], handlers: previewHandler(lines) });
  await instance.approveWorkflow('studio_setup');
  assert.ok(dialog.shown[0].options.detail.includes('<U+200B>'));
});

test('with no key the click is not enough: nothing is posted', async () => {
  const { instance, backend } = makeBroker({ answers: [0], secret: Buffer.alloc(0), handlers: previewHandler() });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  assert.match(result.error, /not available/);
  assert.ok(!backend.calls.some((call) => call.path === '/workflows/approve'));
});

// ---- one dialog at a time -----------------------------------------------------

test('a second request while a dialog is open is refused, not stacked', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const dialog = {
    shown: 0,
    async showMessageBox() { dialog.shown += 1; await gate; return { response: 1 }; },
  };
  const backend = fakeBackend(previewHandler());
  const instance = createApprovalBroker({ secret: SECRET, dialog, backend, now: () => 1_000_000 });
  const first = instance.approveWorkflow('studio_setup');
  await new Promise((resolve) => setImmediate(resolve));
  const second = await instance.approveWorkflow('studio_setup');
  assert.equal(second.ok, false);
  assert.match(second.error, /already waiting/);
  release();
  await first;
  assert.equal(dialog.shown, 1);
});

test('a renderer looping on dialog requests is slowed down', async () => {
  const { instance, dialog, advance } = makeBroker({ answers: [1, 1, 1], handlers: previewHandler() });
  await instance.approveWorkflow('studio_setup');
  const immediate = await instance.approveWorkflow('studio_setup');
  assert.match(immediate.error, /wait a moment/);
  assert.equal(dialog.shown.length, 1);
  advance(600);
  await instance.approveWorkflow('studio_setup');
  assert.equal(dialog.shown.length, 2);
});

// ---- persona examples ---------------------------------------------------------

test('persona example: the dialog shows persona, raw and result text; the ticket binds all three', async () => {
  const { instance, dialog, backend } = makeBroker({ answers: [0] });
  const result = await instance.addPersonaExample({ persona: 'Coach', raw: 'hey whats up', out: 'Hey, what’s up?' });
  assert.equal(result.ok, true);
  const detail = dialog.shown[0].options.detail;
  assert.ok(detail.includes('hey whats up') && detail.includes('Hey, what’s up?') && detail.includes('Coach'));
  const post = backend.calls[0];
  assert.equal(post.path, '/personas/Coach/examples');
  assert.deepEqual(Object.keys(post.body).sort(), ['approval', 'out', 'raw'], 'no consent flag is sent');
  verifyTicket(post.body.approval, {
    purpose: 'persona.example', subject: 'Coach', bind: personaExampleBind('Coach', 'hey whats up', 'Hey, what’s up?'),
  });
});

test('persona example: declining, empty text and oversized text teach nothing', async () => {
  for (const [args, answers] of [
    [{ persona: 'Coach', raw: 'a', out: 'b' }, [1]],
    [{ persona: 'Coach', raw: '', out: 'b' }, [0]],
    [{ persona: '', raw: 'a', out: 'b' }, [0]],
    [{ persona: 'Coach', raw: 'x'.repeat(4001), out: 'b' }, [0]],
    [{ persona: 'Coach', raw: 'a', out: 5 }, [0]],
    [{ persona: 'Coach', raw: `${'long '.repeat(500)}`, out: `${'long '.repeat(500)}` }, [0]],
  ]) {
    const { instance, backend } = makeBroker({ answers });
    assert.equal((await instance.addPersonaExample(args)).ok, false, JSON.stringify(args).slice(0, 60));
    assert.equal(backend.calls.length, 0);
  }
});

test('persona example: a persona name with slashes cannot change the route', async () => {
  const { instance, backend } = makeBroker({ answers: [0] });
  await instance.addPersonaExample({ persona: '../workflows/approve', raw: 'a', out: 'b' });
  assert.equal(backend.calls[0].path, '/personas/..%2Fworkflows%2Fapprove/examples');
});

// ---- drafts -------------------------------------------------------------------

const DRAFTS = { 'GET /drafts': { ok: true, status: 200, body: { drafts: [{ id: 7, final_text: 'The final text.' }, { id: 8, final_text: 'Other.' }] } } };

test('copy-only needs no dialog and no ticket', async () => {
  const { instance, dialog, backend } = makeBroker({ handlers: DRAFTS });
  await instance.sendDraft({ id: 7, action: 'copy_only', timeoutMs: 1000 });
  assert.equal(dialog.shown.length, 0);
  assert.deepEqual(backend.calls.map((c) => c.path), ['/drafts/7/send']);
  assert.ok(!('approval' in backend.calls[0].body));
  const { instance: defaulted, backend: b2 } = makeBroker({ handlers: DRAFTS });
  await defaulted.sendDraft({ id: 7 });
  assert.equal(b2.calls[0].body.action, 'copy_only', 'the default is the safe action');
});

test('placing a draft shows its exact text and signs a ticket bound to that text, action and flag', async () => {
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: DRAFTS });
  const result = await instance.sendDraft({ id: 7, action: 'paste', openChat: false });
  assert.equal(result.ok, true);
  assert.ok(dialog.shown[0].options.detail.includes('The final text.'));
  const post = backend.calls.find((c) => c.method === 'POST');
  assert.equal(post.path, '/drafts/7/send');
  verifyTicket(post.body.approval, { purpose: 'draft.send', subject: '7', bind: draftSendBind('paste', 'The final text.', false) });
});

test('the text signed is the BACKEND\'s text for that id, not anything from the renderer', async () => {
  const { instance, backend } = makeBroker({ answers: [0], handlers: DRAFTS });
  await instance.sendDraft({ id: 8, action: 'type', finalText: 'Wire $500 now', text: 'Wire $500 now' });
  const post = backend.calls.find((c) => c.method === 'POST');
  verifyTicket(post.body.approval, { purpose: 'draft.send', subject: '8', bind: draftSendBind('type', 'Other.', false) });
});

test('declining a placement sends nothing', async () => {
  const { instance, backend } = makeBroker({ answers: [1], handlers: DRAFTS });
  assert.equal((await instance.sendDraft({ id: 7, action: 'paste' })).ok, false);
  assert.ok(!backend.calls.some((c) => c.method === 'POST'));
});

test('unknown drafts, unreadable drafts, bad ids and bad actions are refused', async () => {
  const cases = [
    [{ id: 99, action: 'paste' }, DRAFTS], [{ id: 7, action: 'paste' }, { 'GET /drafts': { ok: false, status: 0, error: 'x' } }],
    [{ id: 0, action: 'paste' }, DRAFTS], [{ id: '7', action: 'paste' }, DRAFTS], [{ id: 7, action: 'rm -rf' }, DRAFTS],
  ];
  for (const [args, handlers] of cases) {
    const { instance, backend, dialog } = makeBroker({ answers: [0], handlers });
    assert.equal((await instance.sendDraft(args)).ok, false, JSON.stringify(args));
    assert.equal(dialog.shown.length, 0);
    assert.ok(!backend.calls.some((c) => c.method === 'POST'));
  }
});

test('a draft too long to show in full cannot be placed from the button (copy is always available)', async () => {
  const body = `${'word '.repeat(60)}\n`.repeat(60);
  const { instance, dialog, backend } = makeBroker({
    answers: [0], handlers: { 'GET /drafts': { ok: true, status: 200, body: { drafts: [{ id: 7, final_text: body }] } } },
  });
  const result = await instance.sendDraft({ id: 7, action: 'paste' });
  assert.equal(result.ok, false);
  assert.match(result.error, /Copy it instead/);
  assert.equal(dialog.shown.length, 0);
  assert.ok(!backend.calls.some((c) => c.method === 'POST'));
});

test('the primary-action button: a challenge is shown and approved, anything else passes through', async () => {
  const challenge = { ok: true, status: 200, body: { ok: false, error: 'approval_required', draft_id: 7, action: 'paste', final_text: 'The final text.' } };
  let calls = 0;
  const { instance, dialog, backend } = makeBroker({
    answers: [0],
    handlers: { 'POST /runtime/primary-action': (body) => { calls += 1; return calls === 1 ? challenge : { ok: true, status: 200, body: { status: 'sent', saw: body } }; } },
  });
  const result = await instance.primaryActionFromUi({});
  assert.equal(result.body.status, 'sent');
  assert.ok(dialog.shown[0].options.detail.includes('The final text.'));
  verifyTicket(backend.calls[1].body.approval, { purpose: 'draft.send', subject: '7', bind: draftSendBind('paste', 'The final text.', false) });

  const plain = makeBroker({ handlers: { 'POST /runtime/primary-action': { ok: true, status: 200, body: { ok: true, text: 'read aloud' } } } });
  assert.deepEqual((await plain.instance.primaryActionFromUi({})).body, { ok: true, text: 'read aloud' });
  assert.equal(plain.dialog.shown.length, 0);
});

test('the primary-action challenge is only honoured when it is well formed', async () => {
  for (const body of [
    { error: 'approval_required' }, { error: 'approval_required', draft_id: '7', final_text: 'x' },
    { error: 'approval_required', draft_id: 7 }, { error: 'something_else', draft_id: 7, final_text: 'x' },
  ]) {
    const { instance, dialog } = makeBroker({ handlers: { 'POST /runtime/primary-action': { ok: true, status: 200, body } } });
    await instance.primaryActionFromUi({});
    assert.equal(dialog.shown.length, 0, JSON.stringify(body));
  }
});

test('the physical-press signer signs without a dialog and only for a well-formed press', () => {
  const { instance, dialog } = makeBroker();
  const ticket = instance.signPhysicalPress({ draftId: 7, text: 'The final text.' });
  verifyTicket(ticket, { purpose: 'draft.send', subject: '7', bind: draftSendBind('paste', 'The final text.', false) });
  assert.equal(dialog.shown.length, 0);
  for (const bad of [undefined, {}, { draftId: 0, text: 'x' }, { draftId: '7', text: 'x' }, { draftId: 7, text: 5 }]) {
    assert.equal(instance.signPhysicalPress(bad), null);
  }
});

// ---- wiring: nothing renderer-facing can mint or read an approval ---------------

const SRC = (rel) => readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8');

test('the preload never exposes the key, a signer or a ticket', () => {
  const preload = SRC('preload/preload.js');
  for (const forbidden of ['APPROVAL_KEY', 'getApprovalKey', 'signTicket', 'signPhysicalPress', 'sendTrusted', 'createApprovalBroker']) {
    assert.ok(!preload.includes(forbidden), `${forbidden} must not appear in the preload bridge`);
  }
  // The renderer-facing approval methods are fixed-shape invokes that return the backend's answer.
  assert.match(preload, /approveWorkflow: \(workflowId, timeoutMs\) =>\s+ipcRenderer\.invoke\('approvals:workflow'/);
});

test('every approval channel is registered through the sender-checked wrapper', () => {
  const ipc = SRC('main/ipc.js');
  for (const channel of ['approvals:workflow', 'approvals:persona-example', 'backend:send-draft', 'backend:primary-action']) {
    assert.ok(ipc.includes(`handleTrusted('${channel}'`), channel);
    assert.ok(!ipc.includes(`ipcMain.handle('${channel}'`), channel);
  }
});

test('no IPC handler returns the approval key or a ticket', () => {
  const ipc = SRC('main/ipc.js');
  const handlers = ipc.match(/handleTrusted\('[^']+'[\s\S]*?\n  \}\);/g) || [];
  assert.ok(handlers.length > 20);
  for (const handler of handlers) {
    assert.ok(!/getApprovalKey\(\)\s*[,;)]?\s*\}?\s*$/.test(handler.split('\n').slice(-3).join('\n')), handler.slice(0, 60));
    assert.ok(!/return\s+[^;]*(approvalKey|getApprovalKey|signPhysicalPress)/.test(handler), handler.slice(0, 80));
  }
  // The key leaves main.js only toward the sidecar and the broker.
  const main = SRC('main/main.js');
  assert.match(main, /createSidecar\(\{[\s\S]*?\n    approvalKey,/);
  assert.match(main, /getApprovalKey: \(\) => approvalKey,/);
  const otherUses = main.split('\n').filter((line) => /approvalKey/.test(line) && !/^\s*\/\//.test(line));
  assert.ok(!otherUses.some((line) => /send\(|console\.|log\(|JSON\.stringify/.test(line)), otherUses.join('\n'));
});

test('the key is removed from main\'s own environment and handed only to the sidecar', () => {
  const main = SRC('main/main.js');
  assert.match(main, /delete process\.env\.BETTERFINGERS_APPROVAL_KEY/);
  assert.match(SRC('main/sidecar.js'), /BETTERFINGERS_APPROVAL_KEY: approvalKey/);
});

test('sidecar passes the key to the backend it spawns, and omits it when there is none', async () => {
  const { createSidecar } = require('../src/main/sidecar.js');
  const seen = [];
  for (const approvalKey of ['ab'.repeat(32), '']) {
    let spawnEnv = null;
    const sidecar = createSidecar({
      platform: 'linux', port: 8191, approvalKey, authToken: 'tok', devCommand: 'stub',
      isTcpPortOpenImpl: async () => false,
      spawnProcess: (_cmd, _args, options) => { spawnEnv = options.env; throw new Error('stop here'); },
      waitForHealthyImpl: async () => ({ status: 'ok' }), readHealthImpl: async () => ({ status: 'ok' }),
      setIntervalImpl: () => ({ unref() {} }), clearIntervalImpl: () => {}, readStat: () => null,
      parentEnv: { PATH: '/bin' },
    });
    await sidecar.start().catch(() => {});
    seen.push(spawnEnv);
  }
  assert.equal(seen[0].BETTERFINGERS_APPROVAL_KEY, 'ab'.repeat(32));
  assert.equal(seen[0].BETTERFINGERS_AUTH_TOKEN, 'tok');
  assert.ok(!('BETTERFINGERS_APPROVAL_KEY' in seen[1]));
});
