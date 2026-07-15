// Unit tests for redact.js + a lint-style regression gate (DESIGN §9.3,
// Tier-3 M4 A3/A4) — the JS twin of tests/test_log_redaction.py's
// LoggingLeakGateTests. Run with: node --test app/tests/redact.test.mjs
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { redact, rawTextLoggingEnabled } = require('../src/main/redact.js');

const APP_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

// --- redact() / rawTextLoggingEnabled() semantics --------------------------

function withEnv(value, fn) {
  const orig = process.env.BETTERFINGERS_LOG_RAW_TEXT;
  if (value === undefined) {
    delete process.env.BETTERFINGERS_LOG_RAW_TEXT;
  } else {
    process.env.BETTERFINGERS_LOG_RAW_TEXT = value;
  }
  try {
    fn();
  } finally {
    if (orig === undefined) {
      delete process.env.BETTERFINGERS_LOG_RAW_TEXT;
    } else {
      process.env.BETTERFINGERS_LOG_RAW_TEXT = orig;
    }
  }
}

test('default redacts content but keeps length', () => {
  withEnv(undefined, () => {
    assert.equal(redact('hello world'), '<redacted 11 chars>');
  });
});

test('default does not leak any substring', () => {
  const secret = 'my bank pin is 4321';
  withEnv(undefined, () => {
    const out = redact(secret);
    assert.ok(!out.includes('bank'));
    assert.ok(!out.includes('4321'));
    assert.ok(out.includes(String(secret.length)));
  });
});

test('empty and null/undefined render as empty marker', () => {
  withEnv(undefined, () => {
    assert.equal(redact(''), '<empty>');
    assert.equal(redact(null), '<empty>');
    assert.equal(redact(undefined), '<empty>');
  });
});

test('opt-in returns raw text', () => {
  withEnv('1', () => {
    assert.equal(redact('hello world'), 'hello world');
    assert.equal(redact(null), '');
  });
});

test('env var truthy/falsy values', () => {
  const cases = [
    ['1', true], ['true', true], ['ON', true], ['yes', true],
    ['0', false], ['', false], ['nope', false],
  ];
  for (const [value, expected] of cases) {
    withEnv(value, () => {
      assert.equal(rawTextLoggingEnabled(), expected, value);
    });
  }
});

test('env var absent is disabled', () => {
  withEnv(undefined, () => {
    assert.equal(rawTextLoggingEnabled(), false);
  });
});

test('non-string input is coerced', () => {
  withEnv(undefined, () => {
    assert.equal(redact(12345), '<redacted 5 chars>');
  });
});

// --- Regression gate: console.*() sites must not carry unwrapped user
// content (DESIGN.md §9.3 breadth). Coarse, line-level, substring-based —
// same tripwire-not-proof caveat as the Python twin. The Phase 0 audit
// (docs/redaction-audit.md) found ZERO current offenders; this gate exists
// so the NEXT feature that adds console.log('draft:', finalText) is caught.

const CONSOLE_CALL_RE = /console\.(log|warn|error|info|debug)\s*\(/;
const SUSPICIOUS_TERMS = [
  'rawtext', 'finaltext', 'drafttext', 'transcript', 'prompt',
  'personaexample', 'clipboardtext', 'dictatedtext',
];

// file -> Set(exact trimmed line content), for verified-SAFE sites that
// happen to match a suspicious term without being user content. Keyed by
// CONTENT not line number — an unrelated edit shifting line numbers
// elsewhere must never turn an already-audited-safe site red again (this bit
// the Python gate once; learned the lesson before writing this one).
const ALLOWLIST = {};

function mainProcessJsFiles() {
  const dir = path.join(APP_ROOT, 'src', 'main');
  return readdirSync(dir)
    .filter((name) => name.endsWith('.js'))
    .map((name) => path.join('src', 'main', name));
}

function scanFileForOffenders(relPath) {
  const abs = path.join(APP_ROOT, relPath);
  const lines = readFileSync(abs, 'utf-8').split('\n');
  const offenders = [];
  const allowed = ALLOWLIST[relPath] || new Set();
  lines.forEach((line, idx) => {
    if (!CONSOLE_CALL_RE.test(line)) return;
    const lowered = line.toLowerCase();
    if (!SUSPICIOUS_TERMS.some((term) => lowered.includes(term))) return;
    if (line.includes('redact(')) return;
    const stripped = line.trim();
    if (allowed.has(stripped)) return;
    offenders.push(`${relPath}:${idx + 1}: ${stripped}`);
  });
  return offenders;
}

test('no unwrapped user-content-shaped console.*() calls in app/src/main/*.js', () => {
  const offenders = mainProcessJsFiles().flatMap(scanFileForOffenders);
  assert.deepEqual(
    offenders, [],
    `Unwrapped user-content-shaped console call(s) — wrap with redact(), or add a ` +
    `reasoned ALLOWLIST entry if verified SAFE:\n${offenders.join('\n')}`,
  );
});

test('no unwrapped user-content-shaped console.*() calls in app/src/renderer/main.js', () => {
  const offenders = scanFileForOffenders(path.join('src', 'renderer', 'main.js'));
  assert.deepEqual(
    offenders, [],
    `Unwrapped user-content-shaped console call(s) — wrap with redact(), or add a ` +
    `reasoned ALLOWLIST entry if verified SAFE:\n${offenders.join('\n')}`,
  );
});
