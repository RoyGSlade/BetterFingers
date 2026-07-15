// Doctor/diagnostics warning scenarios -- Phase 2 (D2 item 4). Shapes per
// model-lifecycle's D5 handshake reply (collab, 01:38:49): store_warnings is
// a NEW top-level field on GET /doctor (sibling to health/stt/llm/.../
// recovery, not nested), covering all four config stores via one shared
// quarantine/downgrade-refusal mechanism. Redacted-stderr is LINE-LEVEL
// (redact_stderr_lines), not one blob-level marker -- loader/diagnostic
// lines survive verbatim, everything else is redacted per-line.
//
// SAME SCOPE NOTE as model-resources.mjs: grepping main.js found no consumer
// of doctor.store_warnings or doctor.llm.last_error_details.stderr anywhere
// -- no UI shows either yet. These are API-contract scenarios, not
// screenshots of a rendered state.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

async function fetchViaBridge(page, method, path) {
  return page.evaluate(
    async ({ method, path }) => {
      const res = await window.betterFingers.backendRequest(method, path);
      return res && { status: res.status, body: res.body };
    },
    { method, path },
  );
}

// A realistic mixed stderr blob: loader/diagnostic lines (survive verbatim
// per the allowlist: error/failed/missing/lib/.so/.dll/cuda/vulkan/version/
// build/load) interleaved with a line that would contain user-adjacent
// content and must be redacted.
const MIXED_STDERR = [
  'llama_model_load: loading model from /models/gemma-4-e2b-q4.gguf',
  'error: failed to load libmtmd.so.0: cannot open shared object file',
  'prompt eval time = 412.3 ms for user input: "what is the capital of france"',
  'cuda_init: version 12.4, build 4500',
].join('\n');

export const doctorWarningsScenarios = [
  {
    area: 'doctor-warnings',
    name: 'store-warnings-contract',
    kind: 'standard',
    description:
      'GET /doctor carries a top-level store_warnings array covering quarantined-corrupt and downgrade_refused ' +
      'events across all four config stores (personas/voice-presets/profiles/app_state) -- one shared mechanism ' +
      'in store_migration.py, not per-store special cases. Verified as a direct sibling of health/stt/llm/etc, ' +
      'not nested under any of them.',
    backendState: () => ({
      ...coldBoot(),
      'GET /doctor': {
        ...coldBoot()['GET /doctor'],
        store_warnings: [
          {
            path: '/tmp/x/profiles/Default.yaml',
            action: 'quarantined',
            warnings: ['corrupt YAML: mapping values are not allowed here'],
            at: 1752500000.0,
          },
          {
            path: '/tmp/x/personas.yaml',
            action: 'downgrade_refused',
            warnings: ['schema_version 3 is newer than this build supports (2) -- refusing to touch the file'],
            at: 1752500005.0,
          },
        ],
      },
    }),
    async navigate(page) {},
    async expects(page) {
      const result = await fetchViaBridge(page, 'GET', '/doctor');
      expect(result.status).toBe(200);
      const warnings = result.body.store_warnings;
      expect(Array.isArray(warnings)).toBe(true);
      expect(warnings.length).toBe(2);
      expect(warnings.map((w) => w.action).sort()).toEqual(['downgrade_refused', 'quarantined']);
      // Sibling to the existing sections, not nested under any of them.
      expect(result.body.stt).toBeDefined();
      expect(result.body.stt.store_warnings).toBeUndefined();
    },
    screenshots: [],
  },
  {
    area: 'doctor-warnings',
    name: 'redacted-stderr-is-line-level-not-blob-level',
    kind: 'standard',
    description:
      'llm.last_error_details.stderr is redacted PER-LINE, not as one blob-level marker: loader/diagnostic lines ' +
      '(matching the error/failed/missing/lib/.so/cuda/vulkan/version/build/load allowlist) survive verbatim ' +
      '(e.g. "libmtmd.so.0" stays readable for debugging), while any other line -- including anything that could ' +
      'carry user-adjacent content, like a logged prompt -- becomes an individual `<redacted N chars>` line. ' +
      'Asserts BOTH halves of that mix are present, not just "the field exists".',
    backendState: () => {
      const lines = MIXED_STDERR.split('\n');
      const redactedStderr = lines
        .map((line) => {
          const isDiagnostic = /error|failed|missing|lib|\.so|\.dll|cuda|vulkan|version|build|load/i.test(line);
          return isDiagnostic ? line : `<redacted ${line.length} chars>`;
        })
        .join('\n');
      return {
        ...coldBoot(),
        'GET /doctor': {
          ...coldBoot()['GET /doctor'],
          llm: {
            ...coldBoot()['GET /doctor'].llm,
            last_error: 'llama-server crashed during model load.',
            last_error_details: { stderr: redactedStderr },
          },
        },
      };
    },
    async navigate(page) {},
    async expects(page) {
      const result = await fetchViaBridge(page, 'GET', '/doctor');
      const stderr = result.body.llm.last_error_details.stderr;
      // Loader/diagnostic lines survive verbatim.
      expect(stderr).toContain('libmtmd.so.0');
      expect(stderr).toContain('cuda_init: version 12.4, build 4500');
      // The prompt-carrying line is redacted, not shown verbatim.
      expect(stderr).not.toContain('capital of france');
      expect(stderr).toMatch(/<redacted \d+ chars>/);
    },
    screenshots: [],
  },
];
