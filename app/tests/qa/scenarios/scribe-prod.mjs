// Production Signal Desk Scribe coverage. This drives the real Scribe
// workspace and reuses the Message Rescue request/response contract with a
// deterministic stub, so the scenario never needs a local model process.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

function scribeState() {
  let capturedContext = '';
  return {
    ...coldBoot(),
    'GET /personas': {
      Formal: { prompt: 'Be precise and businesslike.' },
      'True Janitor': { prompt: 'Clean up text while preserving meaning.' },
    },
    'POST /message-rescue/context/manual': (_req, { body }) => {
      capturedContext = String(body?.text || '');
      return { active: true, source: 'manual', visible_preview: capturedContext.slice(0, 80) };
    },
    'POST /message-rescue/generate': (_req, { body }) => {
      const answered = /Answer: Tuesday/.test(capturedContext);
      const mayAsk = body?.allow_clarifying_question === true && !answered;
      return {
        id: answered ? 'scribe-qa-job-answered' : 'scribe-qa-job-1',
        status: 'done',
        result: {
          assessment: mayAsk ? {
            intent: 'Schedule a meeting.',
            ambiguity_risk: 'high',
            missing_details: ['which day'],
            clarification_question: 'Which day should I use?',
            clarification_confidence: 0.92,
            clarification_gate: { passed: true, reason: 'passed', confidence: 0.92, threshold: 0.75 },
          } : {
            intent: 'Ask to move the standup meeting.',
            ambiguity_risk: 'low',
            missing_details: [],
            clarification_question: '',
            clarification_confidence: 0,
            clarification_gate: { passed: false, reason: 'permission_denied', confidence: 0, threshold: 0.75 },
          },
          delivery: { labels: [], confidence: 0, evidence: [] },
          variants: answered ? {
            faithful: 'Can we meet Tuesday?',
            clearer: 'Could we schedule the meeting for Tuesday?',
            alternate: 'Would Tuesday work for the meeting?',
          } : {
            faithful: String(body?.transcript || ''),
            clearer: body?.persona === 'Formal'
              ? 'Could we please move the standup meeting to a later time?'
              : 'Could we move standup later?',
            alternate: 'Would a later standup time work for everyone?',
          },
          preservation_checks: [{ name: 'Meaning preserved', passed: true, detail: '' }],
          warnings: [],
        },
      };
    },
  };
}

async function assertNoOnboardingGate(page) {
  const gate = page.locator('#sdOnboarding');
  if (await gate.isVisible().catch(() => false)) {
    throw new Error('The production Scribe scenario requires an ungated Signal Desk shell.');
  }
}

