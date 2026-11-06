// Redact user-dictated content from Electron main-process logs by default
// (DESIGN §9.3, Tier-3 M4 A3). Mirrors log_redaction.py's semantics exactly
// (same env var, same truthy set, same markers) so the redaction posture is
// one policy expressed in two languages, not two policies that can drift:
// callers log a redacted length summary instead of raw text unless a
// developer opts into raw logging for the process via
// BETTERFINGERS_LOG_RAW_TEXT.
//
// This is a STANDING GUARDRAIL, not a response to a found leak — the Phase 0
// audit (docs/redaction-audit.md) found zero current console.* sites in
// app/src/main/*.js or app/src/renderer/main.js logging raw dictated/final/
// draft/transcript/persona-example text (every site logs an Error object, an
// IPC channel/endpoint string, a hotkey binding, or a file path). No call
// site is being rewrapped here — redact.test.mjs turns that audited-clean
// snapshot into a regression gate so the next feature that logs a draft's
// finished text straight to the console gets caught instead of shipped.

'use strict';

const TRUTHY = new Set(['1', 'true', 'yes', 'on']);

function rawTextLoggingEnabled() {
  const value = String(process.env.BETTERFINGERS_LOG_RAW_TEXT || '').trim().toLowerCase();
  return TRUTHY.has(value);
}

function redact(text) {
  if (rawTextLoggingEnabled()) {
    return text === null || text === undefined ? '' : String(text);
  }
  if (text === null || text === undefined) {
    return '<empty>';
  }
  const s = String(text);
  if (s.length === 0) {
    return '<empty>';
  }
  return `<redacted ${s.length} chars>`;
}

// --- credentials -----------------------------------------------------------
// Mirrors backend/privacy/secret_scrub.py (Phase 0 item 10): bearer tokens,
// token= style parameters, the WebSocket "auth:" first frame and well-known key
// shapes are masked in anything headed for a log, whatever raw-text setting is
// on. This one is NOT opt-out: no debugging session needs a live credential in a
// file.
const REDACTED = '[redacted]';
const BEARER_RE = /\b(bearer)([\s:=]+)([A-Za-z0-9._~+/=-]{6,})/gi;
const KV_RE = /\b((?:[a-z0-9]*[_-])*(?:token|api[_-]?key|apikey|secret|password|passwd|auth))(=|:\s*)(?!\[redacted\])([^\s&"'<>,;]{3,})/gi;
// Quoted keys, as in JSON bodies and Python dict reprs: {"token": "abc"}, {'Authorization': 'x'}
// (the unquoted pattern never matched these; Codex re-review).
const QUOTED_KV_RE = /(["'])((?:[a-z0-9]*[_-])*(?:token|api[_-]?key|apikey|secret|password|passwd|auth|authorization|credential|credentials))\1(\s*:\s*)(["'])(.*?)(?<!\\)\4/gi;
const AUTH_FRAME_RE = /\b(auth:)([A-Za-z0-9._~+/=-]{6,})/gi;
const KEY_SHAPE_RE = /\b(sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b/g;
const LONG_HEX_RE = /\b[0-9a-fA-F]{48,}\b/g;

function redactSecrets(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(QUOTED_KV_RE, (_m, q, key, colon, vq) => `${q}${key}${q}${colon}${vq}${REDACTED}${vq}`)
    .replace(BEARER_RE, (_m, a, b) => `${a}${b}${REDACTED}`)
    .replace(AUTH_FRAME_RE, (_m, a) => `${a}${REDACTED}`)
    .replace(KV_RE, (_m, a, b) => `${a}${b}${REDACTED}`)
    .replace(KEY_SHAPE_RE, REDACTED)
    .replace(LONG_HEX_RE, REDACTED);
}

// Line-oriented redaction for a byte stream that arrives in arbitrary chunks. A secret can
// straddle two chunks ("...token=ab" / "cd..."), and redacting each chunk on its own would
// miss it, so an unfinished line is held back until its newline arrives (or until it has grown
// past maxPending, so a stream that never ends a line cannot grow without bound; in that rare
// case the held text is redacted and flushed). push() returns the finished, redacted lines;
// flush() returns whatever is still held, redacted.
function createLineRedactor({ maxPending = 16 * 1024 } = {}) {
  let pending = '';
  return {
    push(chunk) {
      pending += String(chunk);
      const lines = pending.split('\n');
      pending = lines.pop();
      const out = lines.map((line) => redactSecrets(line.endsWith('\r') ? line.slice(0, -1) : line));
      if (pending.length > maxPending) {
        out.push(redactSecrets(pending));
        pending = '';
      }
      return out;
    },
    flush() {
      if (!pending) return [];
      const line = redactSecrets(pending);
      pending = '';
      return [line];
    },
  };
}

module.exports = { rawTextLoggingEnabled, redact, redactSecrets, createLineRedactor };
