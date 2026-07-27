// Utilities and Settings section routing on the Signal Desk page.
//
// These two workspaces carry the highest parity scores and the only
// machine-checked no-feature-lost gates in the repo — and until now had no
// Signal Desk QA at all. The gates prove a control is *claimed*; only a real
// Electron run proves the section it lives in can actually be opened.
//
// This is the Signal Desk equivalent of the default UI's
// baseline/settings-general-renders + settings-recording-renders pair, which
// exist for exactly this reason: section routing is the thing that silently
// breaks and makes whole panels of features unreachable. It is also the shape
// of failure that actually happened on the old dashboard, where a stray call to
// a nonexistent function aborted the click handler before it revealed the
// section (see main.js's tts-readaloud branch).

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

const UTIL_SECTIONS = ['models', 'speech', 'text', 'diagnostics', 'advanced'];
const SET_SECTIONS = [
  'Profile', 'Recording', 'Review', 'AiCleanup', 'Notifications', 'Appearance', 'Privacy',
];

/** Exactly one section visible, and it is the requested one. */
async function expectOnlySectionVisible(page, idFor, all, active) {
  for (const id of all) {
    const panel = page.locator(`#${idFor(id)}`);
    if (id === active) {
      await expect(panel, `${idFor(id)} should be visible`).toBeVisible();
    } else {
      await expect(panel, `${idFor(id)} should be hidden`).toBeHidden();
    }
  }
}

const utilSectionId = (id) => `sdUtilSection${id[0].toUpperCase()}${id.slice(1)}`;
const setSectionId = (id) => `sdSetSection${id}`;

export const signalDeskSectionScenarios = [
  {
    area: 'signal-desk-sections',
    ui: 'signal-desk',
    name: 'utilities-sections-are-all-reachable',
    kind: 'standard',
    description:
      'Utilities is the catch-all that guarantees no feature was lost in the redesign — models, speech input, ' +
      'text tools, diagnostics and advanced. Clicking each nav item must reveal that section and hide the rest. ' +
      'A section that cannot be opened makes every control inside it unreachable while the placement-map gate ' +
      'still reports them as wired, which is the one way that gate can lie.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('.sd-nav__button[data-nav="utilities"]');
    },
    async expects(page) {
      await expect(page.locator('#workspace-utilities')).toBeVisible();

      for (const id of UTIL_SECTIONS) {
        // Address the nav by its unique id, not [data-util-nav]: the context
        // panel reuses that attribute on filter chips, so the bare attribute
        // selector matches two elements and resolves ambiguously.
        const navId = `sdUtilNav${id[0].toUpperCase()}${id.slice(1)}`;
        await page.click(`#${navId}`);
        await expectOnlySectionVisible(page, utilSectionId, UTIL_SECTIONS, id);
        await expect(page.locator(`#${navId}`)).toHaveAttribute('aria-current', 'page');
      }
    },
    screenshots: [{ name: 'utilities-sections-are-all-reachable' }],
  },
  {
    area: 'signal-desk-sections',
    ui: 'signal-desk',
    name: 'settings-sections-are-all-reachable',
    kind: 'standard',
    description:
      'Every profile key lives in one of Settings\' seven sections. Same contract as Utilities: each nav item ' +
      'reveals its own section and hides the others. Notably includes Privacy, which owns the data wipe — a ' +
      'section that silently fails to open is a safety control the user cannot reach.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('.sd-nav__button[data-nav="settings"]');
    },
    async expects(page) {
      await expect(page.locator('#workspace-settings')).toBeVisible();

      for (const id of SET_SECTIONS) {
        await page.click(`#sdSetNav${id}`);
        await expectOnlySectionVisible(page, setSectionId, SET_SECTIONS, id);
      }
    },
    screenshots: [{ name: 'settings-sections-are-all-reachable' }],
  },
  {
    area: 'signal-desk-sections',
    ui: 'signal-desk',
    name: 'voice-studio-is-present-and-consent-gated',
    kind: 'standard',
    description:
      'settingsWorkspace.js delegates §7.9 to Studio, but Studio had only the blend strip -- presets, ' +
      'modulation, cloning and read-aloud speed had no markup at all, so voiceStudio.js\'s logic could not bind ' +
      'to anything. Asserts each group exists, and that the clone upload stays unreachable until consent is ' +
      'ticked: cloning is the one irreversible action on this screen, so the checkbox has to be a gate rather ' +
      'than a formality sitting next to an already-live button.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('.sd-nav__button[data-nav="studio"]');
    },
    async expects(page) {
      // Every §7.9 group has a real mount point.
      for (const id of [
        'settingReviewTtsVoiceHint', 'settingReviewTtsSpeed', 'testTtsButton', 'voicePreviewText',
        'voiceBlendRows', 'addVoiceLayerButton', 'resetVoiceBlendButton',
        'voicePitch', 'voiceEnergy', 'voiceWarmth', 'voiceBrightness', 'voicePauseStyle',
        'voicePresetSelect', 'voicePresetNameInput', 'saveVoicePresetButton', 'voicePresetList',
        'voiceCloneConsent', 'voiceCloneName', 'voiceCloneFile', 'voiceCloneUploadButton',
      ]) {
        await expect(page.locator(`#${id}`), `#${id} missing from Voice Studio`).toHaveCount(1);
      }

      // The consent gate.
      const consent = page.locator('#voiceCloneConsent');
      const upload = page.locator('#voiceCloneUploadButton');
      await expect(consent).not.toBeChecked();
      await expect(upload, 'clone upload is live before consent was given').toBeDisabled();

      await consent.check();
      await expect(upload).toBeEnabled();

      // Withdrawing consent must close the gate again, not leave it ajar.
      await consent.uncheck();
      await expect(upload, 'gate stayed open after consent was withdrawn').toBeDisabled();
    },
    screenshots: [{ name: 'voice-studio-is-present-and-consent-gated' }],
  },
];
