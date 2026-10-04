const MAX_REQUEST_BYTES = 40 * 1024;
const MAX_REPORT_BYTES = 32 * 1024;
const PROCESSING_TTL_SECONDS = 10 * 60;
const DELIVERED_TTL_SECONDS = 7 * 24 * 60 * 60;
const PRIVACY_NOTE = 'Automatic diagnostics exclude transcripts, drafts, audio, wake phrases, clipboard data, screenshots, raw logs, filesystem paths, exact hardware identifiers, exact model identifiers, and error messages.';

const CHANNELS = new Set(['discord', 'email']);
const LLM_STATUSES = new Set([
  'disabled', 'missing_llama_server', 'missing_model',
  'runtime_validation_timeout', 'runtime_invalid', 'runtime_link_failure',
  'runtime_outdated', 'ready', 'startup_failure', 'not_loaded',
]);
const ERROR_CODES = new Set([
  'runtime_validation_timeout', 'runtime_link_failure',
  'runtime_outdated', 'runtime_invalid',
]);
const HARDWARE_TIERS = new Set(['dgpu-12g+', 'dgpu-8g', 'igpu', 'cpu-only']);
const SEVERITIES = new Set(['info', 'warning', 'recoverable', 'fatal', 'error']);
const COMPONENTS = new Set([
  'diagnostics', 'hotkeys', 'llm', 'recording', 'review',
  'selection_rewrite', 'stt', 'tts',
]);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const IDENTIFIER_RE = /^[A-Za-z0-9][A-Za-z0-9.+_-]*$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CONTROL_RE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function hasExactKeys(value, required, optional = []) {
  if (!isRecord(value)) return false;
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => Object.hasOwn(value, key))
    && Object.keys(value).every((key) => allowed.has(key));
}

function validText(value, max, { required = false } = {}) {
  return typeof value === 'string'
    && (!required || value.trim().length > 0)
    && value.length <= max
    && !CONTROL_RE.test(value);
}

function validIdentifier(value, max = 96) {
  return validText(value, max, { required: true }) && IDENTIFIER_RE.test(value);
}

function validInteger(value, max) {
  return Number.isSafeInteger(value) && value >= 0 && value <= max;
}

function validTimestamp(value) {
  if (!validText(value, 40, { required: true })) return false;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && new Date(parsed).toISOString() === value;
}

function validCountMap(value, keys) {
  return isRecord(value)
    && Object.keys(value).every((key) => keys.has(key) && validInteger(value[key], 1000));
}

