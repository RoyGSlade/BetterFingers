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
  makeVisible, wrapLine, displayLines, MAX_DISPLAY_LINES, MAX_DISPLAY_CHARS, personaFewShotBind, fewShotItems,
  fewShotListDigest, learnedDeleteBind, mcpTrustBind,
} = broker;
const { resolveLaunchPlan } = require('../src/main/applicationLauncher.js');

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

function makeBroker({ answers = [0], handlers = {}, nowMs = 1_000_000, secret = SECRET, registry = [], runAuthorizations } = {}) {
  const dialog = fakeDialog(answers);
  const backend = fakeBackend(handlers);
  let clock = nowMs;
  const instance = createApprovalBroker({
    secret, dialog, backend, listApplications: () => registry, now: () => clock,
    getParentWindow: () => ({ isDestroyed: () => false }),
    planLaunch: resolveLaunchPlan, runAuthorizations,
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

// Round 3, item 7: content over the line OR character budget gets a dialog with no approving
// button at all; it says it is too long to show in full and where to read it. Nothing is signed.
function assertTooLongDialog(shown) {
  assert.equal(shown.length, 1, 'exactly one dialog');
  const { options } = shown[0];
  assert.deepEqual(options.buttons, ['Close'], 'no Approve button is offered');
  assert.equal(options.defaultId, 0);
  assert.equal(options.cancelId, 0);
  assert.match(options.message, /too long to show in full/);
  assert.match(options.detail, /Nothing was approved and nothing was signed/);
}

test('a preview that cannot be shown in full is refused, never clipped, and the dialog offers no Approve', async () => {
  const long = Array.from({ length: MAX_DISPLAY_LINES + 5 }, (_, i) => `${i + 1}. step`);
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: previewHandler(long) });
  const result = await instance.approveWorkflow('studio_setup');
  assert.equal(result.ok, false);
  assert.match(result.error, /too long to review/);
  assertTooLongDialog(dialog.shown);
  assert.match(dialog.shown[0].options.detail, /Workflows page/);
  assert.ok(!backend.calls.some((call) => call.path === '/workflows/approve'));
});

test('the character budget is enforced too: few lines, too many characters, no Approve', async () => {
  // 45 wrapped lines of ~96 characters each is under the line budget and over the character one.
  const line = `1. ${'x'.repeat(90)} ${'y'.repeat(90)} ${'z'.repeat(90)} ${'w'.repeat(90)} ${'v'.repeat(90)}`;
  const lines = Array.from({ length: 9 }, (_, i) => line.replace(/^1/, String(i + 1)));
  const shownLines = lines.flatMap((l) => displayLines(l));
  assert.ok(shownLines.length < MAX_DISPLAY_LINES && shownLines.join('\n').length > MAX_DISPLAY_CHARS, 'the fixture tests the right budget');
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: previewHandler(lines) });
  assert.equal((await instance.approveWorkflow('studio_setup')).ok, false);
  assertTooLongDialog(dialog.shown);
  assert.ok(!backend.calls.some((call) => call.path === '/workflows/approve'));
});

test('a too-long message line is refused the same way', async () => {
  const { instance, dialog } = makeBroker({ answers: [0], handlers: previewHandler(PREVIEW_LINES, { name: 'N'.repeat(400) }) });
  assert.equal((await instance.approveWorkflow('studio_setup')).ok, false);
  assertTooLongDialog(dialog.shown);
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

// ---- voice commands (round 2, item 6): voice only REQUESTS, the dialog confirms ----------------------------

test('a spoken "send it" shows the backend\'s draft in a dialog and places it only on a click', async () => {
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: DRAFTS });
  const result = await instance.presentVoiceTap({ draftId: 7 });
  assert.equal(result.ok, true);
  const { options } = dialog.shown[0];
  assert.equal(options.defaultId, 1, 'ambient audio can start this dialog, so Cancel is the default');
  assert.ok(options.detail.includes('The final text.'));
  const post = backend.calls.find((c) => c.method === 'POST');
  assert.equal(post.path, '/drafts/7/send');
  verifyTicket(post.body.approval, { purpose: 'draft.send', subject: '7', bind: draftSendBind('paste', 'The final text.', false) });
});

