// Voice Cloning card (models page) scenarios. The card is populated from the
// /tts/voices `cloning` availability payload
// ({ available, reason, setup_hint, mechanism }) and replaces surfacing the raw
// "run tools/setup_voice_cloning.py" CLI hint to end users. Stubbed against that
// backend contract, treated as an external spec.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

async function openModels(page) {
  await page.click('#tabButtonModels');
  await expect(page.locator('#voiceCloningPanel')).toBeVisible();
}

export const voiceCloningScenarios = [
  {
    area: 'voice-cloning',
    name: 'not-installed',
    kind: 'standard',
    description:
      'Voice cloning has not been provisioned: the card shows a "Not installed" badge, friendly optional-add-on ' +
      'copy with the ~1.5 GB download size, and an "Install voice cloning" button — NOT the raw ' +
      '"run tools/setup_voice_cloning.py" CLI instruction the backend reason still carries.',
    backendState: () => ({
      ...coldBoot(),
      'GET /tts/voices': {
        defaults: [], cloned: [],
        cloning: {
          available: false,
          reason: 'voice-cloning dependencies not installed (kanade_tokenizer)',
          setup_hint: 'Run tools/setup_voice_cloning.py to install the voice-cloning engine.',
          mechanism: null,
        },
      },
    }),
    async navigate(page) {
      await openModels(page);
    },
    async expects(page) {
      await expect(page.locator('#voiceCloningBadge')).toHaveText('Not installed');
      await expect(page.locator('#provisionVoiceCloningButton')).toBeVisible();
      // The jargon/CLI reason must NOT leak into the user-facing card.
      await expect(page.locator('#voiceCloningPanel')).not.toContainText('setup_voice_cloning');
      await expect(page.locator('#voiceCloningPanel')).not.toContainText('kanade_tokenizer');
    },
    screenshots: [{ name: 'not-installed' }],
  },
  {
    area: 'voice-cloning',
    name: 'installed',
    kind: 'standard',
    description:
      'Voice cloning is provisioned (side-runtime): the badge reads "Installed", the copy points the user to ' +
      'TTS / Read-Aloud to clone a voice, and the Install button is hidden.',
    backendState: () => ({
      ...coldBoot(),
      'GET /tts/voices': {
        defaults: [], cloned: [],
        cloning: { available: true, reason: '', setup_hint: '', mechanism: 'side-runtime' },
      },
    }),
    async navigate(page) {
      await openModels(page);
    },
    async expects(page) {
      await expect(page.locator('#voiceCloningBadge')).toHaveText('Installed');
      await expect(page.locator('#provisionVoiceCloningButton')).toBeHidden();
    },
    screenshots: [{ name: 'installed' }],
  },
];
