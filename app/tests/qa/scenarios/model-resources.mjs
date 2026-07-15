// Model resources / admission scenarios -- Phase 2 (D2 item 3). Shapes per
// model-lifecycle's D5 handshake reply (collab, 01:38:49): GET /models/resources
// is exactly the shape wake-harness assumed; admission refusal is a
// STRUCTURED payload ONLY for LLM (surfaced at /doctor's llm.last_error +
// llm.last_error_details), STT/TTS refusals are plain strings with no route
// surface today.
//
// IMPORTANT SCOPE NOTE: grepping app/src/renderer/main.js turned up ZERO
// consumers of /models/resources or doctor.llm.last_error_details anywhere
// in the renderer -- no Diagnostics UI reads this data at all yet. Building
// that UI is model-lifecycle's Diagnostics surface, not qa-harness's to
// invent (per the "consume, don't build" rule for surfaces you don't own).
// These scenarios verify the API CONTRACT is real and fetchable via the same
// bridge the app itself uses, and exist to give whoever builds that UI a
// concrete backend they can build+test against immediately -- not to fake a
// UI that isn't there. Flagged as a finding in the qa-harness handoff post.

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

export const modelResourcesScenarios = [
  {
    area: 'model-resources',
    name: 'resources-ledger-contract',
    kind: 'standard',
    description:
      'GET /models/resources returns the resource ledger (per-component model_id/estimated_mb/pinned, ' +
      'available_mb, ram_floor_mb) -- verified reachable through the same main-process proxy bridge the app ' +
      'uses. NOTE: no Diagnostics UI currently renders this data (confirmed by grepping main.js for any ' +
      'consumer) -- this scenario locks in the API contract for whoever builds that UI, it is not a screenshot ' +
      'of a rendered state because none exists yet.',
    backendState: () => ({
      ...coldBoot(),
      'GET /models/resources': {
        ok: true,
        ledger: {
          llm: { model_id: 'gemma-4-e2b-q4', estimated_mb: 3200, last_used: 1752500000.0, pinned: true },
          stt: null,
          tts: null,
        },
        pinned: { llm: true, stt: false, tts: false },
        available_mb: 5400,
        ram_floor_mb: 1024,
      },
    }),
    async navigate(page) {
      // No UI surface to navigate to -- verified directly via the app's own
      // backend bridge, exactly how main.js would call it if/when a
      // Diagnostics panel is added.
    },
    async expects(page) {
      const result = await fetchViaBridge(page, 'GET', '/models/resources');
      expect(result.status).toBe(200);
      expect(result.body.ok).toBe(true);
      expect(result.body.ledger.llm.model_id).toBe('gemma-4-e2b-q4');
      expect(result.body.ledger.llm.pinned).toBe(true);
      expect(result.body.ledger.stt).toBeNull();
      expect(typeof result.body.available_mb).toBe('number');
    },
    screenshots: [],
  },
  {
    area: 'model-resources',
    name: 'llm-admission-refusal-contract',
    kind: 'standard',
    description:
      'An LLM admission refusal surfaces as a structured payload at /doctor\'s llm.last_error (message string) + ' +
      'llm.last_error_details (resident components + suggested_model_id for a lighter fallback) -- confirmed via ' +
      'D5 handshake. STT/TTS refusals are plain strings with no structured route surface today (not stubbed here ' +
      '-- there is nothing to assert against). Same "no UI consumer yet" caveat as the ledger scenario applies.',
    backendState: () => ({
      ...coldBoot(),
      'GET /doctor': {
        ...coldBoot()['GET /doctor'],
        llm: {
          ...coldBoot()['GET /doctor'].llm,
          last_error: 'Insufficient memory to load gemma-4-12b-q4 (need ~9200MB, 5400MB available).',
          last_error_details: {
            message: 'Insufficient memory to load gemma-4-12b-q4 (need ~9200MB, 5400MB available).',
            resident: [
              { component: 'llm', model_id: 'gemma-4-e2b-q4', estimated_mb: 3200, pinned: true },
              { component: 'stt', model_id: 'base.en', estimated_mb: 500, pinned: false },
            ],
            suggested_model_id: 'gemma-4-e2b-q4',
          },
        },
      },
    }),
    async navigate(page) {},
    async expects(page) {
      const result = await fetchViaBridge(page, 'GET', '/doctor');
      expect(result.status).toBe(200);
      const details = result.body.llm.last_error_details;
      expect(details.suggested_model_id).toBe('gemma-4-e2b-q4');
      expect(Array.isArray(details.resident)).toBe(true);
      expect(details.resident.some((r) => r.pinned === true)).toBe(true);
    },
    screenshots: [],
  },
  {
    area: 'model-resources',
    name: 'LIE-stt-refusal-fabricates-resident-list',
    kind: 'negative-control',
    description:
      'Negative control (orchestrator-suggested): per the D5 handshake, STT/TTS admission refusals are ONLY ever ' +
      'a plain string -- there is no structured resident/suggested_model_id payload for them, that shape is ' +
      'LLM-only. This stub fabricates an STT refusal WITH an LLM-style structured resident list, which no real ' +
      'backend would ever produce. The assertion demands the asymmetry hold (structured details only ever ' +
      'accompanies the LLM component) and is EXPECTED TO FAIL against this stub -- a green result means the ' +
      'harness would catch a backend that started lying about which components get structured refusal detail.',
    backendState: () => ({
      ...coldBoot(),
      'GET /doctor': {
        ...coldBoot()['GET /doctor'],
        // The lie: STT normally only ever gets a plain-string last_error (per
        // the D5 handshake, nothing today even reads it into a route), never
        // a structured last_error_details with a resident/suggested_model_id
        // shape -- that shape is LLM-only.
        stt: {
          ...coldBoot()['GET /doctor'].stt,
          last_error: 'Insufficient memory to load base.en.',
          last_error_details: {
            message: 'Insufficient memory to load base.en.',
            resident: [{ component: 'llm', model_id: 'gemma-4-e2b-q4', estimated_mb: 3200, pinned: true }],
            suggested_model_id: 'tiny.en',
          },
        },
      },
    }),
    async navigate(page) {},
    async expects(page) {
      const result = await fetchViaBridge(page, 'GET', '/doctor');
      const stt = result.body.stt;
      // Real backends never attach a structured last_error_details to stt --
      // this asserts that invariant, which the lying stub above violates.
      expect(
        stt.last_error_details === undefined,
        'stt.last_error_details should never exist -- structured admission-refusal detail is LLM-only',
      ).toBe(true);
    },
    screenshots: [],
  },
];
