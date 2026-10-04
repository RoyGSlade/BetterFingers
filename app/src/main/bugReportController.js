'use strict';

const net = require('node:net');
const { randomUUID: nodeRandomUUID } = require('node:crypto');

const EMAIL_FALLBACK = 'donavencrenshaw@gmail.com';
const DISCORD_FALLBACK = 'https://discord.gg/m3HH45CFwz';
const PREVIEW_TTL_MS = 10 * 60 * 1000;
const DIRECT_COOLDOWN_MS = 60 * 1000;
const MAX_REPORT_BYTES = 32 * 1024;
const MAX_RELAY_ACK_BYTES = 4 * 1024;
const MAX_ACTIVE_PREVIEWS = 20;

const LLM_STATUSES = new Set([
  'disabled',
  'missing_llama_server',
  'missing_model',
  'runtime_validation_timeout',
  'runtime_invalid',
  'runtime_link_failure',
  'runtime_outdated',
  'ready',
  'startup_failure',
  'not_loaded',
]);
const RUNTIME_ERROR_CODES = new Set([
  'runtime_validation_timeout',
  'runtime_link_failure',
  'runtime_outdated',
  'runtime_invalid',
]);
const HARDWARE_TIERS = ['dgpu-12g+', 'dgpu-8g', 'igpu', 'cpu-only'];
// Keep this vocabulary aligned with server.record_runtime_error(). `error` is
// retained for forward compatibility with older/newer sidecars, but the live
// backend currently emits recoverable/fatal for its two failure levels.
const ERROR_SEVERITIES = new Set(['info', 'warning', 'recoverable', 'fatal', 'error']);
const ERROR_COMPONENTS = new Set([
  'diagnostics',
  'hotkeys',
  'llm',
  'recording',
  'review',
  'selection_rewrite',
  'stt',
  'tts',
]);
const MAX_ERROR_BREADCRUMBS = 15;

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function boundedText(value, maxLength) {
  return String(value ?? '')
    .replace(/\r\n?/g, '\n')
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
    .trim()
    .slice(0, maxLength);
}

function neutralizeDiscordMentions(value) {
  return String(value)
    .replace(/@(everyone|here)\b/gi, '@\u200b$1')
    .replace(/<@/g, '<@\u200b');
}

function boundedIdentifier(value, maxLength = 64) {
  const candidate = String(value ?? '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9.+_-]*$/.test(candidate) && candidate.length <= maxLength
    ? candidate
    : undefined;
}

function boundedInteger(value, max = 1_000_000_000) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 && number <= max ? number : undefined;
}

function boundedNumber(value, max = 86_400) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= max
    ? Math.round(number * 1000) / 1000
    : undefined;
}

function normalizedTimestamp(value) {
  const timestamp = Date.parse(String(value ?? ''));
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : undefined;
}

function normalizedPlatform(value) {
  const candidate = String(value ?? '').trim().toLowerCase();
  if (candidate === 'windows') return 'windows';
  if (candidate === 'linux') return 'linux';
  if (candidate === 'darwin' || candidate === 'macos') return 'macos';
  return 'other';
}

function normalizedPython(value) {
  const match = String(value ?? '').match(/^(\d{1,2})\.(\d{1,2})(?:\D|$)/);
  return match ? `${match[1]}.${match[2]}` : undefined;
}

function normalizedHardwareTier(value) {
  const candidate = String(value ?? '').trim().toLowerCase();
  for (const tier of HARDWARE_TIERS) {
    if (candidate === tier || candidate.includes(`(${tier})`) || candidate.includes(tier)) return tier;
  }
  return undefined;
}

function copyBoolean(target, key, value) {
  if (typeof value === 'boolean') target[key] = value;
}

