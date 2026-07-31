import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PROBE_MODE_CONFIG,
  formatProbeMetric,
  normalizeResourceMetrics,
  runProbeStage,
  runLatencyProbe,
} from '../src/renderer/lib/latencyProbe.mjs';

test('a timed-out stage is retained with its measured duration', async () => {
  const result = await runProbeStage('rewrite', () => new Promise(() => {}), { timeoutMs: 5 });
  assert.equal(result.status, 'timed_out');
  assert.match(result.error, /timed out/i);
  assert.ok(result.durationMs >= 0);
});

test('unavailable hardware metrics render as not available, never zero', () => {
  const metrics = normalizeResourceMetrics({ hardware: { gpu: { name: 'Intel Iris Xe', vram_mb: null }, memory: {} } });
  assert.equal(formatProbeMetric(metrics.cpu.usagePercent, '%'), 'not available');
  assert.equal(formatProbeMetric(metrics.vram.totalMb, ' MB'), 'not available');
  assert.notEqual(metrics.vram.totalMb, 0);
  assert.equal(metrics.gpu.name, 'Intel Iris Xe');
});

test('probe modes differ in real work count and expose the hard bound', async () => {
  const counts = {};
  for (const mode of ['light', 'medium', 'hard']) {
    let calls = 0;
    const stage = async () => { calls += 1; return calls; };
    const result = await runLatencyProbe({ mode, stages: { stt: stage, rewrite: stage, tts: stage } });
    counts[mode] = calls;
    assert.equal(result.completedRuns, PROBE_MODE_CONFIG[mode].runs);
    assert.equal(result.bound.maxRuns, PROBE_MODE_CONFIG[mode].maxRuns);
    assert.equal(result.stages.total.count, result.completedRuns);
  }
  assert.ok(counts.light < counts.medium && counts.medium < counts.hard);
});

test('a missing stage runner is an explicit unavailable result', async () => {
  const result = await runLatencyProbe({ mode: 'light' });
  assert.equal(result.runs[0].stages.stt.status, 'unavailable');
  assert.equal(result.stages.stt.unavailable, PROBE_MODE_CONFIG.light.runs);
});
