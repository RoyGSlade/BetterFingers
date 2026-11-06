'use strict';

// The approval broker (Phase 0 items 1-3).
//
// "The human tap decides" used to be a rule nothing enforced: approving a
// workflow, teaching a persona an example, placing a draft into another app and
// confirming a command were all VALUES a caller put in a request, so a
// compromised renderer or anything holding the bearer token could approve its own
// proposal and the owner never saw a preview.
//
// This module is the only place in the product that can say yes. For each kind of
// approval it
//   1. fetches the thing to be approved from the BACKEND (never from the
//      renderer, which can only name it: a workflow id, a draft id, a persona
//      and its example text),
//   2. shows the person a NATIVE dialog (dialog.showMessageBox: the renderer
//      cannot click it, script it or style it) with the exact, complete content,
//      wrapped and with invisible characters made visible, never truncated, and
//      Cancel as the default button,
//   3. only if the person clicks Approve, signs a short-lived single-use ticket
//      with an HMAC key that exists only in this process and the backend's
//      (handed over by environment variable, never sent to a renderer), bound to
//      SHA-256 digests of the content that was shown, and
//   4. forwards the ticket to the backend, which verifies it against its own copy
//      before doing anything (backend/services/approvals.py).
//
// A renderer can ask for a dialog (a typed IPC channel); it can never obtain or
// forge a result. A token holder can call every backend route; without the key
// it cannot produce a ticket. The digest and framing code below is byte for byte
// the backend's (approvals.lines_digest), checked by a shared test vector.

const crypto = require('node:crypto');
const { freezeRunTargets, createRunAuthorizations, canonicalJson } = require('./runAuthorization');

const TICKET_VERSION = 1;
const TICKET_TTL_S = 60;
// A native dialog cannot scroll: content that does not fit is REFUSED, never
// clipped. (A person approving the first half of a thing has not approved it.)
// Both budgets are checked on the WHOLE dialog (message, body and note) inside
// confirm(), and anything over either one gets a dialog with NO approving button
// (round 3, item 7): it says the thing is too long to show in full and where to read
// it, and nothing is signed.
//
// The numbers were MEASURED, not assumed (round 3, item 7): the real GTK dialog, opened by
// app/tests/nativeDialogXvfb.test.mjs on a virtual display, re-wraps detail lines longer than
// about 75 characters at the default font, and 48 lines of 73 characters already made the
// dialog 1030 px tall, too tall for a 768 px laptop screen. So lines are wrapped here at 64
// characters (short enough that the toolkit does not wrap them again), and the whole dialog is
// held to 26 lines and 1600 characters, which the same test shows fits a 1366x768 and a
// 1280x720 screen with the buttons visible.
//
// Round 4, item 2 (Codex re-check 3, finding 2): the budget counted ARRAY ELEMENTS, and untrusted
// text with embedded newlines (a persona name with 45 of them) became a 46-line message and 52
// detail lines with an approving button. Now every dynamic field -- title, message, detail lines,
// persona names, labels -- goes through ONE display pipeline: a field that is meant to be one
// line (a name, a label, a title, the message) has its newlines and tabs drawn as visible
// symbols (⏎, ⇥) and every other control character as <U+XXXX>; multi-line content is split on
// its newlines into separate counted lines. The budget is then checked on what the toolkit will
// actually draw: every wrapped message line (counted twice: GTK draws the message larger and
// bold) plus every wrapped detail line.
const MAX_DISPLAY_LINES = 26;
const MAX_DISPLAY_CHARS = 1600;
const MAX_MESSAGE_CHARS = 120;
const WRAP_WIDTH = 64;
// The message is drawn in a larger bold font, so it wraps at fewer units and each of its lines
// costs two of the line budget.
const MESSAGE_WRAP_WIDTH = 48;
const MESSAGE_LINE_COST = 2;
const MAX_TITLE_WIDTH = 60;
const MIN_DIALOG_GAP_MS = 500;

const PURPOSE_WORKFLOW_APPROVE = 'workflow.approve';
const PURPOSE_PERSONA_EXAMPLE = 'persona.example';
const PURPOSE_DRAFT_SEND = 'draft.send';
const PURPOSE_PERSONA_FEW_SHOT = 'persona.few_shot';
const PURPOSE_PERSONA_LEARNED_DELETE = 'persona.learned_delete';
const PURPOSE_PERSONA_LEARNED_CLEAR = 'persona.learned_clear';
const PURPOSE_LEARNED_CLEAR_ALL = 'persona.learned_clear_all';
const PURPOSE_PERSONA_DELETE = 'persona.delete';
const PURPOSE_PRIVACY_WIPE = 'privacy.wipe';
// There is no MCP trust purpose (round 4, item 4): Phase 0 has no persistent MCP trust.

const WORKFLOW_ID = /^[A-Za-z0-9_-]{1,64}$/;
const SEND_ACTIONS = new Set(['copy_only', 'paste', 'type', 'open_chat_then_send']);
const MAX_EXAMPLE_CHARS = 4000;

// --- digests (identical bytes to backend/services/approvals.py) --------------

function linesDigest(lines) {
  const hash = crypto.createHash('sha256');
  for (const line of lines) {
    const data = Buffer.from(String(line), 'utf8');
    hash.update(`${data.length}:`, 'ascii');
    hash.update(data);
    hash.update('\n', 'ascii');
  }
  return hash.digest('hex');
}

function textDigest(text) {
  return linesDigest([String(text)]);
}

// Few-shot items as [raw, out] string pairs, normalised like the backend's
// approvals.few_shot_items (and llm_engine.normalize_persona): a non-object item is
// dropped and a missing or empty field is the empty string. ORDER AND DUPLICATES ARE
// KEPT: inference uses the first five in order, so reordering or repeating an example
// changes what the model sees (round 3, item 3).
function fewShotItems(value) {
  return (Array.isArray(value) ? value : [])
    .filter((item) => item && typeof item === 'object' && !Array.isArray(item))
    .map((item) => [item.raw ? String(item.raw) : '', item.out ? String(item.out) : '']);
}

// Digest of a COMPLETE ordered example list for one persona (identical bytes to
// approvals.few_shot_list_digest).
function fewShotListDigest(persona, items) {
  const lines = ['persona.few_shot.v2', String(persona), String(items.length)];
  for (const [raw, out] of items) lines.push(raw, out);
  return linesDigest(lines);
}

// A change is approved against the list it REPLACES and the list it RESULTS IN, so a
// change made by anything else between the dialog and the save voids the approval.
function personaFewShotBind(persona, before, after) {
  return { before_sha256: fewShotListDigest(persona, before), after_sha256: fewShotListDigest(persona, after) };
}

function learnedDeleteBind(persona, exampleId, before, after) {
  return { example_id: String(exampleId), ...personaFewShotBind(persona, before, after) };
}

// Learning one example (round 4, item 5): the example AND the complete learned list before and
// after, so an example the cap evicts is part of what was approved.
function learnedAddBind(persona, raw, out, before, after) {
  return { ...personaExampleBind(persona, raw, out), ...personaFewShotBind(persona, before, after) };
}

// Clearing one persona's learned examples / deleting a persona with its few-shot list (round 4,
// item 3): bound to the complete list removed.
function learnedClearBind(persona, before) {
  return { scope: 'persona_learned', ...personaFewShotBind(persona, before, []) };
}

function personaDeleteBind(persona, before) {
  return { scope: 'persona', ...personaFewShotBind(persona, before, []) };
}