// This is the network privacy boundary. It deliberately does not reuse the
// rich Markdown support report, which is meant for a person to review and
// contains exact paths, hardware/model identifiers, and error text.
function curatedDiagnostics(raw) {
  const source = isRecord(raw) ? raw : {};
  const diagnostics = { schema_version: 1 };

  const generatedAt = normalizedTimestamp(source.generated_at);
  if (generatedAt) diagnostics.generated_at = generatedAt;

  if (isRecord(source.version)) {
    const version = {};
    const backendVersion = boundedIdentifier(source.version.backend_version);
    const profileSchema = boundedInteger(source.version.profile_schema_version, 10_000);
    const configSchema = boundedInteger(source.version.config_version, 10_000);
    if (backendVersion) version.backend_version = backendVersion;
    if (profileSchema !== undefined) version.profile_schema_version = profileSchema;
    if (configSchema !== undefined) version.config_version = configSchema;
    if (Object.keys(version).length) diagnostics.version = version;
  }

  const platform = isRecord(source.platform) ? source.platform : {};
  diagnostics.platform = { family: normalizedPlatform(platform.system) };
  const python = normalizedPython(platform.python);
  if (python) diagnostics.platform.python = python;

  const hardware = {};
  const tier = normalizedHardwareTier(source.hardware_tier);
  if (tier) hardware.tier = tier;
  const rawHardware = isRecord(source.hardware) ? source.hardware : {};
  if (isRecord(rawHardware.gpu)) {
    const kind = String(rawHardware.gpu.kind ?? '').trim().toLowerCase();
    hardware.gpu_acceleration_available = Boolean(
      rawHardware.gpu.accelerated
      || rawHardware.gpu.available
      || ['cuda', 'discrete', 'integrated'].includes(kind),
    );
  }
  if (Object.keys(hardware).length) diagnostics.hardware = hardware;

  const runtimeSource = isRecord(source.runtime) ? source.runtime : {};
  const runtime = {};
  if (isRecord(runtimeSource.llm)) {
    const llm = {};
    const status = String(runtimeSource.llm.runtime_status ?? '').trim().toLowerCase();
    if (LLM_STATUSES.has(status)) llm.status = status;
    const build = boundedInteger(runtimeSource.llm.runtime_build);
    const requiredBuild = boundedInteger(runtimeSource.llm.required_runtime_build);
    const elapsed = boundedNumber(runtimeSource.llm.runtime_validation_elapsed_sec);
    const timeout = boundedNumber(runtimeSource.llm.runtime_validation_timeout_sec);
    const errorCode = String(runtimeSource.llm.runtime_validation_error_code ?? '').trim().toLowerCase();
    if (build !== undefined) llm.runtime_build = build;
    if (requiredBuild !== undefined) llm.required_runtime_build = requiredBuild;
    if (elapsed !== undefined) llm.validation_elapsed_sec = elapsed;
    if (timeout !== undefined) llm.validation_timeout_sec = timeout;
    if (RUNTIME_ERROR_CODES.has(errorCode)) llm.error_code = errorCode;
    if (Object.keys(llm).length) runtime.llm = llm;
  }
  if (isRecord(runtimeSource.stt)) {
    const stt = {};
    for (const key of ['initialized', 'loaded', 'constructed', 'probe_passed', 'inference_ready']) {
      copyBoolean(stt, key, runtimeSource.stt[key]);
    }
    if (runtimeSource.stt.device_fallback_code === 'cuda_runtime_missing') {
      stt.device_fallback_code = 'cuda_runtime_missing';
    }
    if (Object.keys(stt).length) runtime.stt = stt;
  }
  if (isRecord(runtimeSource.tts)) {
    const tts = {};
    copyBoolean(tts, 'initialized', runtimeSource.tts.initialized);
    copyBoolean(tts, 'loaded', runtimeSource.tts.loaded);
    if (Object.keys(tts).length) runtime.tts = tts;
  }
  if (Object.keys(runtime).length) diagnostics.runtime = runtime;

  const ledger = isRecord(source.resources) && isRecord(source.resources.ledger)
    ? source.resources.ledger
    : null;
  if (ledger) {
    diagnostics.resources = {
      resident_model_count: Math.min(Object.values(ledger).filter(Boolean).length, 64),
    };
  }

  if (Array.isArray(source.recent_errors)) {
    const counts = { total: Math.min(source.recent_errors.length, 1000) };
    const bySeverity = {};
    const byComponent = {};
    const recent = source.recent_errors.slice(-1000);
    for (const entry of recent) {
      const severity = String(isRecord(entry) ? entry.severity : '').trim().toLowerCase();
      if (ERROR_SEVERITIES.has(severity)) bySeverity[severity] = (bySeverity[severity] || 0) + 1;
      const component = String(isRecord(entry) ? entry.component : '').trim().toLowerCase();
      if (ERROR_COMPONENTS.has(component)) byComponent[component] = (byComponent[component] || 0) + 1;
    }
    if (Object.keys(bySeverity).length) counts.by_severity = bySeverity;
    if (Object.keys(byComponent).length) counts.by_component = byComponent;
    diagnostics.recent_error_counts = counts;

    // This is the automatic report's flight recorder. It deliberately carries
    // no free-form message or details object: only fixed-vocabulary fields and
    // message values that are themselves safe machine identifiers survive.
    const breadcrumbs = [];
    for (const entry of recent.slice(-MAX_ERROR_BREADCRUMBS)) {
      if (!isRecord(entry)) continue;
      const component = String(entry.component ?? '').trim().toLowerCase();
      const severity = String(entry.severity ?? '').trim().toLowerCase();
      if (!ERROR_COMPONENTS.has(component) || !ERROR_SEVERITIES.has(severity)) continue;
      const breadcrumb = { component, severity };
      const createdAt = normalizedTimestamp(entry.created_at);
      const code = boundedIdentifier(entry.message, 96);
      if (createdAt) breadcrumb.created_at = createdAt;
      if (code) breadcrumb.code = code;
      breadcrumbs.push(breadcrumb);
    }
    if (breadcrumbs.length) diagnostics.recent_error_breadcrumbs = breadcrumbs;
  }

  return diagnostics;
}

