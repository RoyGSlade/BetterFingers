import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

import { createRelay, validateEnvelope } from '../src/index.js';

const require = createRequire(import.meta.url);
const { createBugReportController } = require('../../../app/src/main/bugReportController.js');

const PRIVACY_NOTE = 'Automatic diagnostics exclude transcripts, drafts, audio, wake phrases, clipboard data, screenshots, raw logs, filesystem paths, exact hardware identifiers, exact model identifiers, and error messages.';
const REPORT_ID = '123e4567-e89b-42d3-a456-426614174000';

class MemoryKV {
  constructor() {
    this.values = new Map();
    this.puts = [];
  }

  async get(key) { return this.values.get(key) ?? null; }

  async put(key, value, options) {
    this.values.set(key, value);
    this.puts.push({ key, value, options });
  }

  async delete(key) { this.values.delete(key); }
}

function envelope(channel = 'discord', overrides = {}) {
  return {
    schema_version: 1,
    channel,
    report: {
      schema_version: 1,
      report_id: REPORT_ID,
      created_at: '2026-08-27T10:00:00.000Z',
      privacy_note: PRIVACY_NOTE,
      bug: {
        summary: '@everyone App freezes',
        steps: '1. Open it\n2. Click Record',
        expected: 'Recording starts',
        actual: 'The window freezes',
        contact: 'tester@example.com',
      },
      automatic_diagnostics: {
        schema_version: 1,
        generated_at: '2026-08-27T09:59:59.000Z',
        version: { backend_version: '1.1.0-alpha.3', profile_schema_version: 1 },
        platform: { family: 'windows', python: '3.12' },
        hardware: { tier: 'dgpu-8g', gpu_acceleration_available: true },
        runtime: {
          llm: { status: 'ready', runtime_build: 7000 },
          stt: { initialized: true, loaded: true },
          tts: { initialized: true, loaded: false },
        },
        resources: { resident_model_count: 2 },
        recent_error_counts: {
          total: 1,
          by_severity: { recoverable: 1 },
          by_component: { recording: 1 },
        },
        recent_error_breadcrumbs: [{
          component: 'recording', severity: 'recoverable', code: 'input_timeout',
        }],
      },
      ...overrides,
    },
  };
}

function requestFor(payload, headers = {}) {
  return new Request('https://relay.example.test/report', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'cf-connecting-ip': '203.0.113.10',
      ...headers,
    },
    body: JSON.stringify(payload),
  });
}

function baseEnv(extra = {}) {
  return {
    BUG_REPORT_RATE_LIMITER: { async limit() { return { success: true }; } },
    BUG_REPORT_DEDUPE: new MemoryKV(),
    DISCORD_WEBHOOK_URL: 'https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    RESEND_API_KEY: 're_test_server_side_only',
    BUG_REPORT_EMAIL_TO: 'support@example.com',
    BUG_REPORT_EMAIL_FROM: 'reports@example.com',
    ...extra,
  };
}

async function body(response) {
  return JSON.parse(await response.text());
}

test('closed schema accepts the desktop contract and rejects injected destinations or raw logs', () => {
  assert.equal(validateEnvelope(envelope()), true);
  assert.equal(validateEnvelope({ ...envelope(), webhook_url: 'https://attacker.invalid' }), false);
  assert.equal(validateEnvelope(envelope('discord', { raw_logs: 'C:/Users/Alice secret' })), false);
  const badDiagnostics = envelope();
  badDiagnostics.report.automatic_diagnostics.transcript = 'private words';
  assert.equal(validateEnvelope(badDiagnostics), false);
});

test('the real desktop controller produces a relay-valid envelope', async () => {
  const controller = createBugReportController({
    clock: () => Date.parse('2026-08-27T10:00:00.000Z'),
    randomUUID: () => REPORT_ID,
    backendProxy: {
      request: async () => ({
        ok: true,
        status: 200,
        body: {
          report: {
            generated_at: '2026-08-27T09:59:59.000Z',
            platform: { system: 'Windows', python: '3.12.7' },
            recent_errors: [],
          },
        },
      }),
    },
  });
  const preview = await controller.prepare({
    summary: 'Capture fails',
    steps: 'Press the hotkey',
    expected: 'Recording starts',
    actual: 'Nothing happens',
  });

  assert.equal(validateEnvelope({
    schema_version: 1,
    channel: 'discord',
    report: JSON.parse(preview.previewText),
  }), true);
});