function validateDiagnostics(value) {
  if (!hasExactKeys(
    value,
    ['schema_version', 'platform'],
    [
      'generated_at', 'version', 'hardware', 'runtime', 'resources',
      'recent_error_counts', 'recent_error_breadcrumbs',
    ],
  ) || value.schema_version !== 1) return false;

  if (value.generated_at !== undefined && !validTimestamp(value.generated_at)) return false;

  if (!hasExactKeys(value.platform, ['family'], ['python'])) return false;
  if (!['windows', 'linux', 'macos', 'other'].includes(value.platform.family)) return false;
  if (value.platform.python !== undefined && !/^\d{1,2}\.\d{1,2}$/.test(value.platform.python)) return false;

  if (value.version !== undefined) {
    if (!hasExactKeys(value.version, [], ['backend_version', 'profile_schema_version', 'config_version'])) return false;
    if (value.version.backend_version !== undefined && !validIdentifier(value.version.backend_version, 64)) return false;
    for (const key of ['profile_schema_version', 'config_version']) {
      if (value.version[key] !== undefined && !validInteger(value.version[key], 10_000)) return false;
    }
  }

  if (value.hardware !== undefined) {
    if (!hasExactKeys(value.hardware, [], ['tier', 'gpu_acceleration_available'])) return false;
    if (value.hardware.tier !== undefined && !HARDWARE_TIERS.has(value.hardware.tier)) return false;
    if (value.hardware.gpu_acceleration_available !== undefined
      && typeof value.hardware.gpu_acceleration_available !== 'boolean') return false;
  }

  if (value.runtime !== undefined) {
    if (!hasExactKeys(value.runtime, [], ['llm', 'stt', 'tts'])) return false;
    if (value.runtime.llm !== undefined) {
      const llm = value.runtime.llm;
      if (!hasExactKeys(llm, [], [
        'status', 'runtime_build', 'required_runtime_build',
        'validation_elapsed_sec', 'validation_timeout_sec', 'error_code',
      ])) return false;
      if (llm.status !== undefined && !LLM_STATUSES.has(llm.status)) return false;
      for (const key of ['runtime_build', 'required_runtime_build']) {
        if (llm[key] !== undefined && !validInteger(llm[key], 1_000_000_000)) return false;
      }
      for (const key of ['validation_elapsed_sec', 'validation_timeout_sec']) {
        if (llm[key] !== undefined
          && (!Number.isFinite(llm[key]) || llm[key] < 0 || llm[key] > 86_400)) return false;
      }
      if (llm.error_code !== undefined && !ERROR_CODES.has(llm.error_code)) return false;
    }
    if (value.runtime.stt !== undefined) {
      const stt = value.runtime.stt;
      if (!hasExactKeys(stt, [], [
        'initialized', 'loaded', 'constructed', 'probe_passed',
        'inference_ready', 'device_fallback_code',
      ])) return false;
      for (const key of ['initialized', 'loaded', 'constructed', 'probe_passed', 'inference_ready']) {
        if (stt[key] !== undefined && typeof stt[key] !== 'boolean') return false;
      }
      if (stt.device_fallback_code !== undefined
        && stt.device_fallback_code !== 'cuda_runtime_missing') return false;
    }
    if (value.runtime.tts !== undefined) {
      const tts = value.runtime.tts;
      if (!hasExactKeys(tts, [], ['initialized', 'loaded'])) return false;
      for (const key of ['initialized', 'loaded']) {
        if (tts[key] !== undefined && typeof tts[key] !== 'boolean') return false;
      }
    }
  }

  if (value.resources !== undefined) {
    if (!hasExactKeys(value.resources, ['resident_model_count'])) return false;
    if (!validInteger(value.resources.resident_model_count, 64)) return false;
  }

  if (value.recent_error_counts !== undefined) {
    const counts = value.recent_error_counts;
    if (!hasExactKeys(counts, ['total'], ['by_severity', 'by_component'])) return false;
    if (!validInteger(counts.total, 1000)) return false;
    if (counts.by_severity !== undefined && !validCountMap(counts.by_severity, SEVERITIES)) return false;
    if (counts.by_component !== undefined && !validCountMap(counts.by_component, COMPONENTS)) return false;
  }

  if (value.recent_error_breadcrumbs !== undefined) {
    if (!Array.isArray(value.recent_error_breadcrumbs)
      || value.recent_error_breadcrumbs.length > 15) return false;
    for (const crumb of value.recent_error_breadcrumbs) {
      if (!hasExactKeys(crumb, ['component', 'severity'], ['created_at', 'code'])) return false;
      if (!COMPONENTS.has(crumb.component) || !SEVERITIES.has(crumb.severity)) return false;
      if (crumb.created_at !== undefined && !validTimestamp(crumb.created_at)) return false;
      if (crumb.code !== undefined && !validIdentifier(crumb.code, 96)) return false;
    }
  }
  return true;
}

export function validateEnvelope(value) {
  if (!hasExactKeys(value, ['schema_version', 'channel', 'report'])) return false;
  if (value.schema_version !== 1 || !CHANNELS.has(value.channel)) return false;
  const report = value.report;
  if (!hasExactKeys(
    report,
    ['schema_version', 'report_id', 'created_at', 'privacy_note', 'bug', 'automatic_diagnostics'],
  )) return false;
  if (report.schema_version !== 1 || !UUID_RE.test(report.report_id)) return false;
  if (!validTimestamp(report.created_at) || report.privacy_note !== PRIVACY_NOTE) return false;
  if (!hasExactKeys(report.bug, ['summary', 'steps', 'expected', 'actual'], ['contact'])) return false;
  if (!validText(report.bug.summary, 160, { required: true })) return false;
  if (!validText(report.bug.steps, 4000) || !validText(report.bug.expected, 4000)) return false;
  if (!validText(report.bug.actual, 4000, { required: true })) return false;
  if (report.bug.contact !== undefined && !validText(report.bug.contact, 254, { required: true })) return false;
  if (!validateDiagnostics(report.automatic_diagnostics)) return false;
  return new TextEncoder().encode(JSON.stringify(report)).byteLength <= MAX_REPORT_BYTES;
}

function responseJson(status, body, requestId, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
      'x-request-id': requestId,
      ...extraHeaders,
    },
  });
}

function neutralizeMentions(value) {
  return String(value)
    .replace(/@(everyone|here)\b/gi, '@\u200b$1')
    .replace(/<@/g, '<@\u200b');
}