function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

function isPrivateIpv4(hostname) {
  const parts = hostname.split('.').map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return true;
  const [a, b] = parts;
  return a === 0
    || a === 10
    || a === 127
    || (a === 100 && b >= 64 && b <= 127)
    || (a === 169 && b === 254)
    || (a === 172 && b >= 16 && b <= 31)
    || (a === 192 && b === 168)
    || (a === 198 && (b === 18 || b === 19))
    || a >= 224;
}

function isPrivateHostname(value) {
  const hostname = String(value ?? '').toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
  if (!hostname || hostname === 'localhost' || hostname.endsWith('.localhost') || hostname.endsWith('.local') || hostname.endsWith('.internal')) return true;
  const ipVersion = net.isIP(hostname);
  if (ipVersion === 4) return isPrivateIpv4(hostname);
  if (ipVersion === 6) {
    if (hostname.startsWith('::ffff:')) {
      const mapped = hostname.slice('::ffff:'.length);
      return net.isIP(mapped) !== 4 || isPrivateIpv4(mapped);
    }
    const first = Number.parseInt(hostname.split(':')[0] || '0', 16);
    return hostname === '::' || hostname === '::1' || (first & 0xfe00) === 0xfc00 || (first & 0xffc0) === 0xfe80 || (first & 0xff00) === 0xff00;
  }
  return false;
}