test('Discord delivery suppresses mentions, attaches only the reviewed JSON, and records dedupe state', async () => {
  const calls = [];
  const env = baseEnv();
  const relay = createRelay({
    randomUUID: () => 'request-discord',
    fetchImpl: async (...args) => { calls.push(args); return new Response('{}', { status: 200 }); },
  });

  const response = await relay.fetch(requestFor(envelope()), env);
  const result = await body(response);

  assert.equal(response.status, 202);
  assert.deepEqual(result, {
    ok: true, status: 'accepted', channel: 'discord', request_id: 'request-discord',
  });
  assert.equal(calls.length, 1);
  assert.match(calls[0][0], /^https:\/\/discord\.com\/api\/webhooks\//);
  assert.match(calls[0][0], /\?wait=true$/);
  const form = calls[0][1].body;
  const message = JSON.parse(form.get('payload_json'));
  assert.deepEqual(message.allowed_mentions, { parse: [] });
  assert.doesNotMatch(message.content, /@everyone|<@/i);
  const attachment = form.get('files[0]');
  assert.deepEqual(JSON.parse(await attachment.text()), envelope().report);
  assert.equal(env.BUG_REPORT_DEDUPE.values.get(`v1:discord:${REPORT_ID}`), 'delivered');
  assert.doesNotMatch(JSON.stringify(result), /webhooks|abcdefghijklmnopqrstuvwxyz|App freezes/);
});

test('email delivery is plain text, server-authenticated, and idempotent at the provider', async () => {
  const calls = [];
  const relay = createRelay({
    randomUUID: () => 'request-email',
    fetchImpl: async (...args) => { calls.push(args); return new Response('{}', { status: 200 }); },
  });
  const env = baseEnv();

  const response = await relay.fetch(requestFor(envelope('email')), env);
  const result = await body(response);

  assert.equal(response.status, 202);
  assert.equal(calls[0][0], 'https://api.resend.com/emails');
  assert.equal(calls[0][1].headers.authorization, 'Bearer re_test_server_side_only');
  assert.equal(calls[0][1].headers['idempotency-key'], `betterfingers-${REPORT_ID}`);
  const outbound = JSON.parse(calls[0][1].body);
  assert.deepEqual(outbound.to, ['support@example.com']);
  assert.match(outbound.text, /App freezes/);
  assert.match(outbound.text, /Automatic diagnostics/);
  assert.equal('html' in outbound, false);
  assert.doesNotMatch(JSON.stringify(result), /re_test|support@example|tester@example/);
});

test('delivered reports are acknowledged without a second provider call', async () => {
  let sends = 0;
  const relay = createRelay({
    randomUUID: () => `request-${sends}`,
    fetchImpl: async () => { sends += 1; return new Response('{}', { status: 200 }); },
  });
  const env = baseEnv();

  assert.equal((await relay.fetch(requestFor(envelope()), env)).status, 202);
  const duplicate = await relay.fetch(requestFor(envelope()), env);
  assert.equal(duplicate.status, 200);
  assert.equal((await body(duplicate)).status, 'duplicate');
  assert.equal(sends, 1);
});

test('provider failure never claims delivery, never leaks content, and permits a later retry', async () => {
  let sends = 0;
  const relay = createRelay({
    randomUUID: () => 'request-failed',
    fetchImpl: async () => { sends += 1; return new Response('provider secret detail', { status: 503 }); },
  });
  const env = baseEnv();

  const first = await relay.fetch(requestFor(envelope()), env);
  const firstBody = await body(first);
  assert.equal(first.status, 502);
  assert.equal(firstBody.error, 'delivery_failed');
  assert.doesNotMatch(JSON.stringify(firstBody), /provider secret|App freezes|webhook/i);
  assert.equal(env.BUG_REPORT_DEDUPE.values.has(`v1:discord:${REPORT_ID}`), false);

  assert.equal((await relay.fetch(requestFor(envelope()), env)).status, 502);
  assert.equal(sends, 2);
});

test('one unconfigured channel does not disable the configured channel', async () => {
  const relay = createRelay({
    randomUUID: () => 'request-channel',
    fetchImpl: async () => new Response('{}', { status: 200 }),
  });
  const env = baseEnv({ DISCORD_WEBHOOK_URL: '' });

  assert.equal((await relay.fetch(requestFor(envelope('discord')), env)).status, 503);
  assert.equal((await relay.fetch(requestFor(envelope('email')), env)).status, 202);
});

test('rate limiting, mandatory bindings, browser origins, and body bounds fail closed', async () => {
  const relay = createRelay({ randomUUID: () => 'request-guard' });

  const originResponse = await relay.fetch(
    requestFor(envelope(), { origin: 'https://attacker.example' }),
    baseEnv(),
  );
  assert.equal(originResponse.status, 403);

  const missingLimiter = baseEnv();
  delete missingLimiter.BUG_REPORT_RATE_LIMITER;
  assert.equal((await relay.fetch(requestFor(envelope()), missingLimiter)).status, 503);

  const limited = baseEnv({
    BUG_REPORT_RATE_LIMITER: { async limit() { return { success: false }; } },
  });
  const limitedResponse = await relay.fetch(requestFor(envelope()), limited);
  assert.equal(limitedResponse.status, 429);
  assert.equal(limitedResponse.headers.get('retry-after'), '60');

  const oversized = new Request('https://relay.example.test/report', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'cf-connecting-ip': '203.0.113.10',
    },
    body: JSON.stringify({ padding: 'x'.repeat(41 * 1024) }),
  });
  assert.equal((await relay.fetch(oversized, baseEnv())).status, 413);
});

test('health reports only coarse configuration booleans', async () => {
  const relay = createRelay({ randomUUID: () => 'request-health' });
  const response = await relay.fetch(
    new Request('https://relay.example.test/health'),
    baseEnv(),
  );
  const result = await body(response);

  assert.equal(response.status, 200);
  assert.deepEqual(result.configured, {
    discord: true, email: true, rate_limit: true, dedupe: true,
  });
  assert.doesNotMatch(JSON.stringify(result), /re_test|webhooks|support@example/);
});
