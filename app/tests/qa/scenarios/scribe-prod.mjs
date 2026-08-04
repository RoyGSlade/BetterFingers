// Production Signal Desk Scribe coverage. This drives the real Scribe
// workspace and reuses the Message Rescue request/response contract with a
// deterministic stub, so the scenario never needs a local model process.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

function scribeState() {
  return {
    ...coldBoot(),
    'GET /personas': {
      Formal: { prompt: 'Be precise and businesslike.' },
      'True Janitor': { prompt: 'Clean up text while preserving meaning.' },
    },
    'POST /message-rescue/generate': (_req, { body }) => ({
      id: 'scribe-qa-job-1',
      status: 'done',
      result: {
        assessment: {
          intent: 'Ask to move the standup meeting.',
          ambiguity_risk: 'low',
          missing_details: [],
          clarification_question: '',
        },
        delivery: { labels: [], confidence: 0, evidence: [] },
        variants: {
          faithful: String(body?.transcript || ''),
          clearer: body?.persona === 'Formal'
            ? 'Could we please move the standup meeting to a later time?'
            : 'Could we move standup later?',
          alternate: 'Would a later standup time work for everyone?',
        },
        preservation_checks: [{ name: 'Meaning preserved', passed: true, detail: '' }],
        warnings: [],
      },
    }),
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
      'then runs a deterministic Message Rescue cleanup with a selected persona. Raw and cleaned variants remain visible ' +
      'for review, while Utilities > Speech Input exposes Ctrl+Alt+R and explicitly says it never auto-replaces or sends text.',
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
        await expect(page.locator('#textPlaygroundColumnRawText')).toHaveText('hey can we move standup later');
        await expect(page.locator('#textPlaygroundColumnFaithfulText')).toHaveText('hey can we move standup later');
        await expect(page.locator('#textPlaygroundColumnClearerText')).toContainText('move the standup meeting');
        await expect(page.locator('#textPlaygroundColumnAlternateText')).toContainText('later standup time');
        await expect(page.locator('#textPlaygroundFallback')).toBeHidden();
        expect(sendRequests, 'Scribe cleanup must not auto-send or inject text').toEqual([]);
      } finally {
        page.off('request', onRequest);
      }

      await page.click('.sd-nav__button[data-nav="utilities"]');
      await page.click('#sdUtilNavSpeech');
      await expect(page.locator('#sdUtilSectionSpeech')).toBeVisible();
      await expect(page.locator('#sdUtilHotkeySelectionRewriteInput')).toHaveValue('ctrl+alt+r');
      await expect(page.locator('#sdUtilSectionSpeech')).toContainText(/never auto-replaces or sends text/i);

      // Leave the walkbook on the core user outcome: the reviewed Scribe
      // variants. The hotkey panel was asserted above in the same real app.
      await page.click('.sd-nav__button[data-nav="scribe"]');
      await expect(scribe).toBeVisible();
    },
    screenshots: [{ name: 'scribe-compose-cleanup-review-and-selection-hotkey' }],
  },
];