function endpointFrom(env) {
  const raw = String(env?.BETTERFINGERS_BUG_REPORT_ENDPOINT ?? '').trim();
  if (!raw || raw.length > 2048) return null;
  try {
    const url = new URL(raw);
    const hostname = url.hostname.toLowerCase().replace(/\.$/, '');
    const isDiscord = hostname === 'discord.com'
      || hostname === 'www.discord.com'
      || hostname === 'discordapp.com'
      || hostname.endsWith('.discord.com');
    if (
      url.protocol !== 'https:'
      || url.username
      || url.password
      || url.hash
      || url.search
      || (url.port && url.port !== '443')
      || isPrivateHostname(hostname)
      || (isDiscord && url.pathname.toLowerCase().includes('/api/webhooks'))
    ) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function readRelayConfig(env) {
  const endpoint = endpointFrom(env);
  const channels = new Set(
    String(env?.BETTERFINGERS_BUG_REPORT_CHANNELS ?? '')
      .split(',')
      .map((value) => value.trim().toLowerCase())
      .filter((value) => value === 'discord' || value === 'email'),
  );
  return { endpoint, channels };
}

async function readRelayAcknowledgement(response, expectedChannel) {
  if (!response || response.status < 200 || response.status >= 300) return null;
  if (typeof response.text !== 'function') return null;
  const contentType = String(response.headers?.get?.('content-type') ?? '').toLowerCase();
  if (!contentType.startsWith('application/json')) return null;
  let text;
  try {
    text = await response.text();
  } catch {
    return null;
  }
  if (!text || Buffer.byteLength(text, 'utf8') > MAX_RELAY_ACK_BYTES) return null;
  let acknowledgement;
  try {
    acknowledgement = JSON.parse(text);
  } catch {
    return null;
  }
  const requestId = String(acknowledgement?.request_id ?? '');
  const status = String(acknowledgement?.status ?? '');
  if (
    acknowledgement?.ok !== true
    || acknowledgement?.channel !== expectedChannel
    || !['accepted', 'duplicate'].includes(status)
    || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(requestId)
  ) return null;
  return { requestId, relayStatus: status };
}

function createBugReportController({
  backendProxy,
  dialog,
  shell,
  clipboard,
  fetch: fetchImpl = globalThis.fetch,
  env = process.env,
  clock = Date.now,
  randomUUID = nodeRandomUUID,
  timers = { setTimeout, clearTimeout },
} = {}) {
  const previews = new Map();
  const inFlight = new Set();
  let lastDirectAt = -Infinity;
  const now = () => Number(typeof clock === 'function' ? clock() : clock);

  function purgeExpired() {
    const current = now();
    for (const [id, preview] of previews) {
      if (!preview || current >= preview.expiresAt) previews.delete(id);
    }
  }

  function publicConfig() {
    const relay = readRelayConfig(env);
    const directDiscord = Boolean(relay.endpoint && relay.channels.has('discord'));
    const directEmail = Boolean(relay.endpoint && relay.channels.has('email'));
    return deepFreeze({
      direct: directDiscord || directEmail,
      directDiscord,
      directEmail,
      fallbacks: { email: EMAIL_FALLBACK, discord: DISCORD_FALLBACK },
    });
  }

  async function confirmAction(preview, direct, channel) {
    if (!dialog || typeof dialog.showMessageBox !== 'function') {
      throw new Error('System confirmation is unavailable; no report was sent or opened.');
    }
    const verb = direct ? 'Send report' : 'Copy and open';
    const target = channel === 'discord' ? 'Discord' : 'your email client';
    return dialog.showMessageBox({
      type: 'question',
      title: direct ? 'Send bug report?' : 'Hand off bug report?',
      message: direct
        ? `Send this reviewed report to BetterFingers support by ${channel}?`
        : `Copy this reviewed report and open ${target}?`,
      detail: preview.previewText,
      buttons: [verb, 'Cancel'],
      defaultId: 1,
      cancelId: 1,
      noLink: true,
    });
  }

  return {
    getConfig: publicConfig,

    async prepare(form = {}) {
      if (!backendProxy || typeof backendProxy.request !== 'function') {
        throw new Error('Diagnostics backend unavailable.');
      }
      const safeForm = {
        summary: neutralizeDiscordMentions(boundedText(form?.summary, 160)),
        steps: neutralizeDiscordMentions(boundedText(form?.steps, 4000)),
        expected: neutralizeDiscordMentions(boundedText(form?.expected, 4000)),
        actual: neutralizeDiscordMentions(boundedText(form?.actual, 4000)),
      };
      const contact = neutralizeDiscordMentions(boundedText(form?.contact, 254));
      if (contact) safeForm.contact = contact;
      if (!safeForm.summary || !safeForm.actual) {
        throw new Error('Summary and actual behavior are required.');
      }

      const response = await backendProxy.request({
        method: 'GET',
        path: '/diagnostics/support-report',
        timeoutMs: 15_000,
      });
      if (!response || response.ok === false || (response.status !== undefined && response.status >= 400)) {
        throw new Error('Unable to collect automatic diagnostics.');
      }
      const responseBody = isRecord(response.body) ? response.body : response;
      const rawReport = isRecord(responseBody.report) ? responseBody.report : {};

      purgeExpired();
      while (previews.size >= MAX_ACTIVE_PREVIEWS) previews.delete(previews.keys().next().value);
      let previewId = String(typeof randomUUID === 'function' ? randomUUID() : nodeRandomUUID());
      while (!previewId || previews.has(previewId)) previewId = nodeRandomUUID();
      const createdAt = new Date(now()).toISOString();
      const report = deepFreeze({
        schema_version: 1,
        report_id: previewId,
        created_at: createdAt,
        privacy_note: 'Automatic diagnostics exclude transcripts, drafts, audio, wake phrases, clipboard data, screenshots, raw logs, filesystem paths, exact hardware identifiers, exact model identifiers, and error messages.',
        bug: safeForm,
        automatic_diagnostics: curatedDiagnostics(rawReport),
      });
      const compact = JSON.stringify(report);
      if (Buffer.byteLength(compact, 'utf8') > MAX_REPORT_BYTES) {
        throw new Error('This report is too large. Shorten the reproduction details and try again.');
      }
      const preview = deepFreeze({
        previewId,
        expiresAt: now() + PREVIEW_TTL_MS,
        previewText: JSON.stringify(report, null, 2),
        report,
      });
      previews.set(previewId, preview);
      return deepFreeze({
        previewId: preview.previewId,
        expiresAt: preview.expiresAt,
        previewText: preview.previewText,
      });
    },

    async submit({ previewId, destination } = {}) {
      const allowed = new Set(['direct-discord', 'direct-email', 'email', 'discord']);
      if (!allowed.has(destination)) throw new Error('Unsupported bug-report destination.');
      purgeExpired();
      const id = typeof previewId === 'string' && previewId.length <= 128 ? previewId : '';
      const preview = previews.get(id);
      if (!preview) throw new Error('Bug-report preview expired. Prepare and review it again.');
      if (inFlight.has(id)) return { delivered: false, status: 'in_progress' };

      const direct = destination.startsWith('direct-');
      const channel = direct ? destination.slice('direct-'.length) : destination;
      const relay = readRelayConfig(env);
      if (direct && (!relay.endpoint || !relay.channels.has(channel))) {
        throw new Error('Direct delivery is not configured for this destination.');
      }
      if (direct && now() - lastDirectAt < DIRECT_COOLDOWN_MS) {
        return { delivered: false, status: 'rate_limited' };
      }

      inFlight.add(id);
      try {
        const confirmation = await confirmAction(preview, direct, channel);
        if (!confirmation || confirmation.response !== 0) {
          return { delivered: false, status: 'cancelled' };
        }

        if (direct) {
          if (typeof fetchImpl !== 'function') return { delivered: false, status: 'delivery_failed' };
          lastDirectAt = now();
          const abortController = new AbortController();
          const timer = timers.setTimeout(() => abortController.abort(), 10_000);
          try {
            const response = await fetchImpl(relay.endpoint, {
              method: 'POST',
              redirect: 'error',
              cache: 'no-store',
              credentials: 'omit',
              referrerPolicy: 'no-referrer',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ schema_version: 1, channel, report: preview.report }),
              signal: abortController.signal,
            });
            const acknowledgement = await readRelayAcknowledgement(response, channel);
            if (!acknowledgement) {
              return { delivered: false, status: 'delivery_failed' };
            }
            previews.delete(id);
            return { delivered: true, status: 'delivered', ...acknowledgement };
          } catch {
            return { delivered: false, status: abortController.signal.aborted ? 'delivery_timeout' : 'delivery_failed' };
          } finally {
            timers.clearTimeout(timer);
          }
        }

        if (!clipboard || typeof clipboard.writeText !== 'function') {
          return { delivered: false, status: 'fallback_failed' };
        }
        clipboard.writeText(preview.previewText);
        if (!shell || typeof shell.openExternal !== 'function') {
          return { delivered: false, status: 'copied_open_failed' };
        }
        const target = channel === 'email'
          ? `mailto:${EMAIL_FALLBACK}?subject=${encodeURIComponent('BetterFingers bug report')}`
          : DISCORD_FALLBACK;
        try {
          await shell.openExternal(target);
          return {
            delivered: false,
            status: channel === 'email' ? 'copied_opened_email' : 'copied_opened_discord',
          };
        } catch {
          return { delivered: false, status: 'copied_open_failed' };
        }
      } finally {
        inFlight.delete(id);
      }
    },
  };
}

module.exports = { createBugReportController };