test('declining a spoken send places nothing and signs nothing', async () => {
  for (const answer of [1, -1, undefined]) {
    const { instance, backend } = makeBroker({ answers: [answer], handlers: DRAFTS });
    assert.equal((await instance.presentVoiceTap({ draftId: 7 })).ok, false);
    assert.ok(!backend.calls.some((c) => c.method === 'POST'));
  }
});

test('a spoken send for a draft the backend does not have, or without a draft, shows nothing', async () => {
  for (const draftId of [99, null, undefined, 0, '7']) {
    const { instance, dialog } = makeBroker({ answers: [0], handlers: DRAFTS });
    assert.equal((await instance.presentVoiceTap({ draftId })).ok, false);
    assert.equal(dialog.shown.length, 0);
  }
});

test('there is no voice-confirmation flow: the broker cannot confirm a spoken command (round 3, item 6)', () => {
  const { instance } = makeBroker({ answers: [0] });
  assert.equal(instance.confirmVoiceCommand, undefined);
  assert.equal(broker.voiceConfirmBind, undefined);
  const source = readFileSync(new URL('../src/main/approvalBroker.js', import.meta.url), 'utf8');
  assert.ok(!source.includes("'voice.confirm'"), 'no voice.confirm purpose is signed anywhere');
});

test('repeated spoken requests are rate limited: only three dialogs a minute', async () => {
  const { instance, dialog, advance } = makeBroker({ answers: [1, 1, 1, 1, 1], handlers: DRAFTS });
  const results = [];
  for (let i = 0; i < 5; i += 1) {
    results.push(await instance.presentVoiceTap({ draftId: 7 }));
    advance(600); // past the minimum gap between dialogs, still inside the one-minute window
  }
  assert.equal(dialog.shown.length, 3);
  assert.match(results[3].error, /Too many spoken requests/);
  advance(61000);
  await instance.presentVoiceTap({ draftId: 7 });
  assert.equal(dialog.shown.length, 4, 'the budget refills');
});

test('voice has no way to approve by itself: a spoken send signs nothing without a dialog', async () => {
  for (const [method, args] of [['presentVoiceTap', { draftId: 7 }]]) {
    const { instance, backend } = makeBroker({ answers: [new Error('no display')], handlers: DRAFTS });
    const result = await instance[method](args);
    assert.equal(result.ok, false);
    assert.ok(!backend.calls.some((c) => c.method === 'POST'));
  }
});

// ---- running an approved workflow (round 2, item 5) -------------------------------------------

function runPreview(overrides = {}) {
  return { 'POST /workflows/preview': { ok: true, status: 200, body: previewBody(PREVIEW_LINES, { outward: true, runnable: true, ...overrides }) } };
}

const RUN_STEPS = [{ action: 'launch_app', app_id: 'obsidian' }, { action: 'activate_application_profile', profile_id: 'writing_app' }];
const OBSIDIAN = { id: 'obsidian', display_name: 'Obsidian', launch_method: 'flatpak', flatpak_id: 'md.obsidian.Obsidian', confirmed: true };
function runBroker({ answers = [0], overrides = {}, registry = [OBSIDIAN], runAuthorizations } = {}) {
  return makeBroker({
    answers, registry, runAuthorizations,
    handlers: { 'POST /workflows/preview': { ok: true, status: 200, body: previewBody(PREVIEW_LINES, { outward: true, runnable: true, steps: RUN_STEPS, ...overrides }) } },
  });
}