// Every persona's learned list, sorted by name (identical bytes to
// approvals.learned_collection_digest). `personas` is [{ name, examples }] or [[name, pairs]].
function learnedCollectionDigest(personas) {
  const rows = (Array.isArray(personas) ? personas : []).map((row) => (Array.isArray(row)
    ? [String(row[0]), (row[1] || []).map(([r, o]) => [String(r), String(o)])]
    : [String(row && row.name), fewShotItems(row && row.examples)]));
  rows.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const lines = ['persona.learned.collection.v1', String(rows.length)];
  for (const [name, items] of rows) {
    lines.push(name, String(items.length));
    for (const [raw, out] of items) lines.push(raw, out);
  }
  return linesDigest(lines);
}

function learnedClearAllBind(collectionSha256) {
  return { scope: 'all_personas', collection_sha256: String(collectionSha256) };
}

// A privacy wipe or factory reset: its mode, the exact categories it deletes (registry order)
// and its options (identical to approvals.privacy_wipe_bind).
function privacyWipeBind(mode, categoryIds, { wipeVoices = false, deleteModels = false } = {}) {
  const ids = (categoryIds || []).map(String);
  return {
    mode: String(mode),
    scope_sha256: linesDigest(['privacy.wipe.v1', String(mode), String(ids.length), ...ids]),
    wipe_voices: wipeVoices ? '1' : '0',
    delete_models: deleteModels ? '1' : '0',
  };
}

// The ONE identity a persona name stands for (round 4, item 1), mirroring
// llm_engine._sanitize_persona_name: letters, digits, space, '_', '-', '.', trimmed. A name that
// is not already in this form is refused before anything is read, shown or signed.
function canonicalPersonaName(name) {
  const trimmed = String(name === undefined || name === null ? '' : name).trim();
  return Array.from(trimmed).filter((ch) => /^[\p{L}\p{N}]$/u.test(ch) || ch === ' ' || ch === '_' || ch === '-' || ch === '.')
    .join('').trim();
}

function draftSendBind(action, text, openChat) {
  return { action: String(action), text_sha256: textDigest(text), open_chat: openChat ? '1' : '0' };
}

function personaExampleBind(persona, raw, out) {
  return { example_sha256: linesDigest([String(persona), String(raw), String(out)]) };
}

// --- tickets -----------------------------------------------------------------

