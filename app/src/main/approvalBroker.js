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

const TICKET_VERSION = 1;
const TICKET_TTL_S = 60;
// A native dialog cannot scroll: content that does not fit is REFUSED, never
// clipped. (A person approving the first half of a thing has not approved it.)
const MAX_DISPLAY_LINES = 48;
const WRAP_WIDTH = 96;
const MIN_DIALOG_GAP_MS = 500;

const PURPOSE_WORKFLOW_APPROVE = 'workflow.approve';
const PURPOSE_PERSONA_EXAMPLE = 'persona.example';
const PURPOSE_DRAFT_SEND = 'draft.send';

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

// Wrap one logical line at `width` code points, preferring to break after a
// space. EVERY character is kept (the space stays at the end of the earlier
// piece); continuation pieces are marked so the wrap is visible as a wrap.
function wrapLine(line, width = WRAP_WIDTH) {
  const chars = Array.from(line);
  if (chars.length <= width) return [line];
  const pieces = [];
  let start = 0;
  while (chars.length - start > width) {
    let end = start + width;
    for (let probe = end; probe > start + Math.floor(width / 2); probe -= 1) {
      if (chars[probe - 1] === ' ') { end = probe; break; }
    }
    pieces.push(chars.slice(start, end).join(''));
    start = end;
  }
  pieces.push(chars.slice(start).join(''));
  return pieces.map((piece, index) => (index === 0 ? piece : `   ↳ ${piece}`));
}

// The lines of `text` (split on newlines) as shown: invisible characters made
// visible, long lines wrapped. Returns an array of display lines.
function displayLines(text, width = WRAP_WIDTH) {
  const out = [];
  for (const raw of String(text).split('\n')) {
    out.push(...wrapLine(makeVisible(raw.replace(/\r$/, '')), width));
  }
  return out;
}

function fingerprint(digest) {
  return `${digest.slice(0, 8)} ${digest.slice(8, 16)}`;
}

// --- the broker ----------------------------------------------------------------

function fault(error, status = 0) {
  return { ok: false, status, error };
}