test('every run needs a fresh native confirmation that names the exact program, and yields an authorization', async () => {
  const { createRunAuthorizations } = require('../src/main/runAuthorization.js');
  const runAuthorizations = createRunAuthorizations();
  const { instance, dialog, backend } = runBroker({ runAuthorizations });
  const result = await instance.confirmWorkflowRun('studio_setup');
  assert.equal(result.ok, true);
  assert.equal(result.confirmed, true);
  assert.match(result.authorization, /^[0-9a-f]{48}$/);
  const { options } = dialog.shown[0];
  assert.equal(options.defaultId, 1, 'Cancel is the default');
  for (const line of PREVIEW_LINES) assert.ok(options.detail.includes(line));
  assert.ok(options.detail.includes('Starts the program flatpak with arguments ["run","md.obsidian.Obsidian"]'));
  assert.deepEqual(backend.calls[0].body.context.registry, [OBSIDIAN], 'the preview is computed from the registry snapshot that is frozen');
  const grant = runAuthorizations.consume(result.authorization, 'studio_setup');
  assert.equal(grant.targets[0].entry.flatpak_id, 'md.obsidian.Obsidian');
  assert.deepEqual(grant.targets[0].plan, { command: 'flatpak', args: ['run', 'md.obsidian.Obsidian'] });
  assert.ok(Object.isFrozen(grant.targets[0].entry));
  assert.equal(runAuthorizations.consume(result.authorization, 'studio_setup'), null, 'single use');
});

test('declining the run confirmation stops the run and issues nothing', async () => {
  for (const answer of [1, -1, undefined, new Error('no display')]) {
    const { instance } = runBroker({ answers: [answer] });
    const result = await instance.confirmWorkflowRun('studio_setup');
    assert.equal(result.ok, false);
    assert.equal(result.confirmed, false);
    assert.equal(result.error, 'declined');
    assert.ok(!('authorization' in result));
  }
});

test('a workflow with no outward action still asks (every run is confirmed)', async () => {
  const { instance, dialog } = runBroker({ answers: [0], overrides: { outward: false } });
  assert.equal((await instance.confirmWorkflowRun('studio_setup')).confirmed, true);
  assert.equal(dialog.shown.length, 1);
});

test('FAIL CLOSED: not runnable, invalid, unverifiable or unresolvable previews refuse with no dialog', async () => {
  const cases = [
    [{ runnable: false }, 'not_runnable'],
    [{ ok: false, refusals: [{ step: 1 }] }, 'not_runnable'],
    [{ preview_sha256: 'f'.repeat(64) }, 'preview_unverified'],
    [{ preview_lines: [] }, 'preview_unverified'],
    [{ workflow_id: 'other' }, 'preview_unverified'],
    [{ steps: undefined }, 'preview_unverified'],
    [{ steps: [{ action: 'launch_app', app_id: 'not_confirmed' }] }, 'targets_unresolved'],
  ];
  for (const [overrides, error] of cases) {
    const { instance, dialog } = runBroker({ overrides });
    const result = await instance.confirmWorkflowRun('studio_setup');
    assert.deepEqual([result.ok, result.confirmed, result.error], [false, false, error], JSON.stringify(overrides));
    assert.equal(dialog.shown.length, 0, JSON.stringify(overrides));
  }
  for (const reply of [{ ok: false, status: 0 }, { ok: true, status: 404, body: { detail: 'gone' } }, { ok: true, status: 200, body: 'x' }]) {
    const { instance, dialog } = makeBroker({ registry: [OBSIDIAN], handlers: { 'POST /workflows/preview': reply } });
    assert.equal((await instance.confirmWorkflowRun('studio_setup')).error, 'preview_unavailable');
    assert.equal(dialog.shown.length, 0);
  }
  const empty = makeBroker({ registry: [OBSIDIAN], handlers: { 'POST /workflows/preview': { ok: true, status: 200, body: {} } } });
  assert.equal((await empty.instance.confirmWorkflowRun('studio_setup')).ok, false);
  assert.equal(empty.dialog.shown.length, 0);
});

test('a run preview too long to show offers no Run button', async () => {
  const long = Array.from({ length: MAX_DISPLAY_LINES + 3 }, (_, i) => `${i + 1}. step`);
  const { instance, dialog } = makeBroker({
    answers: [0], registry: [OBSIDIAN],
    handlers: { 'POST /workflows/preview': { ok: true, status: 200, body: previewBody(long, { runnable: true, steps: RUN_STEPS }) } },
  });
  assert.equal((await instance.confirmWorkflowRun('studio_setup')).error, 'too_long');
  assertTooLongDialog(dialog.shown);
});