function validDiscordWebhook(raw) {
  try {
    const url = new URL(String(raw || ''));
    const parts = url.pathname.split('/').filter(Boolean);
    const host = url.hostname.toLowerCase();
    return url.protocol === 'https:'
      && (host === 'discord.com' || host === 'www.discord.com' || host === 'discordapp.com')
      && parts.length === 4
      && parts[0] === 'api'
      && parts[1] === 'webhooks'
      && /^\d+$/.test(parts[2])
      && parts[3].length >= 20
      && !url.username
      && !url.password
      && !url.search
      && !url.hash
      ? url
      : null;
  } catch {
    return null;
  }
}

function timeoutSignal(milliseconds) {
  return typeof globalThis.AbortSignal?.timeout === 'function'
    ? globalThis.AbortSignal.timeout(milliseconds)
    : undefined;
}

async function deliverDiscord(report, env, fetchImpl) {
  const webhook = validDiscordWebhook(env.DISCORD_WEBHOOK_URL);
  if (!webhook) return { configured: false, ok: false };
  webhook.searchParams.set('wait', 'true');
  const form = new FormData();
  form.set('payload_json', JSON.stringify({
    content: `New BetterFingers bug report \`${report.report_id}\`\n**Summary:** ${neutralizeMentions(report.bug.summary)}`.slice(0, 1800),
    allowed_mentions: { parse: [] },
  }));
  form.set(
    'files[0]',
    new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }),
    `betterfingers-${report.report_id}.json`,
  );
  const upstream = await fetchImpl(webhook.toString(), {
    method: 'POST',
    redirect: 'error',
    body: form,
    signal: timeoutSignal(10_000),
  });
  return { configured: true, ok: upstream.status >= 200 && upstream.status < 300 };
}

function validEmail(value) {
  return validText(value, 254, { required: true }) && EMAIL_RE.test(value);
}

function emailText(report) {
  const fields = [
    'BetterFingers bug report',
    `Report ID: ${report.report_id}`,
    `Created: ${report.created_at}`,
    '',
    `Summary:\n${report.bug.summary}`,
    `Steps to reproduce:\n${report.bug.steps || '(not supplied)'}`,
    `Expected behavior:\n${report.bug.expected || '(not supplied)'}`,
    `Actual behavior:\n${report.bug.actual}`,
  ];
  if (report.bug.contact) fields.push(`Contact:\n${report.bug.contact}`);
  fields.push('', 'Automatic diagnostics:', JSON.stringify(report.automatic_diagnostics, null, 2));
  return fields.join('\n\n');
}

async function deliverEmail(report, env, fetchImpl) {
  if (!validText(env.RESEND_API_KEY, 256, { required: true })
    || !validEmail(env.BUG_REPORT_EMAIL_TO)
    || !validEmail(env.BUG_REPORT_EMAIL_FROM)) {
    return { configured: false, ok: false };
  }
  const upstream = await fetchImpl('https://api.resend.com/emails', {
    method: 'POST',
    redirect: 'error',
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      'content-type': 'application/json',
      'idempotency-key': `betterfingers-${report.report_id}`,
    },
    body: JSON.stringify({
      from: env.BUG_REPORT_EMAIL_FROM,
      to: [env.BUG_REPORT_EMAIL_TO],
      subject: `BetterFingers bug: ${report.bug.summary.replace(/[\r\n]+/g, ' ').slice(0, 100)}`,
      text: emailText(report),
    }),
    signal: timeoutSignal(10_000),
  });
  return { configured: true, ok: upstream.status >= 200 && upstream.status < 300 };
}

async function parseBody(request) {
  const contentType = String(request.headers.get('content-type') || '').toLowerCase();
  const contentEncoding = String(request.headers.get('content-encoding') || '').toLowerCase();
  const declared = Number(request.headers.get('content-length') || 0);
  if (!contentType.startsWith('application/json')) throw new Error('content_type');
  if (contentEncoding && contentEncoding !== 'identity') throw new Error('content_encoding');
  if (Number.isFinite(declared) && declared > MAX_REQUEST_BYTES) throw new Error('too_large');
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength > MAX_REQUEST_BYTES) throw new Error('too_large');
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    throw new Error('invalid_utf8');
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('invalid_json');
  }
}

function configStatus(env) {
  return {
    discord: Boolean(validDiscordWebhook(env.DISCORD_WEBHOOK_URL)),
    email: Boolean(
      validText(env.RESEND_API_KEY, 256, { required: true })
      && validEmail(env.BUG_REPORT_EMAIL_TO)
      && validEmail(env.BUG_REPORT_EMAIL_FROM),
    ),
    rate_limit: typeof env.BUG_REPORT_RATE_LIMITER?.limit === 'function',
    dedupe: typeof env.BUG_REPORT_DEDUPE?.get === 'function'
      && typeof env.BUG_REPORT_DEDUPE?.put === 'function',
  };
}

