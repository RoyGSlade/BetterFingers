// I3.5-I3.7: the live Message Rescue panel bound to the real Review Draft
// path (features/messageRescueDraft.js), as opposed to F2.8's static
// #messageRescuePanel preview (message-rescue.mjs) or board #31's
// standalone Text Playground (text-playground.mjs). Proves: real selection
// capture (success + clipboard-fallback + unsupported outcomes), a real
// generate call against the current draft's transcript, a safe fallback
// when only `faithful` comes back, and that picking a variant writes into
// the *existing* #draftFinalText editor -- #draftRawText never changes.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

const DRAFT = { id: 99, raw_text: 'hey can we push standup back a bit', final_text: 'hey can we push standup back a bit', status: 'pending' };

function baseState(overrides = {}) {
  return {
    ...coldBoot(),
    'GET /drafts': { drafts: [DRAFT] },
    'GET /drafts/latest': { draft: DRAFT },
    'GET /message-rescue/context': { active: false },
    'DELETE /message-rescue/context': { ok: true },
    ...overrides,
  };
}

function enableFlag(page) {
  return page.evaluate(() => localStorage.setItem('pref_message_rescue_enabled', 'true'));
}

// The Electron harness reuses one long-lived profile across scenarios (and
// across separate `node run.mjs` invocations -- no --user-data-dir reset),
// so localStorage genuinely persists. Every scenario that flips this flag on
// must flip it back off, exactly like message-rescue.mjs's own
// panel-enabled-preview scenario already does, or later scenarios that
// assume the shipped (flag-off) default will see stale state.
function disableFlag(page) {
  return page.evaluate(() => localStorage.removeItem('pref_message_rescue_enabled'));
}

async function goToDashboard(page) {
  await enableFlag(page);
  await page.reload();
  await page.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
  await page.click('#tabButtonDashboard');
  await expect(page.locator('#draftRescuePanel')).toBeVisible();
}

