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

module.exports = { rawTextLoggingEnabled, redact };
