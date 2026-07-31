// Pure latency/throughput probe primitives. The renderer supplies real stage
// runners; this module never invents work, sleeps, or turns a missing metric
// into zero. It is deliberately usable without a DOM for unit tests.

export const PROBE_STAGE_NAMES = Object.freeze(['stt', 'rewrite', 'tts']);

// The hard bound is part of the result so an operator can see exactly how much
// work a mode is allowed to do. Runs are sequential: local models are the
// constrained resource and an artificial concurrency fan-out would measure
// contention while risking the user's active instance.
export const PROBE_MODE_CONFIG = Object.freeze({
  light: Object.freeze({ runs: 3, maxRuns: 3, stageTimeoutMs: 15_000, maxDurationMs: 45_000 }),
  medium: Object.freeze({ runs: 8, maxRuns: 8, stageTimeoutMs: 15_000, maxDurationMs: 90_000 }),
  hard: Object.freeze({ runs: 12, maxRuns: 12, stageTimeoutMs: 15_000, maxDurationMs: 120_000 }),
});

export const LATENCY_PROBE_MODES = Object.freeze(Object.keys(PROBE_MODE_CONFIG));

const hasFiniteNumber = (value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));

function nowDefault() {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') return performance.now();
  return Date.now();
}

function stageMessage(error) {
  if (error instanceof Error) return error.message;
  return String(error || 'Stage failed.');
}

export function formatProbeMetric(value, unit = 'ms') {
  if (!hasFiniteNumber(value)) return 'not available';
  return `${Math.round(Number(value))}${unit}`;
}

export function formatProbeDuration(value) {
  return formatProbeMetric(value, 'ms');
}

/** Convert /doctor hardware payloads into a display-safe, measurement-only model. */
export function normalizeResourceMetrics(snapshot) {
  const source = snapshot || {};
  const hardware = source.hardware || source;
  const cpu = hardware.cpu || source.cpu || {};
  const memory = hardware.memory || source.memory || source.ram || {};
  const gpu = hardware.gpu || source.gpu || {};
  const cpuPercent = source.cpu_percent ?? source.cpu_usage_percent ?? cpu.usage_percent;
  const ramUsedPercent = memory.used_percent ?? source.ram_used_percent;
  const vramTotal = gpu.vram_mb ?? gpu.vram_total_mb ?? source.vram_total_mb;
  const vramUsed = gpu.vram_used_mb ?? source.vram_used_mb;
  return {
    cpu: { usagePercent: hasFiniteNumber(cpuPercent) ? Number(cpuPercent) : null },
    ram: {
      usedPercent: hasFiniteNumber(ramUsedPercent) ? Number(ramUsedPercent) : null,
      totalMb: hasFiniteNumber(memory.total_mb) ? Number(memory.total_mb) : null,
      availableMb: hasFiniteNumber(memory.available_mb) ? Number(memory.available_mb) : null,
    },
    gpu: {
      name: gpu.name || null,
      backend: gpu.backend || null,
      available: Boolean(gpu.name || gpu.backend || gpu.accelerated),
    },
    vram: {
      usedMb: hasFiniteNumber(vramUsed) ? Number(vramUsed) : null,
      totalMb: hasFiniteNumber(vramTotal) ? Number(vramTotal) : null,
      available: hasFiniteNumber(vramTotal) || hasFiniteNumber(vramUsed),
    },
  };
}

export function probeMetricValue(value) {
  return hasFiniteNumber(value) ? Number(value) : 'not available';
}