test('bad workflow ids never reach the backend', async () => {
  for (const id of ['', '../x', null, 5]) {
    const { instance, backend } = makeBroker();
    assert.equal((await instance.confirmWorkflowRun(id)).ok, false);
    assert.equal(backend.calls.length, 0);
  }
});

test('replacing a confirmed application shows before and after; only a click approves it', async () => {
  const before = { ...OBSIDIAN, launch_method: 'executable', executable: '/opt/obsidian/obsidian' };
  const after = { ...before, executable: '/tmp/evil' };
  for (const [answer, approved] of [[0, true], [1, false], [-1, false]]) {
    const { instance, dialog } = makeBroker({ answers: [answer] });
    assert.equal((await instance.confirmApplicationReplace({ before, after })).approved, approved);
    const { options } = dialog.shown[0];
    assert.equal(options.defaultId, 1);
    assert.ok(options.detail.indexOf('/opt/obsidian/obsidian') < options.detail.indexOf('/tmp/evil'));
  }
});

// ---- persona few-shot saves (round 2, item 4; round 3, item 3) ------------------------------

const A = { raw: 'hey whats up', out: 'Hey, what\u2019s up?' };
const B = { raw: 'ok see you', out: 'Okay, see you then.' };
const STORED = { 'GET /personas/Coach': { ok: true, status: 200, body: { few_shot: [A, B] } } };
const P = (list) => fewShotItems(list);

test('a persona save with no few-shot field goes straight through, with no dialog', async () => {
  const { instance, dialog, backend } = makeBroker({ handlers: STORED });
  await instance.savePersona({ name: 'Coach', body: { prompt: 'You are a coach.' } });
  assert.equal(dialog.shown.length, 0);
  assert.deepEqual(backend.calls.map((c) => `${c.method} ${c.path}`), ['POST /personas']);
});

test('only an exactly unchanged list skips the dialog', async () => {
  const { instance, dialog, backend } = makeBroker({ handlers: STORED });
  await instance.savePersona({ name: 'Coach', body: { prompt: 'p', few_shot: [A, B] } });
  assert.equal(dialog.shown.length, 0);
  assert.ok(!('approval' in backend.calls.find((c) => c.method === 'POST').body));
});

test('removal, emptying, reordering and duplication all need the dialog (round 3, item 3)', async () => {
  for (const after of [[A], [], [B, A], [A, A, B], [A, B, A]]) {
    const { instance, dialog, backend } = makeBroker({ answers: [1], handlers: STORED });
    assert.equal((await instance.savePersona({ name: 'Coach', body: { prompt: 'p', few_shot: after } })).ok, false);
    assert.equal(dialog.shown.length, 1, JSON.stringify(after));
    assert.ok(!backend.calls.some((c) => c.method === 'POST'), JSON.stringify(after));
  }
});

test('the dialog shows the complete resulting list in order and what is removed; the ticket binds before and after', async () => {
  const C = { raw: 'always', out: 'Always add a link.' };
  const after = [B, C, B];
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: STORED });
  const result = await instance.savePersona({ name: 'Coach', body: { prompt: 'p', few_shot: after } });
  assert.equal(result.ok, true);
  const { options } = dialog.shown[0];
  assert.equal(options.defaultId, 1);
  const detail = options.detail;
  assert.ok(detail.includes('has 3 examples, used in this order'));
  assert.ok(detail.includes('1. (moved from position 2)'));
  assert.ok(detail.includes('2. (new)') && detail.includes(C.out));
  assert.ok(detail.includes('3. (an extra copy)'));
  assert.ok(detail.includes('Removed by this change (1)') && detail.includes(A.out));
  const post = backend.calls.find((c) => c.method === 'POST');
  verifyTicket(post.body.approval, { purpose: 'persona.few_shot', subject: 'Coach', bind: personaFewShotBind('Coach', P([A, B]), P(after)) });
  assert.deepEqual(post.body.few_shot, after, 'what is sent is the list that was shown');
});

