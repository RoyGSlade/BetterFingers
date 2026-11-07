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

// --- redactSecrets (Phase 0 item 10) ---------------------------------------

const { redactSecrets, createLineRedactor } = require('../src/main/redact.js');
const SECRET = '9f8e7d6c'.repeat(8);

test('redactSecrets masks bearer tokens, token= parameters, auth frames and key shapes', () => {
  for (const text of [
    `Authorization: Bearer ${SECRET}`,
    `GET /ws/voice_status?token=${SECRET}&x=1 HTTP/1.1`,
    `auth:${SECRET}`,
    `BETTERFINGERS_AUTH_TOKEN=${SECRET}`,
    `leaked ${SECRET} in prose`,
    'key sk-ant-abcdefgh12345678',
    'ghp_' + 'y'.repeat(30),
  ]) {
    const out = redactSecrets(text);
    assert.ok(!out.includes(SECRET), text);
    assert.ok(!out.includes('sk-ant-abcdefgh12345678'), text);
    assert.ok(!out.includes('y'.repeat(30)), text);
    assert.ok(out.includes('[redacted]'), text);
  }
});

test('redactSecrets leaves ordinary log text alone and is idempotent', () => {
  for (const text of ['Loaded model base.en in 1.2s', 'token_count=5', 'author=bob', 'GET /runtime/status 200']) {
    assert.equal(redactSecrets(text), text);
  }
  const once = redactSecrets(`Bearer ${SECRET}`);
  assert.equal(redactSecrets(once), once);
  assert.equal(redactSecrets(null), '');
});

// --- Round 2, item 7: the gaps Codex listed ---------------------------------------

test('quoted JSON and repr values are masked', () => {
  const secrets = [SECRET, 'abc-secret-value-123', 'sk-short', 'hunter2hunter2', 'short-token-value', 's3cr3t-value'];
  for (const sample of [
    `{"token": "${SECRET}"}`, `{'access_token': '${SECRET}', 'x': 1}`, `{"Authorization": "Bearer ${SECRET}"}`,
    "{'Authorization': 'abc-secret-value-123'}", '{"api_key":"sk-short"}', '{ "password" : "hunter2hunter2" }',
    'payload={"auth_token":"short-token-value"}', '{"client_secret": "s3cr3t-value"}',
  ]) {
    const out = redactSecrets(sample);
    for (const secret of secrets) assert.ok(!out.includes(secret), `${secret} survived in ${out}`);
    assert.ok(out.includes('[redacted]'), sample);
  }
  for (const plain of ['{"name": "Coach", "token_count": 5}', '{"author": "bob"}', '{"keys": ["a", "b"]}']) {
    assert.equal(redactSecrets(plain), plain);
  }
});

test('createLineRedactor masks a secret split across chunk boundaries', () => {
  const redactor = createLineRedactor();
  const line = `INFO: GET /x Authorization: Bearer ${SECRET} done\n`;
  for (const cut of [10, 33, 40, 60, 80]) {
    const out = [...redactor.push(line.slice(0, cut)), ...redactor.push(line.slice(cut))].join('\n');
    assert.ok(!out.includes(SECRET), `cut at ${cut}`);
    assert.ok(!out.includes(SECRET.slice(0, 12)), `a prefix survived at ${cut}`);
    assert.ok(out.includes('done'), `cut at ${cut}`);
  }
});

test('createLineRedactor holds back an unfinished line, flushes it redacted, and caps a runaway line', () => {
  const redactor = createLineRedactor({ maxPending: 200 });
  assert.deepEqual(redactor.push('partial line with token=abc'), []);
  assert.deepEqual(redactor.flush(), ['partial line with token=[redacted]']);
  assert.deepEqual(redactor.flush(), []);
  const flood = redactor.push('x'.repeat(500));
  assert.ok(flood.length >= 1, 'a line that never ends is flushed at the cap');
  assert.deepEqual(createLineRedactor().push('a\r\nb\n'), ['a', 'b']);
});

// Round 3, item 5 (Codex re-check 2, finding 5): the overflow flush used to emit the oversized
// line raw-redacted and RESET, so a credential straddling the 16 KiB boundary lost its prefix
// ("token=") in the first half and its suffix arrived in the next chunk looking like plain text.
// Now the oversized line is dropped through its terminating newline and replaced by a marker.
test('a credential split across the 16 KiB overflow boundary never reaches the output', () => {
  const credential = 'Zq7Vt2Lm9Rw4Kp8Xc3Nb6Hy1Gd5Fs0Ja'; // synthetic, non-hex, 32 chars
  for (const offset of [1, 6, 12, 20, 31]) {
    const redactor = createLineRedactor();
    // A space before "token=" so the whole line WOULD be caught; the cut lands past the cap.
    const prefix = `${'x'.repeat(16 * 1024 - 'token='.length - 1)} `;
    const line = `${prefix}token=${credential} tail\nnext line ok\n`;
    const cut = prefix.length + 'token='.length + offset; // inside the credential, past the cap
    const out = [...redactor.push(line.slice(0, cut)), ...redactor.push(line.slice(cut)), ...redactor.flush()];
    const joined = out.join('\n');
    assert.ok(!joined.includes(credential.slice(offset)), `credential suffix leaked at offset ${offset}`);
    assert.ok(out.includes('[line too long, dropped]'), `no drop marker at offset ${offset}`);
    assert.ok(out.includes('next line ok'), `the following line was lost at offset ${offset}`);
    assert.ok(!joined.includes(' tail'), `the rest of the dropped line leaked at offset ${offset}`);
  }
});

test('an oversized line keeps being discarded across many chunks until its newline', () => {
  const redactor = createLineRedactor({ maxPending: 64 });
  const out = [];
  out.push(...redactor.push('a'.repeat(100)));
  out.push(...redactor.push('password=hunter2hunter2'));
  out.push(...redactor.push('b'.repeat(100)));
  out.push(...redactor.push(' end\nafter\n'));
  assert.deepEqual(out, ['[line too long, dropped]', 'after']);
  assert.deepEqual(redactor.flush(), []);
});