/** Run exactly one stage and retain timeout/failure duration as a result. */
export async function runProbeStage(name, task, {
  timeoutMs = 15_000,
  clock = nowDefault,
} = {}) {
  const startedAt = clock();
  if (typeof task !== 'function') {
    return {
      name,
      status: 'unavailable',
      durationMs: null,
      error: `No ${name} stage runner is configured.`,
    };
  }

  let timer;
  let timedOut = false;
  try {
    const work = Promise.resolve().then(() => task());
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => {
        timedOut = true;
        const error = new Error(`${name} stage timed out after ${timeoutMs}ms.`);
        error.code = 'PROBE_TIMEOUT';
        reject(error);
      }, timeoutMs);
    });
    const value = await Promise.race([work, timeout]);
    return { name, status: 'ok', durationMs: Math.max(0, clock() - startedAt), value };
  } catch (error) {
    const durationMs = Math.max(0, clock() - startedAt);
    return {
      name,
      status: timedOut || error?.code === 'PROBE_TIMEOUT' ? 'timed_out' : 'failed',
      durationMs,
      error: stageMessage(error),
    };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function summarizeStage(runs, name) {
  const stages = runs.map((run) => run.stages?.[name]).filter(Boolean);
  const measured = stages.map((stage) => stage.durationMs).filter(hasFiniteNumber).map(Number);
  const ok = stages.filter((stage) => stage.status === 'ok').length;
  const timedOut = stages.filter((stage) => stage.status === 'timed_out').length;
  const failed = stages.filter((stage) => stage.status === 'failed').length;
  return {
    count: stages.length,
    ok,
    failed,
    timedOut,
    unavailable: stages.filter((stage) => stage.status === 'unavailable').length,
    avgMs: measured.length ? measured.reduce((sum, value) => sum + value, 0) / measured.length : null,
    lastMs: measured.length ? measured[measured.length - 1] : null,
  };
}

export function summarizeProbeRuns(runs = []) {
  const summary = Object.fromEntries(PROBE_STAGE_NAMES.map((name) => [name, summarizeStage(runs, name)]));
  const measured = runs.map((run) => run.durationMs).filter(hasFiniteNumber).map(Number);
  summary.total = {
    count: measured.length,
    ok: measured.length,
    failed: 0,
    timedOut: 0,
    unavailable: 0,
    avgMs: measured.length ? measured.reduce((sum, value) => sum + value, 0) / measured.length : null,
    lastMs: measured.length ? measured[measured.length - 1] : null,
  };
  return summary;
}

/**
 * Execute bounded, sequential real stage runners.
 *
 * `stages` is an object whose values are functions receiving
 * `{mode, runIndex, sample, previous}`. A missing function is reported as
 * unavailable; it is never replaced with a delay or a guessed measurement.
 */
export async function runLatencyProbe({
  mode = 'light',
  stages = {},
  sample = 'A short local diagnostics sample.',
  metricsProvider,
  timeoutMs,
  maxDurationMs,
  clock = nowDefault,
  onRun,
} = {}) {
  const selectedMode = PROBE_MODE_CONFIG[mode] ? mode : 'light';
  const config = PROBE_MODE_CONFIG[selectedMode];
  const requestedRuns = Math.min(config.runs, config.maxRuns);
  const stageTimeoutMs = Number.isFinite(Number(timeoutMs)) ? Math.max(1, Number(timeoutMs)) : config.stageTimeoutMs;
  const durationBoundMs = Number.isFinite(Number(maxDurationMs)) ? Math.max(1, Number(maxDurationMs)) : config.maxDurationMs;
  const startedAt = clock();
  const runs = [];

  for (let runIndex = 0; runIndex < requestedRuns; runIndex += 1) {
    if (clock() - startedAt >= durationBoundMs) break;
    const runStartedAt = clock();
    const stagesForRun = {};
    let previous = {};
    for (const name of PROBE_STAGE_NAMES) {
      const result = await runProbeStage(
        name,
        typeof stages[name] === 'function'
          ? () => stages[name]({ mode: selectedMode, runIndex, sample, previous })
          : null,
        { timeoutMs: stageTimeoutMs, clock },
      );
      stagesForRun[name] = result;
      previous = { ...previous, [name]: result };
    }
    let resources = null;
    if (typeof metricsProvider === 'function') {
      try {
        resources = normalizeResourceMetrics(await metricsProvider({ mode: selectedMode, runIndex }));
      } catch (error) {
        resources = { error: stageMessage(error), ...normalizeResourceMetrics(null) };
      }
    } else {
      resources = normalizeResourceMetrics(null);
    }
    const run = {
      runIndex,
      durationMs: Math.max(0, clock() - runStartedAt),
      stages: stagesForRun,
      resources,
    };
    runs.push(run);
    onRun?.(run);
  }

  return {
    mode: selectedMode,
    requestedRuns,
    completedRuns: runs.length,
    runs,
    stages: summarizeProbeRuns(runs),
    elapsedMs: Math.max(0, clock() - startedAt),
    bound: {
      maxRuns: config.maxRuns,
      maxDurationMs: durationBoundMs,
      stageTimeoutMs,
      truncated: runs.length < requestedRuns,
    },
  };
}