test('a new persona is compared against the empty list', async () => {
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: { 'GET /personas/Fresh': { ok: false, status: 404, body: { detail: 'nope' } } } });
  assert.equal((await instance.savePersona({ name: 'Fresh', body: { few_shot: [A] } })).ok, true);
  assert.equal(dialog.shown.length, 1);
  verifyTicket(backend.calls.find((c) => c.method === 'POST').body.approval, { purpose: 'persona.few_shot', subject: 'Fresh', bind: personaFewShotBind('Fresh', [], P([A])) });
});

test('an unreadable stored persona saves nothing (fail closed)', async () => {
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: { 'GET /personas/Coach': { ok: false, status: 0, error: 'down' } } });
  assert.equal((await instance.savePersona({ name: 'Coach', body: { few_shot: [A] } })).ok, false);
  assert.equal(dialog.shown.length, 0);
  assert.ok(!backend.calls.some((c) => c.method === 'POST'));
});

test('the stored examples come from the backend, and a page-supplied approval is discarded', async () => {
  const { instance, backend } = makeBroker({ answers: [1], handlers: STORED });
  await instance.savePersona({ name: 'Coach', body: { prompt: 'p', few_shot: [{ raw: 'x', out: 'y' }], approval: { payload: 'forged', sig: '0'.repeat(64) } } });
  assert.deepEqual(backend.calls.map((c) => `${c.method} ${c.path}`), ['GET /personas/Coach']);
});

test('declining a few-shot save saves nothing', async () => {
  for (const answer of [1, -1, undefined]) {
    const { instance, backend } = makeBroker({ answers: [answer], handlers: STORED });
    assert.equal((await instance.savePersona({ name: 'Coach', body: { few_shot: [{ raw: 'a', out: 'b' }] } })).ok, false);
    assert.ok(!backend.calls.some((c) => c.method === 'POST'));
  }
});

test('too many, too long or malformed few-shot saves are refused, and a list too long to show offers no Approve', async () => {
  const cases = [
    { name: '', body: { few_shot: [] } }, { name: 'Coach', body: null }, { name: 'Coach', body: { few_shot: 'x' } },
    { name: 'Coach', body: { few_shot: Array.from({ length: 51 }, () => ({ raw: 'a', out: 'b' })) } },
    { name: 'Coach', body: { few_shot: [{ raw: 'x'.repeat(4001), out: 'b' }] } },
  ];
  for (const args of cases) {
    const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: STORED });
    assert.equal((await instance.savePersona(args)).ok, false, JSON.stringify(args).slice(0, 60));
    assert.equal(dialog.shown.length, 0);
    assert.ok(!backend.calls.some((c) => c.method === 'POST'));
  }
  const tall = Array.from({ length: 12 }, (_, i) => ({ raw: `${'long '.repeat(60)}${i}`, out: 'b' }));
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: STORED });
  assert.equal((await instance.savePersona({ name: 'Coach', body: { few_shot: tall } })).ok, false);
  assertTooLongDialog(dialog.shown);
  assert.match(dialog.shown[0].options.detail, /persona editor/);
  assert.ok(!backend.calls.some((c) => c.method === 'POST'));
});

test('fewShotItems matches the backend\'s normalisation and keeps order and repeats', () => {
  assert.deepEqual(fewShotItems([{ raw: 'a', out: 'b' }, 'junk', null, { raw: 'c' }, { raw: 'a', out: 'b' }, { raw: null, out: 0 }]),
    [['a', 'b'], ['c', ''], ['a', 'b'], ['', '']]);
  assert.deepEqual(fewShotItems('nope'), []);
  assert.notEqual(fewShotListDigest('C', [['a', 'b'], ['c', 'd']]), fewShotListDigest('C', [['c', 'd'], ['a', 'b']]));
  assert.notEqual(fewShotListDigest('C', [['a', 'b']]), fewShotListDigest('C', [['a', 'b'], ['a', 'b']]));
});

