import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createBugReportController } = require('../src/main/bugReportController.js');

function relayAcknowledgement(channel, status = 'accepted') {
  return new Response(JSON.stringify({
    ok: true,
    status,
    channel,
    request_id: 'relay-request-1',
  }), {
    status: status === 'duplicate' ? 200 : 202,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function setup({
  env = {}, report = {}, now = 1000, confirm = 0, fetchImpl,
  shellImpl, clipboardImpl, timers,
} = {}) {
  const clock = { value: now };
  const calls = { requests: [], dialogs: [], clipboard: [], opened: [], fetch: [] };
  const controller = createBugReportController({
    env,
    clock: () => clock.value,
    randomUUID: () => 'preview-1',
    backendProxy: {
      request: async (request) => {
        calls.requests.push(request);
        return { ok: true, status: 200, body: { report } };
      },
    },
    dialog: {
      showMessageBox: async (options) => {
        calls.dialogs.push(options);
        return { response: confirm };
      },
    },
    clipboard: clipboardImpl || { writeText: (value) => calls.clipboard.push(value) },
    shell: shellImpl || { openExternal: async (value) => calls.opened.push(value) },
    fetch: fetchImpl || (async (...args) => {
      calls.fetch.push(args);
      const payload = JSON.parse(args[1].body);
      return relayAcknowledgement(payload.channel);
    }),
    timers,
  });
  return { controller, calls, clock };
}

const relayEnv = {
  BETTERFINGERS_BUG_REPORT_ENDPOINT: 'https://relay.example.test/report',
  BETTERFINGERS_BUG_REPORT_CHANNELS: 'discord,email',
};

function richReport() {
  return {
    generated_at: '2026-08-26T01:02:03Z',
    version: { backend_version: '1.2.3-alpha.3', profile_schema_version: 1, config_version: 2, secret: 'token' },
    platform: { system: 'Windows', release: '11-secret', python: '3.12.7', path: 'C:/Users/Alice' },
    hardware_tier: 'Dedicated GPU (8 GB) (dgpu-8g)',
    hardware: {
      cpu: { model: 'Secret CPU serial 123' },
      gpu: { name: 'Secret GPU serial 456', kind: 'cuda', accelerated: true },
      memory: { total_mb: 65536 },
    },
    runtime: {
      llm: {
        runtime_status: 'ready', runtime_build: 7000, required_runtime_build: 6500,
        runtime_validation_error_code: 'runtime_link_failure', runtime_validation_elapsed_sec: 0.25,
        runtime_validation_timeout_sec: 30, last_error: 'user prompt leaked here',
      },
      stt: {
        initialized: true, loaded: true, constructed: true, probe_passed: true,
        inference_ready: true, model_size: 'private/model', device: 'cuda:0',
        device_fallback_code: 'cuda_runtime_missing', error_state: 'user@example.com',
      },
      tts: { initialized: true, loaded: false, backend: 'private-provider' },
    },
    resources: {
      ledger: {
        llm: { model_id: 'provider/private-account/model' },
        stt: { model_id: 'C:/Users/Alice/model.bin' },
      },
      available_mb: 12345,
    },
    recent_errors: [
      {
        severity: 'recoverable', component: 'llm', created_at: '2026-08-26T01:02:04Z',
        message: '@everyone C:/Users/Alice secret token', details: { prompt: 'draft' },
      },
      {
        severity: 'fatal', component: 'stt', created_at: '2026-08-26T01:02:05Z',
        message: 'cuda_runtime_missing', details: { transcript: 'must not survive' },
      },
      {
        severity: 'warning', component: 'future-user-controlled-component', created_at: 'not-a-date',
        message: 'unknown_component_code', details: { path: 'C:/Users/Alice' },
      },
    ],
    message_rescue: { context: { active: true }, persona_store: { path: 'C:/Users/Alice/personas' } },
    paths: { app_data_dir: 'C:/Users/Alice/AppData', debug_log_path: '\\\\server\\share\\debug.log' },
    transcript: 'private transcript', draft: 'private draft', audio: 'bytes', wake_phrase: 'secret phrase',
    clipboard: 'clipboard secret', screenshot: 'image bytes', raw_logs: 'full raw log', future_field: 'must fail closed',
  };
}

test('prepare builds the closed coarse projection and ignores renderer-supplied diagnostics', async () => {
  const { controller, calls } = setup({ report: richReport() });
  const preview = await controller.prepare({
    summary: 'App broke', steps: 'Click the button', expected: 'It works', actual: 'It froze',
    contact: 'tester@example.com', diagnostics: { raw_logs: 'attacker' }, raw_logs: 'attacker',
  });

  assert.deepEqual(calls.requests, [{ method: 'GET', path: '/diagnostics/support-report', timeoutMs: 15_000 }]);
  const parsed = JSON.parse(preview.previewText);
  assert.equal(parsed.schema_version, 1);
  assert.equal(parsed.bug.summary, 'App broke');
  assert.deepEqual(parsed.automatic_diagnostics.platform, { family: 'windows', python: '3.12' });
  assert.deepEqual(parsed.automatic_diagnostics.hardware, { tier: 'dgpu-8g', gpu_acceleration_available: true });
  assert.equal(parsed.automatic_diagnostics.runtime.llm.status, 'ready');
  assert.equal(parsed.automatic_diagnostics.runtime.llm.error_code, 'runtime_link_failure');
  assert.deepEqual(parsed.automatic_diagnostics.resources, { resident_model_count: 2 });
  assert.deepEqual(parsed.automatic_diagnostics.recent_error_counts, {
    total: 3,
    by_severity: { recoverable: 1, fatal: 1, warning: 1 },
    by_component: { llm: 1, stt: 1 },
  });
  assert.deepEqual(parsed.automatic_diagnostics.recent_error_breadcrumbs, [
    { component: 'llm', severity: 'recoverable', created_at: '2026-08-26T01:02:04.000Z' },
    {
      component: 'stt', severity: 'fatal', created_at: '2026-08-26T01:02:05.000Z',
      code: 'cuda_runtime_missing',
    },
  ]);
  assert.ok(Object.isFrozen(preview));
  assert.doesNotMatch(
    JSON.stringify(parsed.automatic_diagnostics),
    /Alice|Secret CPU|Secret GPU|private-account|model\.bin|prompt leaked|secret token|must not survive|unknown_component_code|future-user-controlled-component|persona_store|app_data_dir|raw_logs|future_field|wake_phrase|clipboard secret|image bytes/i,
  );
});

test('automatic error breadcrumbs retain only the newest 15 safe machine events', async () => {
  const recent_errors = Array.from({ length: 20 }, (_, index) => ({
    severity: 'recoverable',
    component: 'recording',
    created_at: `2026-08-26T01:02:${String(index).padStart(2, '0')}Z`,
    message: `recording_code_${index}`,
    details: { raw_text: `private-${index}` },
  }));
  const { controller } = setup({ report: { recent_errors } });
  const preview = await controller.prepare({ summary: 'x', actual: 'y' });
  const diagnostics = JSON.parse(preview.previewText).automatic_diagnostics;

  assert.equal(diagnostics.recent_error_breadcrumbs.length, 15);
  assert.equal(diagnostics.recent_error_breadcrumbs[0].code, 'recording_code_5');
  assert.equal(diagnostics.recent_error_breadcrumbs.at(-1).code, 'recording_code_19');
  assert.equal(diagnostics.recent_error_counts.total, 20);
  assert.doesNotMatch(JSON.stringify(diagnostics), /private-/);
});

test('prepare enforces required fields, neutralizes Discord mentions, and rejects oversized Unicode reports', async () => {
  const { controller } = setup();
  await assert.rejects(() => controller.prepare({ summary: '', actual: 'broken' }), /required/i);
  const preview = await controller.prepare({
    summary: '@everyone <@123> broken', actual: '@here <@!456> failed',
  });
  assert.doesNotMatch(preview.previewText, /@everyone|@here|<@123>|<@!456>/);

  const oversized = setup().controller;
  await assert.rejects(
    () => oversized.prepare({ summary: 'x', actual: '界'.repeat(4000), steps: '界'.repeat(4000), expected: '界'.repeat(4000) }),
    /too large/i,
  );
});

test('public config exposes capabilities and fallbacks but never the relay endpoint', () => {
  const { controller } = setup({ env: relayEnv });
  const config = controller.getConfig();
  assert.deepEqual(config, {
    direct: true,
    directDiscord: true,
    directEmail: true,
    fallbacks: { email: 'donavencrenshaw@gmail.com', discord: 'https://discord.gg/m3HH45CFwz' },
  });
  assert.equal('endpoint' in config, false);
});

test('invalid, private, credentialed, query-string, and direct webhook endpoints disable direct delivery', () => {
  const invalid = [
    'http://relay.example.com/report',
    'https://localhost/report',
    'https://127.0.0.1/report',
    'https://10.0.0.8/report',
    'https://[::1]/report',
    'https://user:pass@relay.example.com/report',
    'https://relay.example.com/report?token=secret',
    'https://discord.com/api/webhooks/1/secret',
  ];
  for (const endpoint of invalid) {
    const { controller } = setup({ env: { ...relayEnv, BETTERFINGERS_BUG_REPORT_ENDPOINT: endpoint } });
    assert.equal(controller.getConfig().direct, false, endpoint);
  }
});

test('expired previews and cancelled native confirmation perform no external action', async () => {
  const expired = setup({ env: relayEnv });
  await expired.controller.prepare({ summary: 'x', actual: 'y' });
  expired.clock.value += 10 * 60 * 1000;
  await assert.rejects(
    () => expired.controller.submit({ previewId: 'preview-1', destination: 'direct-email' }),
    /expired/i,
  );
  assert.equal(expired.calls.fetch.length, 0);

  const cancelled = setup({ env: relayEnv, confirm: 1 });
  await cancelled.controller.prepare({ summary: 'x', actual: 'y' });
  const result = await cancelled.controller.submit({ previewId: 'preview-1', destination: 'discord' });
  assert.deepEqual(result, { delivered: false, status: 'cancelled' });
  assert.equal(cancelled.calls.clipboard.length, 0);
  assert.equal(cancelled.calls.opened.length, 0);
});

test('direct success posts only the reviewed report, consumes it, and throttles a new preview', async () => {
  const networkCalls = [];
  const ctx = setup({
    env: relayEnv,
    fetchImpl: async (...args) => {
      networkCalls.push(args);
      return relayAcknowledgement(JSON.parse(args[1].body).channel);
    },
  });
  await ctx.controller.prepare({ summary: 'x', actual: 'y', diagnostics: { forged: true } });
  const result = await ctx.controller.submit({ previewId: 'preview-1', destination: 'direct-discord' });
  assert.deepEqual(result, {
    delivered: true,
    status: 'delivered',
    requestId: 'relay-request-1',
    relayStatus: 'accepted',
  });
  assert.equal(networkCalls.length, 1);
  assert.equal(networkCalls[0][0], 'https://relay.example.test/report');
  assert.equal(networkCalls[0][1].redirect, 'error');
  const payload = JSON.parse(networkCalls[0][1].body);
  assert.equal(payload.channel, 'discord');
  assert.equal(payload.report.bug.diagnostics, undefined);
  assert.equal('text' in payload, false);

  await ctx.controller.prepare({ summary: 'another', actual: 'failure' });
  assert.deepEqual(
    await ctx.controller.submit({ previewId: 'preview-1', destination: 'direct-email' }),
    { delivered: false, status: 'rate_limited' },
  );
  assert.equal(networkCalls.length, 1);
});

test('direct failure and timeout never claim delivery', async () => {
  const failed = setup({ env: relayEnv, fetchImpl: async () => ({ status: 503 }) });
  await failed.controller.prepare({ summary: 'x', actual: 'y' });
  assert.deepEqual(
    await failed.controller.submit({ previewId: 'preview-1', destination: 'direct-email' }),
    { delivered: false, status: 'delivery_failed' },
  );

  const timeout = setup({
    env: relayEnv,
    timers: { setTimeout(fn) { fn(); return 1; }, clearTimeout() {} },
    fetchImpl: async (_url, options) => {
      assert.equal(options.signal.aborted, true);
      throw new Error('aborted');
    },
  });
  await timeout.controller.prepare({ summary: 'x', actual: 'y' });
  assert.deepEqual(
    await timeout.controller.submit({ previewId: 'preview-1', destination: 'direct-email' }),
    { delivered: false, status: 'delivery_timeout' },
  );
});

test('a generic or malformed 2xx response is not a delivery acknowledgement', async () => {
  for (const response of [
    new Response('<html>ok</html>', { status: 200, headers: { 'content-type': 'text/html' } }),
    new Response(JSON.stringify({ ok: true }), { status: 202, headers: { 'content-type': 'application/json' } }),
    new Response(JSON.stringify({
      ok: true, status: 'accepted', channel: 'email', request_id: 'wrong-channel',
    }), { status: 202, headers: { 'content-type': 'application/json' } }),
  ]) {
    const ctx = setup({ env: relayEnv, fetchImpl: async () => response });
    await ctx.controller.prepare({ summary: 'x', actual: 'y' });
    assert.deepEqual(
      await ctx.controller.submit({ previewId: 'preview-1', destination: 'direct-discord' }),
      { delivered: false, status: 'delivery_failed' },
    );
  }
});

test('manual fallbacks copy the full reviewed preview and only report a handoff', async () => {
  const ctx = setup();
  const preview = await ctx.controller.prepare({ summary: 'x', actual: 'y' });
  const discord = await ctx.controller.submit({ previewId: preview.previewId, destination: 'discord' });
  assert.deepEqual(discord, { delivered: false, status: 'copied_opened_discord' });
  assert.equal(ctx.calls.clipboard[0], preview.previewText);
  assert.equal(ctx.calls.opened[0], 'https://discord.gg/m3HH45CFwz');

  const email = await ctx.controller.submit({ previewId: preview.previewId, destination: 'email' });
  assert.deepEqual(email, { delivered: false, status: 'copied_opened_email' });
  assert.match(ctx.calls.opened[1], /^mailto:donavencrenshaw@gmail\.com\?subject=/);
});