export const messageRescueDraftScenarios = [
  {
    area: 'message-rescue-draft',
    name: 'capture-selection-run-select-variant-updates-editor',
    kind: 'standard',
    description:
      'Capturing the current OS selection as context succeeds, running Message Rescue against the live draft ' +
      'renders assessment/delivery/clarification/preservation from the real result, and choosing the "clearer" ' +
      'variant writes it straight into the existing Cleaned output editor -- the raw transcript column is never ' +
      'touched. Clearing context afterwards resets the context region.',
    backendState: () =>
      baseState({
        'POST /message-rescue/context/selection': () => ({
          active: true, id: 'ctx-1', source: 'selection', captured_at: Date.now() / 1000, expires_at: Date.now() / 1000 + 120,
          use_count: 0, max_uses: 1, visible_preview: 'they asked to move it',
        }),
        'POST /message-rescue/generate': (req, { body }) => ({
          id: 'job-1',
          status: 'done',
          result: {
            assessment: {
              intent: 'Ask to move standup later.', ambiguity_risk: 'low',
              missing_details: [], clarification_question: '',
            },
            delivery: { labels: ['rushed'], confidence: 0.7, evidence: ['fast speaking rate'] },
            variants: {
              faithful: DRAFT.raw_text,
              clearer: 'Could we move standup back a bit today?',
              alternate: 'Any chance standup shifts later today?',
            },
            preservation_checks: [
              { name: 'Meaning preserved', passed: true, detail: '' },
              { name: 'Time reference resolved', passed: false, detail: '"a bit" is vague' },
            ],
            warnings: body && body.use_context ? [] : ['No context was used for this rewrite.'],
          },
        }),
      }),
    async navigate(page) {
      await goToDashboard(page);
    },
    async expects(page) {
      await expect(page.locator('#draftRescueDraftLabel')).toContainText('draft #99');

      await page.click('#draftRescueCaptureButton');
      await expect(page.locator('#draftRescueContextMessage')).toHaveText('Context captured.');
      await expect(page.locator('#draftRescueContextStatus')).toContainText('Context active');
      await expect(page.locator('#draftRescueContextPreview')).toHaveText('they asked to move it');

      const rawBefore = await page.locator('#draftRawText').textContent();

      await page.click('#draftRescueRunButton');
      await expect(page.locator('#draftRescueStatus')).toHaveText('Done.');
      await expect(page.locator('#draftRescueAssessment')).toBeVisible();
      await expect(page.locator('#draftRescueAssessmentIntent')).toHaveText('Ask to move standup later.');
      await expect(page.locator('#draftRescueDeliveryLabels .message-rescue-chip').first()).toBeVisible();
      await expect(page.locator('.draft-rescue-panel .message-rescue-check--fail')).toHaveCount(1);
      await expect(page.locator('.draft-rescue-panel .message-rescue-check--pass')).toHaveCount(1);
      // Context was consumed by the run -- one-time-use, gone from the panel now.
      await expect(page.locator('#draftRescueContextStatus')).toHaveText('No context captured.');

      // Picking "clearer" writes straight into the real review editor.
      await page.check('#draftRescueVariantClearer');
      await expect(page.locator('#draftFinalText')).toHaveValue('Could we move standup back a bit today?');
      await expect(page.locator('#draftRescueApplyMessage')).toContainText('Applied the clearer variant');
      // Raw transcript column is untouched by any of this.
      await expect(page.locator('#draftRawText')).toHaveText(rawBefore || '');

      await disableFlag(page);
    },
    screenshots: [{ name: 'capture-selection-run-select-variant-updates-editor' }],
  },
  {
    area: 'message-rescue-draft',
    name: 'clipboard-fallback-and-unsupported-capture',
    kind: 'standard',
    description:
      'When the OS selection is empty but the clipboard already has text, the backend reports a clipboard-fallback ' +
      'capture and the panel labels it accordingly. A second capture attempt that the platform cannot support at ' +
      'all surfaces a distinct, non-crashing message instead -- the capture button stays usable either way.',
    backendState: () =>
      baseState({
        'POST /message-rescue/context/selection': (() => {
          let call = 0;
          return () => {
            call += 1;
            if (call === 1) {
              return {
                active: true, id: 'ctx-2', source: 'clipboard_fallback', captured_at: Date.now() / 1000, expires_at: Date.now() / 1000 + 120,
                use_count: 0, max_uses: 1, visible_preview: 'pre-existing clipboard text',
              };
            }
            return { status: 422, body: { detail: 'capture_unsupported' } };
          };
        })(),
      }),
    async navigate(page) {
      await goToDashboard(page);
    },
    async expects(page) {
      await page.click('#draftRescueCaptureButton');
      await expect(page.locator('#draftRescueContextStatus')).toContainText('Context active');
      await expect(page.locator('#draftRescueContextMeta')).toContainText('from clipboard');
      await expect(page.locator('#draftRescueClearContextButton')).toBeEnabled();

      await page.click('#draftRescueClearContextButton');
      await expect(page.locator('#draftRescueContextStatus')).toHaveText('No context captured.');
      await expect(page.locator('#draftRescueClearContextButton')).toBeDisabled();

      await page.click('#draftRescueCaptureButton');
      await expect(page.locator('#draftRescueContextMessage')).toHaveText("Selection capture isn't available on this system.");
      await expect(page.locator('#draftRescueContextStatus')).toHaveText('No context captured.');
      await expect(page.locator('#draftRescueCaptureButton')).toBeEnabled();

      await disableFlag(page);
    },
    screenshots: [{ name: 'clipboard-fallback-and-unsupported-capture' }],
  },
  {
    area: 'message-rescue-draft',
    name: 'expired-context-and-faithful-only-fallback',
    kind: 'standard',
    description:
      'A context left over from a previous, already-expired capture is never shown as active on load. Running ' +
      'Message Rescue when the model output only produced a safe faithful rewrite (parse failure / preservation ' +
      'check on the server side) surfaces the fallback banner and leaves Clearer/Alternate disabled instead of ' +
      'inventing content for them.',
    backendState: () =>
      baseState({
        // Expired before this scenario even loads -- ContextSession.status()
        // reports active:false once past expires_at (see context_session.py).
        'GET /message-rescue/context': {
          active: false, id: 'ctx-stale', source: 'manual', captured_at: 1, expires_at: 2, use_count: 0, max_uses: 1,
          visible_preview: 'stale leftover context',
        },
        'POST /message-rescue/generate': {
          id: 'job-2',
          status: 'done',
          result: {
            assessment: { intent: '', ambiguity_risk: '', missing_details: [], clarification_question: '' },
            delivery: { labels: [], confidence: 0, evidence: [] },
            variants: { faithful: DRAFT.raw_text },
            preservation_checks: [],
            warnings: [],
          },
        },
      }),
    async navigate(page) {
      await goToDashboard(page);
    },
    async expects(page) {
      // The stale/expired context from GET /message-rescue/context never
      // renders as active, so Clear stays disabled and there is nothing to
      // consume when Run is clicked.
      await expect(page.locator('#draftRescueContextStatus')).toHaveText('No context captured.');
      await expect(page.locator('#draftRescueClearContextButton')).toBeDisabled();

      await page.click('#draftRescueRunButton');
      await expect(page.locator('#draftRescueStatus')).toHaveText('Done.');
      await expect(page.locator('#draftRescueFallback')).toBeVisible();
      await expect(page.locator('#draftRescueFallback')).toContainText('Fallback');
      await expect(page.locator('#draftRescueVariantFaithful')).toBeEnabled();
      await expect(page.locator('#draftRescueVariantClearer')).toBeDisabled();
      await expect(page.locator('#draftRescueVariantAlternate')).toBeDisabled();

      await disableFlag(page);
    },
    screenshots: [{ name: 'expired-context-and-faithful-only-fallback' }],
  },
];