test('deleting a learned example shows it, and the ticket binds its id and the list before and after', async () => {
  const examples = [{ id: 'ex_1', ...A }, { id: 'ex_2', ...B }];
  const handlers = { 'GET /personas/Coach/examples': { ok: true, status: 200, body: { examples } } };
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers });
  assert.equal((await instance.deleteLearnedExample({ persona: 'Coach', exampleId: 'ex_1' })).ok, true);
  assert.ok(dialog.shown[0].options.detail.includes(A.out));
  assert.equal(dialog.shown[0].options.defaultId, 1);
  const del = backend.calls.find((c) => c.method === 'DELETE');
  assert.equal(del.path, '/personas/Coach/examples/ex_1');
  verifyTicket(del.body.approval, { purpose: 'persona.learned_delete', subject: 'Coach', bind: learnedDeleteBind('Coach', 'ex_1', P([A, B]), P([B])) });
  for (const [answer, exampleId] of [[1, 'ex_1'], [0, 'missing'], [0, '../x']]) {
    const other = makeBroker({ answers: [answer], handlers });
    assert.equal((await other.instance.deleteLearnedExample({ persona: 'Coach', exampleId })).ok, false);
    assert.ok(!other.backend.calls.some((c) => c.method === 'DELETE'));
  }
});

test('trusting an MCP server shows its exact configuration and binds the config digest', async () => {
  const config = 'cd'.repeat(32);
  const handlers = { 'GET /mcp/servers/files/trust': { ok: true, status: 200, body: {
    name: 'files', command: '/usr/bin/files-mcp', args: ['--root', '/home/x'], env_keys: ['API_KEY'], network: false,
    config_sha256: config, weaker_confinement: 'none (no bubblewrap)', why_untrusted: 'bubblewrap is not installed.',
  } } };
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers });
  assert.equal((await instance.trustMcpServer({ name: 'files' })).ok, true);
  const { options } = dialog.shown[0];
  assert.equal(options.defaultId, 1);
  for (const part of ['/usr/bin/files-mcp', '["--root","/home/x"]', 'API_KEY', 'Network: off', 'bubblewrap is not installed']) assert.ok(options.detail.includes(part), part);
  const post = backend.calls.find((c) => c.method === 'POST');
  assert.equal(post.path, '/mcp/servers/files/trust');
  verifyTicket(post.body.approval, { purpose: 'mcp.trust', subject: 'files', bind: mcpTrustBind(config) });
  for (const [answer, name, body] of [[1, 'files', handlers], [0, '../x', handlers], [0, 'files', { 'GET /mcp/servers/files/trust': { ok: true, status: 200, body: { config_sha256: 'nope' } } }]]) {
    const other = makeBroker({ answers: [answer], handlers: body });
    assert.equal((await other.instance.trustMcpServer({ name })).ok, false);
    assert.ok(!other.backend.calls.some((c) => c.method === 'POST'));
  }
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
  assertTooLongDialog(dialog.shown);
  assert.match(dialog.shown[0].options.detail, /review window/);
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

// ---- the send hotkey (round 2, item 2) ------------------------------------------------------

test('a hotkey press shows the BACKEND\'s text for the draft the window names, and Enter confirms', async () => {
  const { instance, dialog, backend } = makeBroker({ answers: [0], handlers: DRAFTS });
  const result = await instance.placeFromHotkey({ displayedDraftId: 7, reviewVisible: true, displayedFinalText: 'EVIL text the review window claims' });
  assert.equal(result.ok, true);
  const { options } = dialog.shown[0];
  assert.equal(options.defaultId, 0, 'the person just pressed the shortcut: Enter confirms');
  assert.equal(options.cancelId, 1, 'Escape still cancels');
  assert.ok(options.detail.includes('The final text.'));
  assert.ok(!options.detail.includes('EVIL'));
  const post = backend.calls.find((c) => c.method === 'POST');
  assert.equal(post.path, '/runtime/primary-action');
  assert.equal(post.body.displayed_final_text, 'The final text.');
  verifyTicket(post.body.approval, { purpose: 'draft.send', subject: '7', bind: draftSendBind('paste', 'The final text.', false) });
});