export function createRelay({
  fetchImpl = globalThis.fetch,
  randomUUID = () => globalThis.crypto.randomUUID(),
} = {}) {
  return {
    async fetch(request, env = {}) {
      const requestId = randomUUID();
      const url = new URL(request.url);
      if (request.headers.get('origin')) {
        return responseJson(403, { ok: false, error: 'browser_origin_refused', request_id: requestId }, requestId);
      }
      if (url.pathname === '/health' && request.method === 'GET') {
        return responseJson(200, { ok: true, configured: configStatus(env), request_id: requestId }, requestId);
      }
      if (url.pathname !== '/report') {
        return responseJson(404, { ok: false, error: 'not_found', request_id: requestId }, requestId);
      }
      if (request.method !== 'POST') {
        return responseJson(405, { ok: false, error: 'method_not_allowed', request_id: requestId }, requestId, { allow: 'POST' });
      }

      const clientKey = request.headers.get('cf-connecting-ip')
        || (env.ALLOW_LOCAL_REQUESTS === 'true' ? 'local-development' : '');
      if (!clientKey) {
        return responseJson(403, { ok: false, error: 'edge_identity_required', request_id: requestId }, requestId);
      }
      if (typeof env.BUG_REPORT_RATE_LIMITER?.limit !== 'function') {
        return responseJson(503, { ok: false, error: 'relay_not_configured', request_id: requestId }, requestId);
      }
      try {
        const limited = await env.BUG_REPORT_RATE_LIMITER.limit({ key: `bug-report:${clientKey}` });
        if (!limited?.success) {
          return responseJson(429, { ok: false, error: 'rate_limited', request_id: requestId }, requestId, { 'retry-after': '60' });
        }
      } catch {
        return responseJson(503, { ok: false, error: 'rate_limit_unavailable', request_id: requestId }, requestId);
      }

      let envelope;
      try {
        envelope = await parseBody(request);
      } catch (error) {
        const tooLarge = error?.message === 'too_large';
        return responseJson(tooLarge ? 413 : 400, {
          ok: false,
          error: tooLarge ? 'request_too_large' : 'invalid_request',
          request_id: requestId,
        }, requestId);
      }
      if (!validateEnvelope(envelope)) {
        return responseJson(400, { ok: false, error: 'invalid_report', request_id: requestId }, requestId);
      }

      const configuration = configStatus(env);
      if (!configuration.dedupe || !configuration[envelope.channel]) {
        return responseJson(503, { ok: false, error: 'destination_not_configured', request_id: requestId }, requestId);
      }

      const dedupeKey = `v1:${envelope.channel}:${envelope.report.report_id}`;
      let prior;
      try {
        prior = await env.BUG_REPORT_DEDUPE.get(dedupeKey);
      } catch {
        return responseJson(503, { ok: false, error: 'dedupe_unavailable', request_id: requestId }, requestId);
      }
      if (prior === 'delivered') {
        return responseJson(200, {
          ok: true, status: 'duplicate', channel: envelope.channel, request_id: requestId,
        }, requestId);
      }
      if (prior === 'processing') {
        return responseJson(409, { ok: false, error: 'already_processing', request_id: requestId }, requestId);
      }
      try {
        await env.BUG_REPORT_DEDUPE.put(dedupeKey, 'processing', {
          expirationTtl: PROCESSING_TTL_SECONDS,
        });
      } catch {
        return responseJson(503, { ok: false, error: 'dedupe_unavailable', request_id: requestId }, requestId);
      }

      let delivery;
      try {
        delivery = envelope.channel === 'discord'
          ? await deliverDiscord(envelope.report, env, fetchImpl)
          : await deliverEmail(envelope.report, env, fetchImpl);
      } catch {
        delivery = { configured: true, ok: false };
      }
      if (!delivery.configured || !delivery.ok) {
        try { await env.BUG_REPORT_DEDUPE.delete?.(dedupeKey); } catch { /* TTL releases it */ }
        return responseJson(502, { ok: false, error: 'delivery_failed', request_id: requestId }, requestId);
      }

      try {
        await env.BUG_REPORT_DEDUPE.put(dedupeKey, 'delivered', {
          expirationTtl: DELIVERED_TTL_SECONDS,
        });
      } catch {
        // The provider already accepted the report. Returning failure here
        // would encourage an immediate duplicate, so keep the honest success.
      }
      return responseJson(202, {
        ok: true, status: 'accepted', channel: envelope.channel, request_id: requestId,
      }, requestId);
    },
  };
}

export default createRelay();