function createApprovalBroker({
  secret,
  dialog,
  getParentWindow = () => null,
  backend,
  listApplications = () => [],
  now = () => Date.now(),
  randomBytes = crypto.randomBytes,
  log = () => {},
} = {}) {
  if (!dialog || typeof dialog.showMessageBox !== 'function') throw new Error('a dialog implementation is required');
  if (!backend || typeof backend.send !== 'function') throw new Error('a backend client is required');

  let busy = false;
  let lastClosedAt = 0;

  function sign(purpose, subject, bind) {
    return signTicket({ secret, purpose, subject, bind, nowMs: now(), randomBytes });
  }

  // A missing/short key means approvals are unavailable; say so instead of throwing.
  const UNAVAILABLE = 'Approvals are not available right now. Nothing was changed.';
  function trySign(purpose, subject, bind) {
    try {
      return sign(purpose, subject, bind);
    } catch {
      return null;
    }
  }

  // Show the native dialog; resolves true ONLY when the person clicked Approve.
  // Anything else (Cancel, Escape, closing the window, an error) is a no.
  async function confirm({ title, message, body, approveLabel = 'Approve', note = '' }) {
    if (busy) return { approved: false, error: 'Another approval is already waiting for you.' };
    if (now() - lastClosedAt < MIN_DIALOG_GAP_MS) {
      return { approved: false, error: 'Please wait a moment before asking again.' };
    }
    busy = true;
    try {
      const detail = [...body, ...(note ? ['', note] : [])].join('\n');
      const parent = getParentWindow();
      const options = {
        type: 'question',
        title,
        message,
        detail,
        buttons: [approveLabel, 'Cancel'],
        defaultId: 1,
        cancelId: 1,
        noLink: true,
      };
      const result = parent && !(typeof parent.isDestroyed === 'function' && parent.isDestroyed())
        ? await dialog.showMessageBox(parent, options)
        : await dialog.showMessageBox(options);
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

  // Fit-or-refuse: the dialog must be able to show ALL of it.
  function fits(lines) {
    return lines.length <= MAX_DISPLAY_LINES;
  }

  const TOO_LONG = 'That is too long to review in one window, so BetterFingers will not approve it. Shorten it and try again.';

  // --- workflow ---------------------------------------------------------------

  async function approveWorkflow(workflowId) {
    const id = String(workflowId || '').trim();
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
    if (!fits(shown)) return fault(TOO_LONG);

    const decision = await confirm({
      title: 'Approve workflow',
      message: `Approve the workflow “${makeVisible(String(info.name || info.workflow_id))}”?`,
      body: ['When it runs, BetterFingers will do exactly this, in this order:', '', ...shown],
      note: `Fingerprint ${fingerprint(info.preview_sha256)}. Any change to these steps cancels the approval.`,
    });
    if (!decision.approved) return declined(decision);

    const approval = trySign(PURPOSE_WORKFLOW_APPROVE, info.workflow_id, {
      preview_sha256: info.preview_sha256,
      steps_sha256: info.steps_sha256,
    });
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', '/workflows/approve', { workflow_id: info.workflow_id, preview: lines, approval }, 5000);
  }

  // --- persona learning --------------------------------------------------------

  async function addPersonaExample({ persona, raw, out, timeoutMs } = {}) {
    if (typeof persona !== 'string' || !persona.trim() || persona.length > 128) return fault('Choose a persona first.');
    if (typeof raw !== 'string' || typeof out !== 'string' || !raw.trim() || !out.trim()
        || raw.length > MAX_EXAMPLE_CHARS || out.length > MAX_EXAMPLE_CHARS) {
      return fault('That example is empty or too long to learn.');
    }
    const shown = [
      `Persona: ${makeVisible(persona)}`, '', 'What was said:', ...displayLines(raw), '',
      'What it should become:', ...displayLines(out),
    ];
    if (!fits(shown)) return fault(TOO_LONG);

    const decision = await confirm({
      title: 'Teach this persona',
      message: `Let “${makeVisible(persona)}” learn from this example?`,
      body: shown,
      approveLabel: 'Learn it',
      note: 'It will shape how this persona rewrites your future dictation until you delete it.',
    });
    if (!decision.approved) return declined(decision);

    const approval = trySign(PURPOSE_PERSONA_EXAMPLE, persona, personaExampleBind(persona, raw, out));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send(
      'POST', `/personas/${encodeURIComponent(persona)}/examples`, { raw, out, approval }, Number(timeoutMs) || 10000,
    );
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

    // Copying to the clipboard places nothing in another application.
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

  async function presentDraft({ title, action, openChat, text, approveLabel }) {
    const body = displayLines(text);
    const header = [
      `${ACTION_DESCRIPTIONS[action] || action}${openChat && action !== 'open_chat_then_send' ? ' (opening the chat first)' : ''}.`,
      'This is the exact text:', '',
    ];
    if (!fits([...header, ...body])) {
      return { approved: false, error: 'This draft is too long to confirm in one window. Copy it instead (Copy never needs a confirmation).' };
    }
    return confirm({
      title,
      message: 'Place this text into another application?',
      body: [...header, ...body],
      approveLabel,
      note: `Length ${Array.from(text).length} characters. Fingerprint ${fingerprint(textDigest(text))}.`,
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

  // The send HOTKEY. No dialog: the physical key press, observed by this process's
  // own global hook or shortcut registration, is the tap, and the text is the text
  // the review overlay is showing (or the draft the person already accepted).
  // Not reachable from any renderer: hotkeys.js is its only caller.
  function signPhysicalPress({ draftId, text, action = 'paste', openChat = false } = {}) {
    if (!Number.isInteger(draftId) || draftId <= 0 || typeof text !== 'string') return null;
    return trySign(PURPOSE_DRAFT_SEND, String(draftId), draftSendBind(action, text, openChat));
  }

  return {
    approveWorkflow,
    addPersonaExample,
    sendDraft,
    primaryActionFromUi,
    signPhysicalPress,
  };
}

module.exports = {
  createApprovalBroker,
  signTicket,
  linesDigest,
  textDigest,
  draftSendBind,
  personaExampleBind,
  makeVisible,
  wrapLine,
  displayLines,
  MAX_DISPLAY_LINES,
  WRAP_WIDTH,
  TICKET_TTL_S,
};