test('a hotkey press with nothing displayed answers the backend\'s challenge through the dialog', async () => {
  const challenge = { ok: true, status: 200, body: { ok: false, error: 'approval_required', draft_id: 9, action: 'paste', final_text: 'queued text' } };
  let calls = 0;
  const { instance, dialog, backend } = makeBroker({
    answers: [0],
    handlers: { 'POST /runtime/primary-action': () => { calls += 1; return calls === 1 ? challenge : { ok: true, status: 200, body: { status: 'sent' } }; } },
  });
  const result = await instance.placeFromHotkey({ displayedDraftId: null });
  assert.equal(result.body.status, 'sent');
  assert.ok(dialog.shown[0].options.detail.includes('queued text'));
  verifyTicket(backend.calls[1].body.approval, { purpose: 'draft.send', subject: '9', bind: draftSendBind('paste', 'queued text', false) });
});

test('cancelling the hotkey dialog places nothing and signs nothing', async () => {
  for (const answer of [1, -1, undefined]) {
    const { instance, backend } = makeBroker({ answers: [answer], handlers: DRAFTS });
    assert.equal((await instance.placeFromHotkey({ displayedDraftId: 7 })).ok, false);
    assert.ok(!backend.calls.some((c) => c.method === 'POST'));
  }
});

test('a hotkey press for a draft the backend does not have shows no dialog', async () => {
  const { instance, dialog } = makeBroker({ answers: [0], handlers: DRAFTS });
  assert.equal((await instance.placeFromHotkey({ displayedDraftId: 99 })).ok, false);
  assert.equal(dialog.shown.length, 0);
});

test('only the hotkey dialog defaults to Approve; every other dialog still defaults to Cancel', async () => {
  const workflow = makeBroker({ answers: [1], handlers: previewHandler() });
  await workflow.instance.approveWorkflow('studio_setup');
  const draft = makeBroker({ answers: [1], handlers: DRAFTS });
  await draft.instance.sendDraft({ id: 7, action: 'paste' });
  const persona = makeBroker({ answers: [1] });
  await persona.instance.addPersonaExample({ persona: 'Coach', raw: 'a', out: 'b' });
  const change = makeBroker({ answers: [1] });
  await change.instance.confirmSendHotkeyChange('ctrl+alt+s');
  for (const ctx of [workflow, draft, persona, change]) assert.equal(ctx.dialog.shown[0].options.defaultId, 1);
});

test('the broker exposes no way to sign without a dialog', () => {
  const { instance } = makeBroker();
  assert.ok(!('signPhysicalPress' in instance));
  assert.deepEqual(Object.keys(instance).sort(), [
    'addPersonaExample', 'approveWorkflow', 'confirmApplicationReplace', 'confirmSendHotkeyChange', 'confirmWorkflowRun',
    'deleteLearnedExample', 'placeFromHotkey', 'presentVoiceTap', 'primaryActionFromUi', 'savePersona', 'sendDraft', 'trustMcpServer',
  ]);
});

test('changing the send shortcut shows a native dialog naming the key; only a click applies it', async () => {
  const yes = makeBroker({ answers: [0] });
  assert.equal(await yes.instance.confirmSendHotkeyChange('ctrl+alt+s'), true);
  assert.ok(yes.dialog.shown[0].options.message.includes('ctrl+alt+s'));
  for (const answer of [1, -1, undefined]) {
    assert.equal(await makeBroker({ answers: [answer] }).instance.confirmSendHotkeyChange('ctrl+alt+s'), false);
  }
});

// ---- wiring: nothing renderer-facing can mint or read an approval ---------------

const SRC = (rel) => readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8');

