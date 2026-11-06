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
const PURPOSE_PERSONA_FEW_SHOT = 'persona.few_shot';

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

// Few-shot items as [raw, out] string pairs, normalised exactly like the backend's
// approvals.few_shot_items, and the ones a save would ADD to what is stored.
function fewShotItems(value) {
  return (Array.isArray(value) ? value : [])
    .filter((item) => item && typeof item === 'object' && !Array.isArray(item))
    .map((item) => [String(item.raw ?? ''), String(item.out ?? '')]);
}

function addedFewShot(next, previous) {
  const existing = new Set(fewShotItems(previous).map(([raw, out]) => JSON.stringify([raw, out])));
  return fewShotItems(next).filter(([raw, out]) => !existing.has(JSON.stringify([raw, out])));
}

function personaFewShotBind(persona, added) {
  const lines = [String(persona)];
  for (const [raw, out] of added) lines.push(raw, out);
  return { few_shot_sha256: linesDigest(lines) };
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
  async function confirm({ title, message, body, approveLabel = 'Approve', note = '', defaultApprove = false }) {
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
        // Cancel is the default EXCEPT when the person themselves just pressed the
        // send shortcut (defaultApprove): then Enter confirms. Anything a page or the
        // backend can start keeps Cancel as the default.
        defaultId: defaultApprove ? 0 : 1,
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

  // --- running an approved workflow (round 2, item 5) ----------------------------------------
  //
  // POLICY. An approved workflow is approved ONCE, but a RUN is a separate act. A run that a
  // renderer asks for (workflows:execute) and that has any outward effect (launching or
  // raising a program, opening a link or a folder) needs a fresh native confirmation, so a
  // compromised page cannot replay an approved workflow whenever it likes. A PHYSICAL owner
  // trigger that main itself observes (a hotkey chord, a trigger phrase heard on the mic) is
  // the owner acting now, and runs without a dialog: ipc.js exposes that as
  // runWorkflowFromPhysicalTrigger, which no renderer channel can reach. Workflows that only
  // change BetterFingers' own settings or speak need no confirmation either way.
  async function confirmWorkflowRun(workflowId) {
    const id = typeof workflowId === 'string' ? workflowId.trim() : '';
    if (!WORKFLOW_ID.test(id)) return { ok: false, error: 'invalid_id', reason: 'That is not a workflow BetterFingers knows about.' };
    const preview = await backend.send('POST', '/workflows/preview', {
      workflow_id: id, context: { registry: listApplications() || [] },
    }, 5000);
    const info = preview && preview.ok && preview.body && typeof preview.body === 'object' ? preview.body : null;
    // If the backend cannot describe it, or the gate would refuse it anyway, let the executor give
    // the gate's own refusal: nothing outward can happen, so there is nothing to confirm.
    if (!info || info.ok !== true || info.runnable !== true) return { ok: true, confirmed: false };
    if (info.outward !== true) return { ok: true, confirmed: false };

    const lines = Array.isArray(info.preview_lines) ? info.preview_lines.map(String) : [];
    if (lines.length === 0 || linesDigest(lines) !== info.preview_sha256) {
      return { ok: false, error: 'preview_unverified', reason: 'BetterFingers could not verify what that workflow would do, so it did not run.' };
    }
    const shown = lines.flatMap((line) => displayLines(line));
    if (!fits(shown)) return { ok: false, error: 'too_long', reason: TOO_LONG };
    const decision = await confirm({
      title: 'Run workflow',
      message: `Run the workflow \u201C${makeVisible(String(info.name || id))}\u201D now?`,
      body: ['It will do exactly this, in this order:', '', ...shown],
      approveLabel: 'Run it',
      note: 'Something in the app asked for this run. If you did not, choose Cancel.',
    });
    if (!decision.approved) {
      return { ok: false, error: 'declined', reason: (decision && decision.error) || 'You cancelled. Nothing was run.' };
    }
    return { ok: true, confirmed: true };
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

  // --- voice requests (round 2, item 6; round 3, item 6) -----------------------------------------
  //
  // A spoken command can only REQUEST. Ambient audio, a video, or a replayed phrase can say "send it";
  // that is not a person's yes. The backend announces the request (a status event) and the native
  // dialog below is the only thing that can place the draft. Voice-started dialogs keep
  // Cancel as the default and are rate limited, so repeated speech cannot grind a person into clicking.
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
      note: 'You said \u201Csend it\u201D. Voice alone never sends; only this button does.',
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_DRAFT_SEND, String(draftId), draftSendBind('paste', text, false));
    if (!approval) return fault(UNAVAILABLE);
    return backend.send('POST', `/drafts/${draftId}/send`, { action: 'paste', open_chat: false, allow_resend: false, approval }, 120000);
  }

  // Round 3, item 6: there is no voice CONFIRMATION flow. The one command it served
  // (delete_history) has no implementation behind it, and a dialog that confirms nothing is
  // surface without a purpose. A spoken command can only REQUEST; the only spoken request that
  // opens a dialog is "send it" above, and the dialog, not the voice, places the draft.

  // --- saving a persona (few-shot examples) ----------------------------------------

  // Few-shot examples steer every future rewrite like learned examples do, so a save that
  // ADDS or changes one is approved in a native dialog (round 2, item 4). A save that adds
  // nothing goes straight through. The renderer names the persona and the body; the
  // stored examples are read from the backend, never taken from the page.
  async function savePersona({ name, body, timeoutMs } = {}) {
    if (typeof name !== 'string' || !name.trim() || name.length > 128) return fault('Choose a persona name first.');
    if (!body || typeof body !== 'object' || Array.isArray(body)) return fault('That persona could not be saved.');
    const payload = { ...body, name };
    delete payload.approval; // a page cannot supply one
    const wantsExamples = Object.prototype.hasOwnProperty.call(payload, 'few_shot');
    if (!wantsExamples) return backend.send('POST', '/personas', payload, Number(timeoutMs) || 5000);
    if (!Array.isArray(payload.few_shot) || payload.few_shot.length > 50) return fault('That persona has too many examples.');

    const current = await backend.send('GET', `/personas/${encodeURIComponent(name)}`, undefined, 5000);
    const stored = current && current.ok && current.body && typeof current.body === 'object' ? current.body.few_shot : [];
    const added = addedFewShot(payload.few_shot, stored);
    if (added.length === 0) return backend.send('POST', '/personas', payload, Number(timeoutMs) || 5000);

    if (added.some(([raw, out]) => raw.length > MAX_EXAMPLE_CHARS || out.length > MAX_EXAMPLE_CHARS)) {
      return fault('One of those examples is too long to learn.');
    }
    const shown = [`Persona: ${makeVisible(name)}`, ''];
    added.forEach(([raw, out], index) => {
      shown.push(`Example ${index + 1} \u2013 what was said:`, ...displayLines(raw), 'What it should become:', ...displayLines(out), '');
    });
    if (!fits(shown)) return fault(TOO_LONG);
    const decision = await confirm({
      title: 'Add examples to this persona',
      message: `Let \u201C${makeVisible(name)}\u201D learn ${added.length === 1 ? 'this example' : `these ${added.length} examples`}?`,
      body: shown,
      approveLabel: 'Add them',
      note: 'They will shape how this persona rewrites your future dictation until you remove them.',
    });
    if (!decision.approved) return declined(decision);
    const approval = trySign(PURPOSE_PERSONA_FEW_SHOT, name, personaFewShotBind(name, added));
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

  async function presentDraft({ title, action, openChat, text, approveLabel, defaultApprove = false }) {
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
      defaultApprove,
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
      message: `Make \u201C${makeVisible(String(newKey))}\u201D the shortcut that places a draft?`,
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
    presentVoiceTap,
    addPersonaExample,
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
  addedFewShot,
  makeVisible,
  wrapLine,
  displayLines,
  MAX_DISPLAY_LINES,
  WRAP_WIDTH,
  TICKET_TTL_S,
};