function b64url(buffer) {
  return Buffer.from(buffer).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function signTicket({
  secret, purpose, subject, bind, ttlSeconds = TICKET_TTL_S, nowMs = Date.now(), randomBytes = crypto.randomBytes,
}) {
  if (!Buffer.isBuffer(secret) || secret.length < 32) throw new Error('approval key unavailable');
  const issued = Math.floor(nowMs / 1000);
  const payload = {
    v: TICKET_VERSION,
    purpose,
    subject: String(subject),
    bind: Object.fromEntries(Object.entries(bind).map(([k, v]) => [String(k), String(v)])),
    nonce: randomBytes(16).toString('hex'),
    iat: issued,
    exp: issued + ttlSeconds,
  };
  const payloadB64 = b64url(Buffer.from(JSON.stringify(payload), 'utf8'));
  const sig = crypto.createHmac('sha256', secret).update(payloadB64, 'ascii').digest('hex');
  return { payload: payloadB64, sig };
}

// --- display -----------------------------------------------------------------

// Characters that can make shown text differ from what is acted on: zero-width
// and joiner characters, bidirectional controls, soft hyphen, BOM and other
// invisible or control code points. They are shown as <U+XXXX> so a hidden
// character in a URL or a draft is visible in the dialog instead of silently
// riding along (red-team: invisible-Unicode URL tricks).
// Written with explicit \u escapes so the source file itself contains no invisible
// characters (an editor or a diff could silently drop or reinterpret them).
const INVISIBLE = new RegExp(
  '[\\u0000-\\u0008\\u000B-\\u001F\\u007F-\\u009F\\u00AD\\u034F\\u061C\\u115F\\u1160\\u17B4\\u17B5'
  + '\\u180B-\\u180E\\u200B-\\u200F\\u2028-\\u202E\\u2060-\\u206F\\u3164\\uFE00-\\uFE0F\\uFEFF\\uFFA0'
  + '\\uFFF9-\\uFFFB]|\\uDB40[\\uDC00-\\uDFFF]',
  'g',
);

function makeVisible(text) {
  return String(text).replace(INVISIBLE, (match) => {
    const code = match.codePointAt(0).toString(16).toUpperCase().padStart(4, '0');
    return `<U+${code}>`;
  });
}

const NEWLINE_MARK = '\u23CE'; // ⏎
const TAB_MARK = '\u21E5'; // ⇥

// A field that is ONE line on screen (a name, a label, a title, the message): newlines and tabs
// become visible marks, every other invisible or control character <U+XXXX>. Nothing a caller
// passes can start a new line here.
function inline(value) {
  return makeVisible(String(value === undefined || value === null ? '' : value)
    .replace(/\r\n|\r|\n|\u2028|\u2029/g, NEWLINE_MARK)
    .replace(/\t/g, TAB_MARK));
}

// How wide a character is likely to RENDER, in units of an average lowercase letter, never
// under-estimated: the toolkit wraps by pixels, and a line it wraps again makes the dialog taller
// than what was budgeted (measured: 21 lines of 64 capital Ws made a 992 px dialog on a 720 px
// screen). East Asian wide and fullwidth characters and emoji take two units; wide capitals and
// symbols more than one.
const WIDE_RANGES = [
  [0x1100, 0x115F], [0x2E80, 0x303E], [0x3041, 0x33FF], [0x3400, 0x4DBF], [0x4E00, 0x9FFF],
  [0xA000, 0xA4CF], [0xAC00, 0xD7A3], [0xF900, 0xFAFF], [0xFE30, 0xFE4F], [0xFF00, 0xFF60],
  [0xFFE0, 0xFFE6], [0x1F000, 0x1FAFF], [0x20000, 0x3FFFD],
];
function charWidth(ch) {
  const code = ch.codePointAt(0);
  if (WIDE_RANGES.some(([lo, hi]) => code >= lo && code <= hi)) return 2;
  if (ch === 'W' || ch === 'M' || ch === '@' || ch === '%' || ch === '—') return 1.8;
  if ((ch >= 'A' && ch <= 'Z') || ch === 'm' || ch === 'w' || ch === '&' || ch === '#') return 1.5;
  if (code > 0x7F) return 1.5; // other scripts and symbols: assume wider than average
  return 1;
}

const CONTINUATION_WIDTH = 6;

function displayWidth(text) {
  let total = 0;
  for (const ch of Array.from(String(text))) total += charWidth(ch);
  return total;
}

// Wrap one logical line at `width` display units (see charWidth), preferring to break after a
// space. EVERY character is kept (the space stays at the end of the earlier piece); continuation
// pieces are marked so the wrap is visible as a wrap.
function wrapLine(line, width = WRAP_WIDTH) {
  const chars = Array.from(line);
  if (displayWidth(line) <= width) return [line];
  const pieces = [];
  let start = 0;
  while (start < chars.length) {
    // continuation pieces carry the visible "   \u21B3 " marker, so they get that much less room
    const room = pieces.length === 0 ? width : width - CONTINUATION_WIDTH;
    let used = 0;
    let end = start;
    while (end < chars.length && used + charWidth(chars[end]) <= room) { used += charWidth(chars[end]); end += 1; }
    if (end === start) end = start + 1; // a single character wider than the line still moves on
    if (end < chars.length) {
      for (let probe = end; probe > start + Math.floor((end - start) / 2); probe -= 1) {
        if (chars[probe - 1] === ' ') { end = probe; break; }
      }
    }
    pieces.push(chars.slice(start, end).join(''));
    start = end;
  }
  return pieces.map((piece, index) => (index === 0 ? piece : `   ↳ ${piece}`));
}

// The lines of multi-line `text` as shown: split on its newlines (each one a counted line),
// tabs and invisible characters made visible, long lines wrapped. Idempotent on its own output,
// so confirm() can pass every body line through it again. Returns an array of display lines.
function displayLines(text, width = WRAP_WIDTH) {
  const out = [];
  for (const raw of String(text).split(/\r\n|\n|\r|\u2028|\u2029/)) {
    out.push(...wrapLine(makeVisible(raw.replace(/\t/g, TAB_MARK)), width));
  }
  return out;
}

function fingerprint(digest) {
  return `${digest.slice(0, 8)} ${digest.slice(8, 16)}`;
}

function fingerprintOf(text) {
  return fingerprint(textDigest(text));
}

// The before/after diff a person reads for a few-shot change: the COMPLETE resulting
// list in order, each example marked, then every example the change removes. Two lines per
// example (more only when the text itself is long), so a useful list fits the dialog budget.
function fewShotDiffLines(before, after) {
  const key = ([raw, out]) => JSON.stringify([raw, out]);
  const unused = new Map();
  before.forEach((pair, index) => {
    const k = key(pair);
    if (!unused.has(k)) unused.set(k, []);
    unused.get(k).push(index);
  });
  const example = (label, [raw, out]) => [...displayLines(`${label} said: ${raw}`), ...displayLines(`   becomes: ${out}`)];
  const lines = [after.length === 0 ? 'After: NO examples.' : `After: ${after.length} example${after.length === 1 ? '' : 's'}, in the order used:`];
  after.forEach((pair, index) => {
    const slots = unused.get(key(pair));
    let mark = 'new';
    if (slots && slots.length) {
      const from = slots.shift();
      mark = from === index ? 'unchanged' : `moved from ${from + 1}`;
    } else if (before.some((other) => key(other) === key(pair))) {
      mark = 'extra copy';
    }
    lines.push(...example(`${index + 1}. [${mark}]`, pair));
  });
  const removed = [];
  for (const indexes of unused.values()) for (const index of indexes) removed.push([index, before[index]]);
  removed.sort((a, b) => a[0] - b[0]);
  if (removed.length) {
    lines.push(`Removed (${removed.length}):`);
    for (const [index, pair] of removed) lines.push(...example(`was ${index + 1}.`, pair));
  }
  return lines;
}

// Describe a registry entry's launch for the replace dialog.
function describeEntry(entry, planLaunch) {
  const lines = [
    ...displayLines(`Name: ${inline(entry.display_name || entry.id)}`),
    ...displayLines(`Start method: ${inline(entry.launch_method || '(none)')}`),
  ];
  let plan = null;
  try { plan = typeof planLaunch === 'function' ? planLaunch(entry) : null; } catch { plan = null; }
  if (plan && plan.ok) {
    lines.push(...displayLines(`Runs: ${inline(plan.command)}${plan.args && plan.args.length ? ` with arguments ${inline(JSON.stringify(plan.args))}` : ' with no arguments'}`));
  } else {
    lines.push('Runs: nothing (no usable start method)');
  }
  for (const field of ['executable', 'desktop_entry', 'flatpak_id', 'uri', 'steam_uri', 'profile_id']) {
    if (entry[field]) lines.push(...displayLines(`${field}: ${inline(entry[field])}`));
  }
  return lines;
}

// --- the broker ----------------------------------------------------------------

function fault(error, status = 0) {
  return { ok: false, status, error };
}

const TOO_LONG = 'That is too long to review in one window, so BetterFingers will not approve it. Shorten it and try again.';
const UNAVAILABLE = 'Approvals are not available right now. Nothing was changed.';

function createApprovalBroker({
  secret,
  dialog,
  getParentWindow = () => null,
  backend,
  listApplications = () => [],
  // applicationLauncher.planFor: entry => { ok, command, args }. Needed to freeze and
  // show the exact program a workflow run will start (round 3, item 2).
  planLaunch = null,
  // The run-authorization store shared with the workflow executor (runAuthorization.js).
  runAuthorizations = null,
  now = () => Date.now(),
  randomBytes = crypto.randomBytes,
  log = () => {},
  // Optional TIGHTER budgets, e.g. from the screen's work area (ipc.js). Never looser than the
  // measured defaults.
  getBudgets = () => ({}),
} = {}) {
  if (!dialog || typeof dialog.showMessageBox !== 'function') throw new Error('a dialog implementation is required');
  if (!backend || typeof backend.send !== 'function') throw new Error('a backend client is required');
  const runs = runAuthorizations || createRunAuthorizations({ now });

  let busy = false;
  let lastClosedAt = 0;

  function sign(purpose, subject, bind) {
    return signTicket({ secret, purpose, subject, bind, nowMs: now(), randomBytes });
  }

  // A missing/short key means approvals are unavailable; say so instead of throwing.
  function trySign(purpose, subject, bind) {
    try {
      return sign(purpose, subject, bind);
    } catch {
      return null;
    }
  }

  async function show(options) {
    const parent = getParentWindow();
    return parent && !(typeof parent.isDestroyed === 'function' && parent.isDestroyed())
      ? dialog.showMessageBox(parent, options)
      : dialog.showMessageBox(options);
  }

  // Does the whole dialog fit the budgets? Counted on exactly what would be shown.
  function budgets() {
    let wanted = {};
    try { wanted = getBudgets() || {}; } catch { wanted = {}; }
    const clamp = (value, max) => (Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), max) : max);
    return { lines: clamp(wanted.lines, MAX_DISPLAY_LINES), chars: clamp(wanted.chars, MAX_DISPLAY_CHARS) };
  }

  // The ONE display pipeline (round 4, item 2). Everything the toolkit will draw, as it will
  // draw it: the title and the message as single visible lines (the message then wrapped at its
  // own width), every body and note line split on its newlines, made visible and wrapped.
  function layout({ title, message, body, note = '' }) {
    const shownTitle = inline(title);
    const messageLines = wrapLine(inline(message), MESSAGE_WRAP_WIDTH);
    const lines = [...(Array.isArray(body) ? body : [body]), ...(note ? ['', ...displayLines(note)] : [])]
      .flatMap((line) => displayLines(String(line)));
    return { title: shownTitle, messageLines, lines };
  }

  // Does the whole dialog fit? Counted on exactly what would be drawn: each message line costs
  // MESSAGE_LINE_COST lines, each detail line one, and every line must already be within its width.
  function fitsLayout({ title, messageLines, lines }) {
    const budget = budgets();
    if (displayWidth(title) > MAX_TITLE_WIDTH) return false;
    const messageText = messageLines.join('');
    if (displayWidth(messageText) > MAX_MESSAGE_CHARS * 2) return false;
    if (messageLines.some((line) => displayWidth(line) > MESSAGE_WRAP_WIDTH)) return false;
    if (messageLines.length * MESSAGE_LINE_COST + lines.length > budget.lines) return false;
    let chars = Array.from(messageText).length;
    for (const line of lines) {
      if (displayWidth(line) > WRAP_WIDTH) return false;
      chars += Array.from(String(line)).length + 1;
    }
    return chars <= budget.chars;
  }

  // For callers that can choose a shorter form (a list, or only its count) before asking.
  function fits(parts) {
    return fitsLayout(layout(parts));
  }

  // Show the native dialog; resolves approved:true ONLY when the person clicked the
  // approving button. Anything else (Cancel, Escape, closing the window, an error) is a no.
  // Content that does not fit gets a dialog with ONLY a Close button (round 3, item 7).
  async function confirm({
    title, message, body, approveLabel = 'Approve', note = '', defaultApprove = false, tooLongWhere = '', tooLongError = TOO_LONG,
  }) {
    if (busy) return { approved: false, error: 'Another approval is already waiting for you.' };
    if (now() - lastClosedAt < MIN_DIALOG_GAP_MS) {
      return { approved: false, error: 'Please wait a moment before asking again.' };
    }
    const shown = layout({ title, message, body, note });
    busy = true;
    try {
      if (!fitsLayout(shown)) {
        await show({
          type: 'warning',
          // Our own fixed title when the given one is itself the problem.
          title: displayWidth(shown.title) <= MAX_TITLE_WIDTH ? shown.title : 'BetterFingers',
          message: 'This is too long to show in full here, so it cannot be approved from this window.',
          detail: [
            'BetterFingers only asks for your approval when it can show you all of it, and this does not fit.',
            '',
            tooLongWhere || 'Read it in full in the BetterFingers window, shorten it, and try again.',
            '',
            'Nothing was approved and nothing was signed.',
          ].join('\n'),
          // ONE button. There is nothing to approve here, so there is no way to approve it.
          buttons: ['Close'],
          defaultId: 0,
          cancelId: 0,
          noLink: true,
        });
        return { approved: false, tooLong: true, error: tooLongError };
      }
      const result = await show({
        type: 'question',
        title: shown.title,
        message: shown.messageLines.join('\n'),
        detail: shown.lines.join('\n'),
        buttons: [approveLabel, 'Cancel'],
        // Cancel is the default EXCEPT when the person themselves just pressed the
        // send shortcut (defaultApprove): then Enter confirms. Anything a page or the
        // backend can start keeps Cancel as the default.
        defaultId: defaultApprove ? 0 : 1,
        cancelId: 1,
        noLink: true,
      });
      return { approved: Boolean(result) && result.response === 0 };
    } catch (error) {
      log(`[approval] dialog failed: ${error && error.name}`);
      return { approved: false, error: 'The approval window could not be shown.' };
    } finally {
      busy = false;
      lastClosedAt = now();
    }
  }

  function declined(result) {
    return fault((result && result.error) || 'You cancelled. Nothing was changed.');
  }

  const WHERE_WORKFLOW = 'Open the workflow on the Workflows page of the BetterFingers window to read every step, then make it shorter.';
  const WHERE_PERSONA = 'Open the persona in the persona editor of the BetterFingers window to review its examples, then change fewer at a time.';
  const WHERE_DRAFT = 'Open the draft in the review window to read it in full. Copy never needs a confirmation.';

  // --- workflow ---------------------------------------------------------------

  async function approveWorkflow(workflowId) {
    const id = typeof workflowId === 'string' ? workflowId.trim() : '';
    if (!WORKFLOW_ID.test(id)) return fault('That is not a workflow BetterFingers knows about.');

    const preview = await backend.send('POST', '/workflows/preview', {
      workflow_id: id,
      // The same context the run gate uses (workflowExecutor.js): what is approved
      // is exactly what will be compared at run time.
      context: { registry: listApplications() || [] },
    }, 5000);
    if (!preview || !preview.ok || !preview.body || typeof preview.body !== 'object') {
      return preview && preview.status ? preview : fault('BetterFingers could not reach its backend to review that workflow.');
    }
    const info = preview.body;
    if (info.ok !== true) {
      return {
        ok: false, status: 409,
        body: { detail: 'Some steps no longer point at anything BetterFingers can open, so this workflow cannot be approved.', refusals: info.refusals || [] },
      };
    }
    const lines = Array.isArray(info.preview_lines) ? info.preview_lines.map(String) : [];
    if (lines.length === 0) return fault('There is nothing to approve: the preview is empty.');
    // The backend's digests must be the digests of what we are about to show. This
    // also fails closed if the two sides ever disagree about the framing.
    if (linesDigest(lines) !== info.preview_sha256 || typeof info.steps_sha256 !== 'string' || typeof info.workflow_id !== 'string') {
      return fault('BetterFingers could not verify that preview. Nothing was approved.');
    }

    const shown = lines.flatMap((line) => displayLines(line));
    const decision = await confirm({
      title: 'Approve workflow',
      message: `Approve the workflow “${inline(String(info.name || info.workflow_id))}”?`,
      body: ['When it runs, it will do exactly this, in this order:', '', ...shown],
      note: `Fingerprint ${fingerprint(info.preview_sha256)}. Any change to these steps cancels the approval.`,
      tooLongWhere: WHERE_WORKFLOW,
    });
    if (!decision.approved) return declined(decision);

    const approval = trySign(PURPOSE_WORKFLOW_APPROVE, info.workflow_id, {
      preview_sha256: info.preview_sha256,
      steps_sha256: info.steps_sha256,
    });
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', '/workflows/approve', { workflow_id: info.workflow_id, preview: lines, approval }, 5000);
  }

  // --- running an approved workflow (round 2, item 5; round 3, items 1 and 2) -------------------
  //
  // POLICY. An approved workflow is approved ONCE; every RUN is a separate act and is confirmed
  // here, in a native dialog, whatever the workflow does and whoever asked. There is no
  // dialog-free path: not for a renderer, not for a "physical" trigger, not for a workflow that
  // only changes a setting. This FAILS CLOSED: if the backend cannot describe the run, if the
  // preview cannot be verified, if the gate would refuse it now (not approved, switched off,
  // changed), or if any target cannot be resolved, nothing is shown and nothing runs. A later
  // "enable" cannot rescue an earlier "not runnable" answer, because no authorization exists.
  //
  // What a click produces is a single-use run authorization (runAuthorization.js) bound to the
  // exact plan that was shown and to the launch targets resolved from the SAME registry snapshot
  // the preview was computed from: the program and its arguments, each link, each folder. The
  // executor runs only those, and only while the registry still holds exactly them.
  async function confirmWorkflowRun(workflowId) {
    const refuse = (error, reason, extra = {}) => ({ ok: false, confirmed: false, error, reason, ...extra });
    const id = typeof workflowId === 'string' ? workflowId.trim() : '';
    if (!WORKFLOW_ID.test(id)) return refuse('invalid_id', 'That is not a workflow BetterFingers knows about.');
    let registry;
    try {
      registry = JSON.parse(JSON.stringify(listApplications() || []));
    } catch {
      return refuse('registry_unavailable', 'BetterFingers could not read its application list, so nothing ran.');
    }
    const preview = await backend.send('POST', '/workflows/preview', { workflow_id: id, context: { registry } }, 5000);
    const info = preview && preview.ok && preview.status < 400 && preview.body && typeof preview.body === 'object' ? preview.body : null;
    if (!info) return refuse('preview_unavailable', 'BetterFingers could not check what that workflow would do, so it did not run.');
    if (info.ok !== true) {
      return refuse('not_runnable', 'Some steps no longer point at anything BetterFingers can open, so it did not run.', { refusals: Array.isArray(info.refusals) ? info.refusals : [] });
    }
    if (info.runnable !== true) {
      return refuse('not_runnable', 'That workflow is not approved, is switched off, or has changed since you approved it, so it did not run.');
    }
    const lines = Array.isArray(info.preview_lines) ? info.preview_lines.map(String) : [];
    if (lines.length === 0 || linesDigest(lines) !== info.preview_sha256 || info.workflow_id !== id || !Array.isArray(info.steps)) {
      return refuse('preview_unverified', 'BetterFingers could not verify what that workflow would do, so it did not run.');
    }
    const frozen = freezeRunTargets(info.steps, registry, { planLaunch });
    if (!frozen.ok) return refuse('targets_unresolved', `${frozen.reason} Nothing ran.`);

    const shown = [
      'It will do exactly this, in this order:', '', ...lines.flatMap((line) => displayLines(line)),
    ];
    if (frozen.lines.length) shown.push('', 'Exactly what it starts or opens:', ...frozen.lines.flatMap((line) => displayLines(line)));
    const decision = await confirm({
      title: 'Run workflow',
      message: `Run the workflow “${inline(String(info.name || id))}” now?`,
      body: shown,
      approveLabel: 'Run it',
      note: 'If you did not just ask for this run, choose Cancel. If an application changes before its step, the run stops.',
      tooLongWhere: WHERE_WORKFLOW,
    });
    if (decision.tooLong) return refuse('too_long', TOO_LONG);
    if (!decision.approved) return refuse('declined', (decision && decision.error) || 'You cancelled. Nothing was run.');
    let authorization;
    try {
      authorization = runs.issue({ workflowId: id, previewSha256: info.preview_sha256, steps: info.steps, targets: frozen.targets });
    } catch {
      return refuse('unavailable', 'BetterFingers could not prepare that run. Nothing ran.');
    }
    return { ok: true, confirmed: true, authorization };
  }

  // --- the application registry (round 3, item 2; round 4, item 6) ---------------------------------
  //
  // The registry is what a workflow may launch. REPLACING an entry changes what a workflow's id
  // points at, so it is shown here, before and after, and only a click lets main write it. Round 4
  // (Codex re-check 3, finding 7): removing an entry and then adding the same id again used to
  // skip that dialog, so REMOVING needs a dialog too, and adding an id that the registry's identity
  // history remembers, or that a saved workflow already names, is treated as a replacement.
  function referenceLines(references) {
    const names = (Array.isArray(references) ? references : []).map((ref) => inline(ref));
    if (!names.length) return [];
    return displayLines(`Workflows that name it (${names.length}): ${names.join(', ')}`);
  }

  async function confirmApplicationReplace({ before, after, references = [] } = {}) {
    if (!after || typeof after !== 'object') return { approved: false, error: 'Nothing to replace.' };
    const known = before && typeof before === 'object';
    const body = [
      known ? 'An application BetterFingers is allowed to start is about to change.'
        : 'This id was used before, or a saved workflow already names it.',
      'Workflows that use this id will start the NEW target.', '',
      ...(known ? ['Before:', ...describeEntry(before, planLaunch)] : ['Before: nothing is registered under this id.']), '',
      'After the change:', ...describeEntry(after, planLaunch),
      ...(references.length ? ['', ...referenceLines(references)] : []),
    ];
    return confirm({
      title: 'Change a confirmed application',
      message: `Change what “${inline(after.id)}” starts?`,
      body,
      approveLabel: 'Change it',
      note: 'If you did not just edit this application, choose Cancel.',
    });
  }

  async function confirmApplicationRemove({ entry, references = [] } = {}) {
    if (!entry || typeof entry !== 'object') return { approved: false, error: 'Nothing to remove.' };
    return confirm({
      title: 'Remove a confirmed application',
      message: `Remove “${inline(entry.display_name || entry.id)}” from the applications BetterFingers may start?`,
      body: [
        'This application is removed:', ...describeEntry(entry, planLaunch),
        ...(references.length ? ['', ...referenceLines(references), 'They will not run until it is added again.'] : []),
        '', 'Adding this id again later will show you the change before it is saved.',
      ],
      approveLabel: 'Remove it',
      note: 'If you did not just remove this application, choose Cancel.',
    });
  }

  // --- persona examples (round 3, item 3; round 4, items 1, 3 and 5) ---------------------------------

  // The persona name the page sent, if it is already canonical; otherwise a refusal naming the
  // canonical form. Nothing is read, shown or signed for an alias (round 4, item 1).
  function personaName(name) {
    if (typeof name !== 'string' || !name.trim() || name.length > 128) return { error: fault('Choose a persona first.') };
    const canonical = canonicalPersonaName(name);
    if (!canonical) return { error: fault('A persona name needs at least one letter or digit.') };
    if (canonical !== name) {
      return { error: fault(`That is not the persona’s saved name. Persona names use letters, digits, spaces, “_”, “-” and “.”; use “${canonical}”.`) };
    }
    return { name };
  }

  // An example as dialog lines: "What was said" and "What it should become".
  function exampleLines([raw, out]) {
    return ['What was said:', ...displayLines(raw), 'What it should become:', ...displayLines(out)];
  }

  // A complete example list as dialog lines, or only its count when the full list does not fit.
  function listOrCount(parts, items, describeCount) {
    const full = [...parts.body, ...items.flatMap(([raw, out], index) => [
      ...displayLines(`${index + 1}. said: ${raw}`), ...displayLines(`   becomes: ${out}`)])];
    if (fits({ ...parts, body: full })) return full;
    return [...parts.body, describeCount, 'The list is too long to show here; open the persona in BetterFingers to read it.'];
  }

  const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

  // Learning ONE example. Round 4, item 5 (Codex re-check 3, finding 6): at the cap the store
  // evicts the oldest example, which the dialog did not show and the ticket did not bind. The
  // backend now computes the COMPLETE resulting list (POST .../examples/preview); main checks it is
  // exactly "before, minus what is evicted, plus the new example", shows the new example and every
  // evicted one, and binds the ticket to both lists. The backend commits only that result.
  async function addPersonaExample({ persona, raw, out, timeoutMs } = {}) {
    const who = personaName(persona);
    if (who.error) return who.error;
    if (typeof raw !== 'string' || typeof out !== 'string' || !raw.trim() || !out.trim()
        || raw.length > MAX_EXAMPLE_CHARS || out.length > MAX_EXAMPLE_CHARS) {
      return fault('That example is empty or too long to learn.');
    }
    const route = `/personas/${encodeURIComponent(who.name)}/examples`;
    const preview = await backend.send('POST', `${route}/preview`, { raw, out }, 5000);
    const plan = preview && preview.ok && preview.status < 400 && preview.body && typeof preview.body === 'object' ? preview.body : null;
    const pairsOf = (list) => (Array.isArray(list) ? list : []).map((p) => (Array.isArray(p) ? [String(p[0]), String(p[1])] : null));
    const before = plan ? pairsOf(plan.before) : [];
    const after = plan ? pairsOf(plan.after) : [];
    const evicted = plan && Array.isArray(plan.evicted) ? fewShotItems(plan.evicted) : null;
    if (!plan || plan.persona !== who.name || before.includes(null) || after.includes(null) || !evicted) {
      return fault('BetterFingers could not work out what learning this example would change. Nothing was learned.');
    }
    const added = [raw.trim(), out.trim()];
    if (plan.duplicate === true) {
      if (canonicalJson(before) !== canonicalJson(after)) return fault('BetterFingers could not verify that change. Nothing was learned.');
      return backend.send('POST', route, { raw, out }, Number(timeoutMs) || 10000); // changes nothing
    }
    // The only result that may be signed: before, minus the evicted examples from the front, plus the new one.
    const expected = [...before.slice(evicted.length), added];
    const evictedOk = canonicalJson(before.slice(0, evicted.length)) === canonicalJson(evicted);
    if (!evictedOk || canonicalJson(after) !== canonicalJson(expected)) {
      return fault('BetterFingers could not verify that change. Nothing was learned.');
    }
    const body = [`Persona: ${inline(who.name)}`, '', ...exampleLines(added)];
    if (evicted.length) {
      body.push('', `To make room, ${evicted.length === 1 ? 'this oldest example is removed' : `these ${evicted.length} oldest examples are removed`}:`);
      for (const pair of evicted) body.push(...exampleLines(pair));
    }
    body.push('', `It will then have ${plural(after.length, 'learned example')}.`);
    const decision = await confirm({
      title: 'Teach this persona',
      message: evicted.length ? `Let “${inline(who.name)}” learn this, and forget its oldest example?` : `Let “${inline(who.name)}” learn from this example?`,
      body,
      approveLabel: 'Learn it',
      note: 'It will shape how this persona rewrites your future dictation until you delete it.',
      tooLongWhere: WHERE_PERSONA,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PERSONA_EXAMPLE, who.name, learnedAddBind(who.name, raw, out, before, after));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', route, { raw, out, approval }, Number(timeoutMs) || 10000);
  }

  async function learnedList(name) {
    const listing = await backend.send('GET', `/personas/${encodeURIComponent(name)}/examples`, undefined, 5000);
    return listing && listing.ok && listing.status < 400 && listing.body && Array.isArray(listing.body.examples)
      ? listing.body.examples : null;
  }

  // Deleting ONE learned example (round 3, item 3). The list is read from the backend; the
  // ticket binds the example id and the complete list before and after.
  async function deleteLearnedExample({ persona, exampleId, timeoutMs } = {}) {
    const who = personaName(persona);
    if (who.error) return who.error;
    if (typeof exampleId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(exampleId)) return fault('That is not a learned example.');
    const examples = await learnedList(who.name);
    if (!examples) return fault('BetterFingers could not read that persona’s learned examples. Nothing was deleted.');
    const target = examples.find((entry) => entry && entry.id === exampleId);
    if (!target) return fault('That learned example is already gone.');
    const before = fewShotItems(examples);
    const after = fewShotItems(examples.filter((entry) => entry && entry.id !== exampleId));
    const decision = await confirm({
      title: 'Remove a learned example',
      message: `Remove this learned example from “${inline(who.name)}”?`,
      body: [
        `Persona: ${inline(who.name)}`, '', ...exampleLines(fewShotItems([target])[0]), '',
        `It will have ${plural(after.length, 'learned example')} left, in the same order.`,
      ],
      approveLabel: 'Remove it',
      note: 'This changes how the persona rewrites your future dictation.',
      tooLongWhere: WHERE_PERSONA,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PERSONA_LEARNED_DELETE, who.name, learnedDeleteBind(who.name, exampleId, before, after));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send(
      'DELETE', `/personas/${encodeURIComponent(who.name)}/examples/${encodeURIComponent(exampleId)}`,
      { approval }, Number(timeoutMs) || 10000,
    );
  }

  // Clearing EVERY learned example of one persona (round 4, item 3). Used to be `?confirm=true`
  // through the dashboard proxy; a page's flag is not a tap. Anything the page sends besides the
  // persona name is ignored.
  async function clearLearnedExamples({ persona, timeoutMs } = {}) {
    const who = personaName(persona);
    if (who.error) return who.error;
    const examples = await learnedList(who.name);
    if (!examples) return fault('BetterFingers could not read that persona’s learned examples. Nothing was deleted.');
    const before = fewShotItems(examples);
    if (!before.length) return { ok: true, status: 200, body: { ok: true, cleared: false } };
    const parts = {
      title: 'Clear learned examples',
      message: `Delete every learned example of “${inline(who.name)}”?`,
      body: [`Persona: ${inline(who.name)}`, `Scope: this persona only. All ${plural(before.length, 'learned example')} are deleted:`, ''],
      note: 'Other personas keep theirs. This changes how the persona rewrites your future dictation.',
    };
    const decision = await confirm({
      ...parts,
      body: listOrCount(parts, before, `(${plural(before.length, 'learned example')})`),
      approveLabel: 'Delete them',
      tooLongWhere: WHERE_PERSONA,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PERSONA_LEARNED_CLEAR, who.name, learnedClearBind(who.name, before));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('DELETE', `/personas/${encodeURIComponent(who.name)}/examples`, { approval }, Number(timeoutMs) || 10000);
  }

  // Clearing EVERY learned example of EVERY persona (round 4, item 3). The renderer's
  // `confirm: true` used to be the whole gate (backendProxy.clearPersonaLearning).
  async function clearAllLearning({ timeoutMs } = {}) {
    const preview = await backend.send('GET', '/privacy/persona-learning/preview', undefined, 5000);
    const personas = preview && preview.ok && preview.status < 400 && preview.body && Array.isArray(preview.body.personas)
      ? preview.body.personas.filter((row) => row && typeof row.name === 'string') : null;
    if (!personas) return fault('BetterFingers could not read the learned examples. Nothing was deleted.');
    const total = personas.reduce((sum, row) => sum + fewShotItems(row.examples).length, 0);
    const names = personas.map((row) => `${inline(row.name)} (${fewShotItems(row.examples).length})`);
    const decision = await confirm({
      title: 'Clear all learned examples',
      message: 'Delete every learned example of every persona?',
      body: [
        `Scope: all personas. ${plural(total, 'learned example')} across ${plural(personas.length, 'persona')} are deleted.`,
        ...(names.length ? displayLines(`Personas: ${names.join(', ')}`) : []),
      ],
      approveLabel: 'Delete them all',
      note: 'Your personas stay; only what they learned from your approved examples is deleted.',
      tooLongWhere: WHERE_PERSONA,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_LEARNED_CLEAR_ALL, 'all', learnedClearAllBind(learnedCollectionDigest(personas)));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('DELETE', '/privacy/persona-learning', { approval }, Number(timeoutMs) || 15000);
  }

  // Deleting a custom persona together with its few-shot list (round 4, item 3).
  async function deletePersona({ name, timeoutMs } = {}) {
    const who = personaName(name);
    if (who.error) return who.error;
    const current = await backend.send('GET', `/personas/${encodeURIComponent(who.name)}`, undefined, 5000);
    if (!current || !current.ok || current.status >= 400 || !current.body || typeof current.body !== 'object') {
      return fault('BetterFingers could not read that persona. Nothing was deleted.');
    }
    const before = fewShotItems(current.body.few_shot);
    const parts = {
      title: 'Delete a persona',
      message: `Delete the persona “${inline(who.name)}”?`,
      body: [
        `Persona: ${inline(who.name)}`,
        'Scope: this persona, with its prompt and settings,',
        `and its ${plural(before.length, 'example')}${before.length ? ':' : '.'}`,
        ...(before.length ? [''] : []),
      ],
      note: 'Profiles that use it switch to True Janitor.',
    };
    const decision = await confirm({
      ...parts,
      body: before.length ? listOrCount(parts, before, `(${plural(before.length, 'example')})`) : parts.body,
      approveLabel: 'Delete it',
      tooLongWhere: WHERE_PERSONA,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PERSONA_DELETE, who.name, personaDeleteBind(who.name, before));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('DELETE', `/personas/${encodeURIComponent(who.name)}`, { approval }, Number(timeoutMs) || 5000);
  }

  // --- privacy wipes and the factory reset (round 4, item 3) ---------------------------------------
  //
  // Every wipe mode deletes learned examples (the larger ones the personas too), so each is a
  // native dialog that lists what the mode deletes, read from the backend's own inventory
  // (GET /privacy/modes), and a ticket bound to the mode, that exact list and the options. The
  // factory reset keeps its typed phrase as well; the phrase alone is not a tap.
  const WIPE_MODES = new Set(['clear_conversations', 'clear_personal_data', 'factory_reset']);
  const WIPE_TITLES = {
    clear_conversations: 'Clear conversations',
    clear_personal_data: 'Clear personal data',
    factory_reset: 'Factory reset',
  };

  async function wipeScope(mode) {
    const modes = await backend.send('GET', '/privacy/modes', undefined, 5000);
    const entry = modes && modes.ok && modes.status < 400 && modes.body && modes.body.modes && modes.body.modes[mode];
    const categories = entry && Array.isArray(entry.categories) ? entry.categories.filter((c) => c && typeof c.id === 'string') : null;
    return categories && categories.length ? categories : null;
  }

  async function confirmWipe({ mode, categories, extra = [], approveLabel }) {
    return confirm({
      title: WIPE_TITLES[mode],
      message: mode === 'factory_reset' ? 'Erase everything BetterFingers stores on this computer?' : 'Delete this data now?',
      body: [
        `Scope: ${plural(categories.length, 'kind')} of data are deleted:`,
        ...displayLines(categories.map((c) => inline(c.label || c.id)).join(', ')),
        ...extra,
      ],
      approveLabel,
      note: 'This cannot be undone. If you did not just ask for this, choose Cancel.',
      tooLongWhere: 'Read the full list on the Privacy page of the BetterFingers window.',
    });
  }

  async function wipePrivacy({ mode, wipeVoices, timeoutMs } = {}) {
    const requested = typeof mode === 'string' && mode ? mode : 'clear_conversations';
    if (!WIPE_MODES.has(requested) || requested === 'factory_reset') return fault(`Unknown wipe mode ${inline(requested)}. Nothing was deleted.`);
    const categories = await wipeScope(requested);
    if (!categories) return fault('BetterFingers could not read what that would delete. Nothing was deleted.');
    const voices = Boolean(wipeVoices);
    const decision = await confirmWipe({
      mode: requested, categories, approveLabel: 'Delete it',
      extra: [voices ? 'Your cloned voice samples are deleted too.' : 'Your cloned voice samples are kept.'],
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PRIVACY_WIPE, requested, privacyWipeBind(requested, categories.map((c) => c.id), { wipeVoices: voices }));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', '/privacy/wipe', { wipe_voices: voices, mode: requested, approval }, Number(timeoutMs) || 120000);
  }

  async function factoryReset({ confirm: phrase, deleteDownloadedModels, timeoutMs } = {}) {
    if (typeof phrase !== 'string' || !phrase) return fault('factoryReset: confirmation phrase required');
    const categories = await wipeScope('factory_reset');
    if (!categories) return fault('BetterFingers could not read what a reset would delete. Nothing was deleted.');
    const models = Boolean(deleteDownloadedModels);
    const decision = await confirmWipe({
      mode: 'factory_reset', categories, approveLabel: 'Erase everything',
      extra: [models ? 'Downloaded models are deleted too.' : 'Downloaded models are kept.'],
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PRIVACY_WIPE, 'factory_reset', privacyWipeBind('factory_reset', categories.map((c) => c.id), { deleteModels: models }));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', '/privacy/factory-reset', { confirm: phrase, delete_downloaded_models: models, approval }, Number(timeoutMs) || 120000);
  }

  // --- voice requests (round 2, item 6; round 3, item 6) -----------------------------------------
  //
  // A spoken command can only REQUEST. Ambient audio, a video, or a replayed phrase can say "send it";
  // that is not a person's yes. The backend announces the request (a status event) and the native
  // dialog below is the only thing that can place the draft. There is no voice-CONFIRMATION flow:
  // the one command it served had no implementation, and a dialog that confirms nothing is surface
  // without a purpose. Voice-started dialogs keep Cancel as the default and are rate limited, so
  // repeated speech cannot grind a person into clicking.
  const VOICE_WINDOW_MS = 60000;
  const VOICE_MAX_PER_WINDOW = 3;
  let voiceRequests = [];
  function voiceBudgetAvailable() {
    const t = now();
    voiceRequests = voiceRequests.filter((at) => t - at < VOICE_WINDOW_MS);
    if (voiceRequests.length >= VOICE_MAX_PER_WINDOW) return false;
    voiceRequests.push(t);
    return true;
  }

  async function backendDraftText(draftId) {
    const listing = await backend.send('GET', '/drafts', undefined, 5000);
    const drafts = listing && listing.ok && listing.body && Array.isArray(listing.body.drafts) ? listing.body.drafts : null;
    const draft = drafts && drafts.find((entry) => entry && entry.id === draftId);
    return draft && typeof draft.final_text === 'string' ? draft.final_text : null;
  }

  // "Send it": the backend said a tap is needed. Show the draft the BACKEND holds and place it only on a click.
  async function presentVoiceTap({ draftId } = {}) {
    if (!Number.isInteger(draftId) || draftId <= 0) return fault('That spoken request did not name a draft.');
    if (!voiceBudgetAvailable()) return fault('Too many spoken requests in a row; ignoring this one.');
    const text = await backendDraftText(draftId);
    if (!text || !text.trim()) return fault('That draft is gone or empty. Nothing was sent.');
    const decision = await presentDraft({
      title: 'Place this draft',
      action: 'paste',
      openChat: false,
      text,
      approveLabel: 'Place it',
      note: 'You said “send it”. Voice alone never sends; only this button does.',
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_DRAFT_SEND, String(draftId), draftSendBind('paste', text, false));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', `/drafts/${draftId}/send`, { action: 'paste', open_chat: false, allow_resend: false, approval }, 120000);
  }

  // --- saving a persona (few-shot examples; round 2, item 4; round 3, item 3) -----------------------
  //
  // Few-shot examples steer every future rewrite, so ANY change to the ordered list a save
  // results in -- an addition, an edit, a removal, a reordering, a repeated copy, emptying it --
  // is shown in a native dialog as a before/after diff and signed against the complete list
  // before and after. A save that leaves the list exactly as stored goes straight through. The
  // stored list is read from the backend, never taken from the page, and what is sent is the
  // normalised list that was shown, so what is stored is exactly what was approved.
  async function savePersona({ name: requestedName, body, timeoutMs } = {}) {
    if (typeof requestedName !== 'string' || !requestedName.trim() || requestedName.length > 128) return fault('Choose a persona name first.');
    // Round 4, item 1: an alias ("Sam!ple") looked like a NEW persona with no examples, so the
    // no-change shortcut below skipped the dialog while the backend saved onto "Sample".
    const who = personaName(requestedName);
    if (who.error) return who.error;
    const { name } = who;
    if (!body || typeof body !== 'object' || Array.isArray(body)) return fault('That persona could not be saved.');
    const payload = { ...body, name };
    delete payload.approval; // a page cannot supply one
    const wantsExamples = Object.prototype.hasOwnProperty.call(payload, 'few_shot') && payload.few_shot !== null && payload.few_shot !== undefined;
    if (!wantsExamples) {
      delete payload.few_shot;
      return backend.send('POST', '/personas', payload, Number(timeoutMs) || 5000);
    }
    if (!Array.isArray(payload.few_shot) || payload.few_shot.length > 50) return fault('That persona has too many examples.');

    const current = await backend.send('GET', `/personas/${encodeURIComponent(name)}`, undefined, 5000);
    let storedList;
    if (current && current.ok && current.status < 400 && current.body && typeof current.body === 'object') {
      storedList = current.body.few_shot;
    } else if (current && current.status === 404) {
      storedList = []; // a new persona starts with no examples
    } else {
      return fault('BetterFingers could not read the stored persona, so nothing was saved.');
    }
    const before = fewShotItems(storedList);
    const after = fewShotItems(payload.few_shot);
    payload.few_shot = after.map(([raw, out]) => ({ raw, out }));
    if (canonicalJson(before) === canonicalJson(after)) return backend.send('POST', '/personas', payload, Number(timeoutMs) || 5000);

    if (after.some(([raw, out]) => raw.length > MAX_EXAMPLE_CHARS || out.length > MAX_EXAMPLE_CHARS)) {
      return fault('One of those examples is too long to learn.');
    }
    const decision = await confirm({
      title: 'Change this persona’s examples',
      message: `Change the examples “${inline(name)}” learns from?`,
      body: [`Persona: ${inline(name)} (now ${before.length} example${before.length === 1 ? '' : 's'})`, ...fewShotDiffLines(before, after)],
      approveLabel: 'Save the examples',
      note: 'The first examples shape your future dictation.',
      tooLongWhere: WHERE_PERSONA,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PERSONA_FEW_SHOT, name, personaFewShotBind(name, before, after));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', '/personas', { ...payload, approval }, Number(timeoutMs) || 5000);
  }

  // --- sending a draft -----------------------------------------------------------

  const ACTION_DESCRIPTIONS = {
    paste: 'Paste it into the application you are using',
    type: 'Type it into the application you are using',
    open_chat_then_send: 'Open the chat box and send it',
  };

  async function sendDraft({ id, action, openChat, allowResend, timeoutMs } = {}) {
    if (!Number.isInteger(id) || id <= 0) return fault('sendDraft: id must be a positive integer');
    const sendAction = action === undefined ? 'copy_only' : action;
    if (!SEND_ACTIONS.has(sendAction)) return fault(`sendDraft: unknown action ${String(action)}`);
    const payload = { action: sendAction, open_chat: Boolean(openChat), allow_resend: Boolean(allowResend) };

    // POLICY (SECURITY.md, "Clipboard"): copying to the clipboard places nothing in another
    // application and sends nothing outward, so it needs no dialog.
    if (sendAction === 'copy_only') {
      return backend.send('POST', `/drafts/${id}/send`, payload, timeoutMs);
    }

    const listing = await backend.send('GET', '/drafts', undefined, 5000);
    const drafts = listing && listing.ok && listing.body && Array.isArray(listing.body.drafts) ? listing.body.drafts : null;
    if (!drafts) return fault('BetterFingers could not read that draft. Nothing was sent.');
    const draft = drafts.find((entry) => entry && entry.id === id);
    if (!draft || typeof draft.final_text !== 'string' || !draft.final_text.trim()) {
      return fault('That draft is gone or empty. Nothing was sent.');
    }

    const decision = await presentDraft({
      title: 'Place this draft',
      action: sendAction,
      openChat: payload.open_chat,
      text: draft.final_text,
      approveLabel: sendAction === 'open_chat_then_send' ? 'Send it' : 'Place it',
    });
    if (!decision.approved) return declined(decision);

    const approval = trySign(PURPOSE_DRAFT_SEND, String(id), draftSendBind(sendAction, draft.final_text, payload.open_chat));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', `/drafts/${id}/send`, { ...payload, approval }, timeoutMs);
  }

  async function presentDraft({ title, action, openChat, text, approveLabel, defaultApprove = false, note = '' }) {
    const body = displayLines(text);
    const header = [
      `${ACTION_DESCRIPTIONS[action] || action}${openChat && action !== 'open_chat_then_send' ? ' (opening the chat first)' : ''}.`,
      'This is the exact text:', '',
    ];
    const facts = `Length ${Array.from(text).length} characters. Fingerprint ${fingerprintOf(text)}.`;
    return confirm({
      title,
      message: 'Place this text into another application?',
      body: [...header, ...body],
      approveLabel,
      defaultApprove,
      note: note ? `${note}\n${facts}` : facts,
      tooLongWhere: WHERE_DRAFT,
      tooLongError: 'This draft is too long to confirm in one window. Copy it instead (Copy never needs a confirmation).',
    });
  }

  // The "Primary action" button in the dashboard: the backend decides which draft
  // a press would place; we show it and ask.
  async function primaryActionFromUi({ timeoutMs } = {}) {
    const first = await backend.send('POST', '/runtime/primary-action', {}, timeoutMs || 120000);
    const body = first && first.body;
    const challenged = body && typeof body === 'object' && body.error === 'approval_required'
      && Number.isInteger(body.draft_id) && typeof body.final_text === 'string';
    if (!challenged) return first;

    const decision = await presentDraft({
      title: 'Place this draft',
      action: 'paste',
      openChat: false,
      text: body.final_text,
      approveLabel: 'Place it',
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_DRAFT_SEND, String(body.draft_id), draftSendBind('paste', body.final_text, false));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', '/runtime/primary-action', { approval }, timeoutMs || 120000);
  }

  // The send HOTKEY. It signs NOTHING by itself (round 2, item 2): a key press is
  // not evidence that anyone reviewed anything, and a renderer can choose the key.
  // A press opens the native dialog for the text MAIN fetched from the backend (the
  // renderer, or the review window, only names WHICH draft it believes is on display;
  // what it says it painted is never shown or signed), and Enter confirms because the
  // person has just pressed the shortcut. Cancel or Escape places nothing.
  async function placeFromHotkey({ displayedDraftId, reviewVisible = false, timeoutMs } = {}) {
    let draftId;
    let text;
    if (Number.isInteger(displayedDraftId) && displayedDraftId > 0) {
      const listing = await backend.send('GET', '/drafts', undefined, 5000);
      const drafts = listing && listing.ok && listing.body && Array.isArray(listing.body.drafts) ? listing.body.drafts : null;
      const draft = drafts && drafts.find((entry) => entry && entry.id === displayedDraftId);
      if (!draft || typeof draft.final_text !== 'string' || !draft.final_text.trim()) {
        return fault('That draft is gone or empty. Nothing was placed.');
      }
      draftId = displayedDraftId;
      text = draft.final_text;
    } else {
      const first = await backend.send('POST', '/runtime/primary-action', reviewVisible ? { review_visible: true } : {}, timeoutMs || 120000);
      const body = first && first.body;
      const challenged = body && typeof body === 'object' && body.error === 'approval_required'
        && Number.isInteger(body.draft_id) && typeof body.final_text === 'string';
      if (!challenged) return first;
      draftId = body.draft_id;
      text = body.final_text;
    }

    const decision = await presentDraft({
      title: 'Place this draft',
      action: 'paste',
      openChat: false,
      text,
      approveLabel: 'Place it',
      defaultApprove: true,
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_DRAFT_SEND, String(draftId), draftSendBind('paste', text, false));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send(
      'POST', '/runtime/primary-action',
      { displayed_draft_id: draftId, displayed_final_text: text, approval },
      timeoutMs || 120000,
    );
  }

  // The person asked to change the send shortcut (settings). A native dialog names
  // the new key; only a click applies it.
  async function confirmSendHotkeyChange(newKey) {
    const decision = await confirm({
      title: 'Change the send shortcut',
      message: `Make “${inline(String(newKey))}” the shortcut that places a draft?`,
      body: [
        'Pressing it will open a window showing the draft, and you confirm there.',
        'If you did not just change this setting, choose Cancel.',
      ],
      approveLabel: 'Change it',
    });
    return decision.approved === true;
  }

  return {
    approveWorkflow,
    confirmWorkflowRun,
    confirmApplicationReplace,
    confirmApplicationRemove,
    presentVoiceTap,
    addPersonaExample,
    deleteLearnedExample,
    clearLearnedExamples,
    clearAllLearning,
    deletePersona,
    wipePrivacy,
    factoryReset,
    savePersona,
    sendDraft,
    primaryActionFromUi,
    placeFromHotkey,
    confirmSendHotkeyChange,
  };
}

module.exports = {
  createApprovalBroker,
  signTicket,
  linesDigest,
  textDigest,
  draftSendBind,
  personaExampleBind,
  personaFewShotBind,
  learnedDeleteBind,
  learnedAddBind,
  learnedClearBind,
  personaDeleteBind,
  learnedCollectionDigest,
  learnedClearAllBind,
  privacyWipeBind,
  canonicalPersonaName,
  inline,
  fewShotItems,
  fewShotListDigest,
  fewShotDiffLines,
  makeVisible,
  wrapLine,
  displayLines,
  displayWidth,
  MAX_DISPLAY_LINES,
  MAX_DISPLAY_CHARS,
  MAX_MESSAGE_CHARS,
  WRAP_WIDTH,
  MESSAGE_WRAP_WIDTH,
  MESSAGE_LINE_COST,
  TICKET_TTL_S,
};