test('the preload never exposes the key, a signer or a ticket', () => {
  const preload = SRC('preload/preload.js');
  for (const forbidden of ['APPROVAL_KEY', 'getApprovalKey', 'signTicket', 'signPhysicalPress', 'placeFromHotkey', 'sendTrusted', 'createApprovalBroker']) {
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

test('the key is removed from main\'s own environment and handed to the sidecar only over a pipe', () => {
  const main = SRC('main/main.js');
  assert.match(main, /delete process\.env\.BETTERFINGERS_APPROVAL_KEY/);
  const sidecar = SRC('main/sidecar.js');
  assert.ok(!/BETTERFINGERS_APPROVAL_KEY:\s*approvalKey/.test(sidecar), 'never in the child environment');
  assert.ok(!/BETTERFINGERS_AUTH_TOKEN:\s*authToken/.test(sidecar), 'never in the child environment');
  assert.match(sidecar, /BETTERFINGERS_SECRETS_STDIN/);
});

test('round 2 item 3: the spawned backend\'s environment holds no key material; the secrets arrive on stdin', async () => {
  const { createSidecar } = require('../src/main/sidecar.js');
  const secretToken = 'tok-' + 'z9'.repeat(16);
  const secretKey = 'ab'.repeat(32);
  for (const platform of ['linux']) {
    let spawn = null;
    const written = [];
    const sidecar = createSidecar({
      platform, port: 8191, approvalKey: secretKey, authToken: secretToken, devCommand: 'stub',
      isTcpPortOpenImpl: async () => false,
      spawnProcess: (command, args, options) => {
        spawn = { command, args, options };
        return Object.assign(new (require('node:events').EventEmitter)(), {
          pid: 4242, killed: false, exitCode: null, signalCode: null,
          stdout: new (require('node:events').EventEmitter)(), stderr: new (require('node:events').EventEmitter)(),
          stdin: { on() {}, end: (data) => written.push(data) },
          kill() { return true; },
        });
      },
      waitForHealthyImpl: async () => ({ status: 'ok' }), readHealthImpl: async () => ({ status: 'ok' }),
      fetchImpl: async () => ({ ok: true, json: async () => ({ schema_version: 1, backend_version: 'test' }) }),
      setIntervalImpl: () => ({ unref() {} }), clearIntervalImpl: () => {}, readStat: () => null, stopGraceMs: 10,
      // Even a parent environment that carries them (an adopted launcher) must not forward them.
      parentEnv: { PATH: '/bin', BETTERFINGERS_AUTH_TOKEN: 'inherited-token', BETTERFINGERS_APPROVAL_KEY: 'inherited-key' },
    });
    await sidecar.start().catch(() => {});
    await sidecar.stop().catch(() => {});
    const env = JSON.stringify(spawn.options.env);
    assert.ok(!env.includes(secretToken) && !env.includes(secretKey), `${platform}: secret in the environment`);
    assert.ok(!env.includes('inherited-token') && !env.includes('inherited-key'), `${platform}: inherited secret forwarded`);
    assert.ok(!/AUTH_TOKEN|APPROVAL_KEY/.test(Object.keys(spawn.options.env).join(',')), `${platform}: credential variable names present`);
    assert.equal(spawn.options.env.BETTERFINGERS_SECRETS_STDIN, '1');
    assert.equal(spawn.options.stdio[0], 'pipe');
    assert.equal(written.length, 1);
    assert.deepEqual(JSON.parse(written[0]), { token: secretToken, approval_key: secretKey });
  }
});

test('with no credentials there is no hand-off and stdin stays closed', async () => {
  const { createSidecar } = require('../src/main/sidecar.js');
  let spawn = null;
  const sidecar = createSidecar({
    platform: 'linux', port: 8192, devCommand: 'stub',
    isTcpPortOpenImpl: async () => false,
    spawnProcess: (_c, _a, options) => { spawn = options; throw new Error('stop'); },
    waitForHealthyImpl: async () => ({}), readHealthImpl: async () => ({}), setIntervalImpl: () => ({ unref() {} }),
    clearIntervalImpl: () => {}, readStat: () => null, parentEnv: { PATH: '/bin' },
  });
  await sidecar.start().catch(() => {});
  assert.equal(spawn.stdio[0], 'ignore');
  assert.ok(!('BETTERFINGERS_SECRETS_STDIN' in spawn.env));
});