export const scribeProdScenarios = [
  {
    area: 'scribe-prod',
    ui: 'signal-desk-prod',
    name: 'scribe-compose-cleanup-review-and-selection-hotkey',
    kind: 'standard',
    description:
      'Opens the primary Scribe workspace, verifies its single real text playground and truthful cleanup/review copy, ' +
      'then runs a deterministic Message Rescue cleanup with a selected persona. It also verifies the always-open context ' +
      'form and the opt-in, confidence-gated clarification answer/rerun loop. Raw and cleaned variants remain review-only.',
    backendState: scribeState,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="scribe"]');
    },
    async expects(page) {
      const scribe = page.locator('#workspace-scribe');
      await expect(scribe).toBeVisible();
      await expect(page.locator('#textPlaygroundSection'), 'Scribe must have exactly one real compose section').toHaveCount(1);

      const compose = page.locator('#textPlaygroundSection');
      await expect(scribe).toContainText(/selected persona and local LLM clean it up/i);
      await expect(scribe).toContainText(/review-only until you explicitly choose Copy or Apply/i);
      await expect(page.locator('#textPlaygroundText')).toBeVisible();
      await expect(page.locator('#textPlaygroundContext')).toBeVisible();
      await expect(page.locator('#textPlaygroundClarificationNo')).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('#textPlaygroundPersonaSelect')).toBeVisible();
      await expect(page.locator('#textPlaygroundRunButton')).toHaveText('Clean up message');
      await expect(page.locator('#textPlaygroundRunButton')).toBeVisible();

      const sendRequests = [];
      const onRequest = (request) => {
        const pathname = new URL(request.url()).pathname;
        if (/\/(?:send|inject|input\/dispatch)(?:\/|$)/i.test(pathname)) sendRequests.push(pathname);
      };
      page.on('request', onRequest);
      try {
        await expect(page.locator('#textPlaygroundPersonaSelect option[value="Formal"]')).toHaveCount(1);
        await page.fill('#textPlaygroundText', 'hey can we move standup later');
        await page.selectOption('#textPlaygroundPersonaSelect', 'Formal');
        await page.click('#textPlaygroundRunButton');

        await expect(page.locator('#textPlaygroundStatus')).toHaveText('Done.');
        await expect(page.locator('#textPlaygroundRanInfo')).toContainText('persona: Formal');
        await expect(page.locator('#textPlaygroundText')).toHaveValue('hey can we move standup later');
        await expect(page.locator('#textPlaygroundColumnFaithfulText')).toHaveText('hey can we move standup later');
        await expect(page.locator('#textPlaygroundColumnClearerText')).toContainText('move the standup meeting');
        await expect(page.locator('#textPlaygroundColumnAlternateText')).toContainText('later standup time');
        await expect(page.locator('#textPlaygroundFallback')).toBeHidden();
        expect(sendRequests, 'Scribe cleanup must not auto-send or inject text').toEqual([]);

        // Opt in, then give the model deliberately ambiguous text. The first
        // pass remains visible behind a question that only opens after the
        // server-reported 92% confidence clears the 75% gate.
        await page.click('#textPlaygroundClarificationYes');
        await page.fill('#textPlaygroundText', 'Can we meet?');
        await page.click('#textPlaygroundRunButton');
        await expect(page.locator('#textPlaygroundColumnFaithfulText')).toHaveText('Can we meet?');
        await expect(page.locator('#textPlaygroundClarification')).toBeVisible();
        await expect(page.locator('#textPlaygroundClarificationQuestion')).toHaveText('Which day should I use?');
        await expect(page.locator('#textPlaygroundClarificationGateStatus')).toContainText('92% (minimum 75%)');
        await page.fill('#textPlaygroundClarificationAnswer', 'Tuesday');
        await page.click('#textPlaygroundClarificationSubmit');
        await expect(page.locator('#textPlaygroundClarification')).toBeHidden();
        await expect(page.locator('#textPlaygroundColumnFaithfulText')).toHaveText('Can we meet Tuesday?');
        await expect(page.locator('#textPlaygroundContext')).toHaveValue(/Answer: Tuesday/);
        expect(sendRequests, 'clarification must remain review-only').toEqual([]);
      } finally {
        page.off('request', onRequest);
      }

      await page.click('.sd-nav__button[data-nav="utilities"]');
      await page.click('#sdUtilNavSpeech');
      await expect(page.locator('#sdUtilSectionSpeech')).toBeVisible();
      await expect(page.locator('#sdUtilHotkeySelectionRewriteInput')).toHaveValue('ctrl+alt+r');
      await expect(page.locator('#sdUtilSectionSpeech')).toContainText(/never replaces or sends text automatically/i);

      // Leave the walkbook on the core user outcome: the reviewed Scribe
      // variants. The hotkey panel was asserted above in the same real app.
      await page.click('.sd-nav__button[data-nav="scribe"]');
      await expect(scribe).toBeVisible();
    },
    screenshots: [{ name: 'scribe-compose-cleanup-review-and-selection-hotkey' }],
  },
  {
    area: 'scribe-prod',
    ui: 'signal-desk-prod',
    name: 'clarification-confidence-gate-popup',
    kind: 'standard',
    description:
      'Opts into one local clarification, produces the best-effort variants first, and leaves the real answer dialog open ' +
      'for visual verification with the model-reported confidence and deterministic threshold disclosed.',
    backendState: scribeState,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="scribe"]');
    },
    async expects(page) {
      await page.click('#textPlaygroundClarificationYes');
      await page.fill('#textPlaygroundText', 'Can we meet?');
      await page.click('#textPlaygroundRunButton');

      await expect(page.locator('#textPlaygroundColumnFaithfulText')).toHaveText('Can we meet?');
      await expect(page.locator('#textPlaygroundClarification')).toBeVisible();
      await expect(page.locator('#textPlaygroundClarificationQuestion')).toHaveText('Which day should I use?');
      await expect(page.locator('#textPlaygroundClarificationGateStatus')).toContainText('92% (minimum 75%)');
      await expect(page.locator('#textPlaygroundClarificationAnswer')).toBeFocused();
      await expect(page.locator('#textPlaygroundClarificationSubmit')).toBeDisabled();
    },
    screenshots: [{ name: 'clarification-confidence-gate-popup' }],
  },
];
