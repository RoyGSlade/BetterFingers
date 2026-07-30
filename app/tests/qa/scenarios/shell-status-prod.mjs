// Wave 11B shell-status surfaces on the PRODUCTION Signal Desk page
// (signal-desk.html, `ui: 'signal-desk-prod'`).
//
// Three things this wave BUILT, because they existed only on the legacy page
// and the Wave 11 audit found no production anchor for any of them:
//
//   * the status rail's Backend cell        (legacy: the backendStatus card)
//   * the status rail's Stream cell         (legacy: the wsConnection pill)
//   * the backend health / version banner   + the header Quit button
//
// The Stream cell is the one worth stating plainly. Before this wave the
// production bootstrap subscribed to the voice-status bridge with EMPTY
// onConnectionChange and onError closures, so a severed stream was completely
// invisible: the Signal Core simply stopped moving and nothing on screen said
// why. A user could not distinguish that from a quiet microphone.
//
// Every selector below was re-grepped against app/src/renderer/signal-desk.html
// rather than copied out of the feature module, same discipline as
// signal-desk-prod-sweep.mjs.
//
// KNOWN COVERAGE LIMIT, stated rather than left to be discovered: the banner's
// LIFECYCLE branch (crashed / restarting / unhealthy) is driven by
// window.betterFingers.getSidecarStatus(), which is Electron-main state the QA
// backend stub cannot reach. Only its VERSION branch is exercised end to end
// here; the lifecycle branch is covered by app/tests/backendBanner.test.mjs at
// unit level. That is a real gap in this file, not an oversight.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

/** Shared with signal-desk-prod-sweep.mjs's rule: never click through the gate. */
async function assertNoOnboardingGate(page) {
  const gate = page.locator('#sdOnboarding');
  if (await gate.isVisible().catch(() => false)) {
    throw new Error(
      '#sdOnboarding is visible at scenario start -- broken precondition. Refusing to click ' +
        'through the gate; fix whatever left it open instead.',
    );
  }
}

export const shellStatusProdScenarios = [
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'backend-and-stream-cells-report-real-state',
    kind: 'standard',
    description:
      'The persistent status rail carries the two cells that replaced the legacy dashboard\'s backend status ' +
      'grid and its WebSocket connection pill. On a cold boot the stub answers GET /health with status "active" ' +
      'and GET /runtime/status with everything unloaded, so this asserts the rail reports exactly that: Backend ' +
      '"Active", STT "Not loaded", LLM "Not ready" -- and, critically, that the Backend cell is NOT showing the ' +
      'em dash it uses for "not asked yet". The distinction between "we asked and it did not answer" and "we ' +
      'have not asked" is the entire reason this cell exists, and a rail that collapses the two would look ' +
      'perfectly normal in a screenshot while telling the user nothing. The Stream cell is asserted as present ' +
      'and non-empty rather than pinned to one state, because the voice-status bridge legitimately settles ' +
      'through connecting -> connected at its own pace.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
    },
    async expects(page) {
      const backend = page.locator('#sdStatusBackendValue');
      await expect(backend, '#sdStatusBackendValue must exist exactly once').toHaveCount(1);
      await expect(backend, 'the Backend cell must be visible in the rail').toBeVisible();
      await expect(
        backend,
        'GET /health answered status "active", so the cell must say Active -- not the "not asked yet" dash',
      ).toHaveText('Active');

      // The other two rail cells the legacy status grid carried, on the same
      // cold-boot payload: nothing is loaded yet, and the rail must say so
      // rather than reporting the mockup's hard-coded "Ready / Local".
      await expect(page.locator('#sdStatusSttValue')).toHaveText('Not loaded');
      await expect(page.locator('#sdStatusLlmValue')).toHaveText('Not ready');

      const stream = page.locator('#sdStatusStreamValue');
      await expect(stream, '#sdStatusStreamValue must exist exactly once').toHaveCount(1);
      await expect(stream, 'the Stream cell must be visible in the rail').toBeVisible();
      await expect(
        stream,
        'the Stream cell must report SOMETHING -- an empty cell is the pre-Wave-11B behaviour this replaced',
      ).not.toHaveText('');
    },
    screenshots: [{ name: 'backend-and-stream-cells-report-real-state' }],
  },
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'version-banner-stays-hidden-when-versions-agree',
    kind: 'standard',
    description:
      'The negative half of the banner contract, and the more important one. On a healthy install the backend ' +
      'reports the app version it was built for and the app agrees, so the banner must render NOTHING. A banner ' +
      'that is always on screen -- "everything might be fine" -- trains people to ignore it, and the one time it ' +
      'matters they will. This asserts the element is present in the DOM (so the next scenario is testing a real ' +
      'element rather than a typo) and hidden.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
    },
    async expects(page) {
      const banner = page.locator('#sdVersionMismatchBanner');
      await expect(banner, '#sdVersionMismatchBanner must exist in the production shell').toHaveCount(1);
      await expect(
        banner,
        'agreeing versions and a healthy sidecar must leave the banner hidden',
      ).toBeHidden();
    },
    screenshots: [{ name: 'version-banner-stays-hidden-when-versions-agree' }],
  },
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'version-banner-appears-on-a-real-disagreement',
    kind: 'standard',
    description:
      'The positive half. GET /runtime/version reports expected_electron_api_version from the single VERSION ' +
      'source (D-0008); this scenario stubs it to a version the running app is definitively not, which is exactly ' +
      'the situation a stale sidecar produces. The banner must appear and name BOTH versions -- a warning that ' +
      'says only "mismatch" leaves the user with nothing to act on. This is the surface that explains a whole ' +
      'class of otherwise inexplicable half-working behaviour, and until Wave 11B the production page had no ' +
      'equivalent at all.',
    backendState: () => ({
      ...coldBoot(),
      'GET /runtime/version': {
        backend_version: '0.0.1-stale',
        // Deliberately not any version this app could be built as.
        expected_electron_api_version: '99.99.99-not-this-build',
        schema_version: 1,
        config_version: 1,
      },
    }),
    async navigate(page) {
      await assertNoOnboardingGate(page);
      // The banner is painted by a 3s poll, not by a user action, so wait for
      // the state rather than asserting into a race.
      await page.locator('#sdVersionMismatchBanner:not([hidden])').waitFor({ timeout: 15000 });
    },
    async expects(page) {
      const banner = page.locator('#sdVersionMismatchBanner');
      await expect(banner, 'a genuine version disagreement must surface the banner').toBeVisible();
      await expect(
        page.locator('#sdBackendBannerTitle'),
        'the banner must be titled as a version mismatch',
      ).toHaveText(/version mismatch/i);
      await expect(
        page.locator('#sdBackendBannerMessage'),
        'the message must name the version the backend expects, not just say "mismatch"',
      ).toContainText('99.99.99-not-this-build');
    },
    screenshots: [{ name: 'version-banner-appears-on-a-real-disagreement' }],
  },
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'quit-button-is-present-and-labelled',
    kind: 'standard',
    description:
      'The header Quit button, which the legacy shell had and Signal Desk shipped without -- leaving the window ' +
      'chrome as the only way out of an app that deliberately keeps a background sidecar running. Asserted as ' +
      'present, visible, enabled and carrying an accessible name; NEVER clicked, because a real click past the ' +
      'confirmation quits the Electron app the rest of this suite is running in. The confirm-then-quit behaviour ' +
      'is covered by app/tests/backendBanner.test.mjs instead.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
    },
    async expects(page) {
      const quit = page.locator('#sdQuitButton');
      await expect(quit, '#sdQuitButton must exist exactly once').toHaveCount(1);
      await expect(quit, '#sdQuitButton must be visible in the header').toBeVisible();
      await expect(quit, '#sdQuitButton must be enabled').toBeEnabled();
      await expect(
        quit,
        'a control that ends the session must have an accessible name, not only an icon',
      ).toHaveAttribute('aria-label', /quit/i);
    },
    screenshots: [{ name: 'quit-button-is-present-and-labelled' }],
  },
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'hotkey-and-wake-capture-controls-are-reachable',
    kind: 'standard',
    description:
      'The Wave 11 blockers list recorded 48 rows across Settings and Utilities as having no production anchor, ' +
      'and concluded a user "cannot rebind a hotkey or train a wake phrase from the product". That was a ' +
      'measurement defect, not a product gap: the controls moved from Settings to Utilities > Speech Input, and ' +
      'the audit\'s rename rule could follow a rename but not a workspace MOVE. This scenario is the standing ' +
      'proof of the correction -- all six hotkey capture fields, the wake enable toggle, the classifier import, ' +
      'the Build-a-Wake-Phrase training group and the live wake test are asserted reachable and visible on the ' +
      'page that ships. If any of them ever stops being reachable, the anchors in tools/parity_anchors.py that ' +
      'promote those rows become false, and this fails.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="utilities"]');
      await expect(page.locator('#workspace-utilities')).toBeVisible();
      await page.click('#sdUtilNavSpeech');
      await expect(page.locator('#sdUtilSectionSpeech')).toBeVisible();
    },
    async expects(page) {
      // The six hotkey fields the inventory names (§7.3), each with its clear
      // button -- a field with no way to clear a binding is only half a
      // rebinding control.
      //
      // Written as LITERAL id pairs rather than built from a
      // `#sdUtilHotkey${field}Input` template, which is how this was first
      // drafted. tools/parity_evidence.py's coverage lookup searches scenario
      // SOURCE TEXT for the anchor's id, and an id assembled at runtime never
      // appears in the source -- so a scenario that genuinely exercised these
      // controls credited none of the rows that anchor to them. Same class of
      // mistake as a comment standing in for evidence: what the file SAYS and
      // what the tool can SEE have to agree.
      const hotkeyControls = [
        ['#sdUtilHotkeyRecordingInput', '#sdUtilHotkeyRecordingClear'],
        ['#sdUtilHotkeyForceStopInput', '#sdUtilHotkeyForceStopClear'],
        ['#sdUtilHotkeyManualSendInput', '#sdUtilHotkeyManualSendClear'],
        ['#sdUtilHotkeyReviewTtsInput', '#sdUtilHotkeyReviewTtsClear'],
        ['#sdUtilHotkeyChatOpenInput', '#sdUtilHotkeyChatOpenClear'],
        ['#sdUtilHotkeyVoiceMuteInput', '#sdUtilHotkeyVoiceMuteClear'],
      ];
      for (const [input, clear] of hotkeyControls) {
        await expect(page.locator(input), `${input} must be reachable for a user to rebind that hotkey`).toBeVisible();
        await expect(page.locator(clear), `${clear} must be reachable to unbind it again`).toBeVisible();
      }

      // The hotkey group's own two status surfaces (inventory §15 orphan row
      // UI-15-002 names these alongside the fields): the Wayland limitation
      // banner, which is conditional and therefore only asserted as PRESENT,
      // and the shared message line.
      await expect(page.locator('#sdUtilHotkeyWaylandWarning')).toHaveCount(1);
      await expect(page.locator('#sdUtilHotkeyMessage')).toHaveCount(1);

      // Wake word (§7.8): enable, choose a classifier, import one, train a
      // phrase, tune detection, test it live.
      for (const id of [
        '#sdUtilWakeEnabledToggle',
        '#sdUtilWakeModelSelect',
        '#sdUtilWakeImportButton',
        '#sdUtilWakeTrainGroup',
        '#sdUtilWakeTrainPhrase',
        '#sdUtilWakeTrainButton',
        '#sdUtilWakeSensitivity',
        '#sdUtilWakeCooldown',
        '#sdUtilWakeMaxRecording',
        '#sdUtilWakeTestButton',
        '#sdUtilWakeScoreBar',
      ]) {
        await expect(page.locator(id), `${id} must be reachable in Utilities > Speech Input`).toBeVisible();
      }

      // Audio device test (§7.7), the third group that moved here.
      await expect(page.locator('#sdUtilAudioTestMicButton')).toBeVisible();
      await expect(page.locator('#sdUtilAudioMeterBar')).toBeVisible();
    },
    screenshots: [{ name: 'hotkey-and-wake-capture-controls-are-reachable' }],
  },
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'model-manager-controls-are-reachable',
    kind: 'standard',
    description:
      'The same correction for inventory §8. The legacy Models tab was reported as 17 rows with no production ' +
      'anchor; it is in fact Utilities > Models, complete. This asserts the LLM and Whisper managers -- badge, ' +
      'picker, detail grid, and the select/download/unload/delete actions for each -- plus the recommendation ' +
      'box, the status summary and the voice-cloning provisioning panel are all reachable on the shipping page. ' +
      'Nothing is clicked: every action here either downloads gigabytes or deletes a model.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="utilities"]');
      await expect(page.locator('#workspace-utilities')).toBeVisible();
      await page.click('#sdUtilNavModels');
      await expect(page.locator('#sdUtilSectionModels')).toBeVisible();
    },
    async expects(page) {
      for (const id of [
        '#sdUtilModelsRefreshButton',
        '#sdUtilModelsRecommendation',
        '#sdUtilModelsStatusSummary',
        '#sdUtilLlmBadge',
        '#sdUtilLlmSelect',
        '#sdUtilLlmDetails',
        '#sdUtilLlmSelectButton',
        '#sdUtilLlmDownloadButton',
        '#sdUtilLlmUnloadButton',
        '#sdUtilLlmDeleteButton',
        '#sdUtilWhisperBadge',
        '#sdUtilWhisperSelect',
        '#sdUtilWhisperDetails',
        '#sdUtilWhisperSelectButton',
        '#sdUtilWhisperDownloadButton',
        '#sdUtilWhisperUnloadButton',
        '#sdUtilWhisperDeleteButton',
        '#sdUtilVoiceCloningPanel',
        '#sdUtilVoiceCloningProvisionButton',
      ]) {
        await expect(page.locator(id), `${id} must be reachable in Utilities > Models`).toBeVisible();
      }
    },
    screenshots: [{ name: 'model-manager-controls-are-reachable' }],
  },
  {
    area: 'shell-status-prod',
    ui: 'signal-desk-prod',
    name: 'voice-studio-quick-presets-exist-and-match-their-handlers',
    kind: 'standard',
    description:
      'features/voiceStudio.js has always exported VOICE_BLEND_QUICK_PRESETS and ' +
      'VOICE_MODULATION_QUICK_PRESETS and bound click handlers to [data-blend-preset] and ' +
      '[data-mod-preset] -- but signal-desk.html contained no such buttons, so eleven one-click ' +
      'presets were unreachable on the shipping page and both handlers were dead code. The ' +
      '"accessibility" modulation preset (0.75x speed) is a genuine accessibility affordance ' +
      'that shipped in the legacy page and had silently gone missing. This asserts the chips ' +
      'exist AND that their data-attribute values match the preset keys the handlers look up -- ' +
      'a chip whose value is not a key is a button that does nothing, which is the failure mode ' +
      'a screenshot cannot show. It also pins the pause-style options to the three values ' +
      'voiceStudio.js\'s PAUSE_STYLES actually accepts: the page shipped "tight" and "relaxed", ' +
      'neither of which is in that set, so choosing either silently saved "natural" instead ' +
      'while the select went on showing the user what they had picked. Existence and key-matching ' +
      'alone would still pass a chip with a dead click listener, so this also actually CLICKS one ' +
      'blend chip and one modulation chip and asserts the real bound sliders move to that preset\'s ' +
      'exact values -- energy/warmth changing on the blend click, then energy/warmth/pause-style/speed ' +
      'changing AGAIN to a second, different set of values on the modulation click, which only a live ' +
      'binding (not a static default) could produce twice in a row.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="studio"]');
      await expect(page.locator('#workspace-studio')).toBeVisible();
    },
    async expects(page) {
      // Keys copied from voiceStudio.js's two preset maps. If a preset is
      // renamed there and not here, this fails -- which is the point.
      for (const key of ['softer', 'brighter', 'lower', 'narrator', 'assistant']) {
        await expect(
          page.locator(`[data-blend-preset="${key}"]`),
          `a blend chip for "${key}" must exist, or VOICE_BLEND_QUICK_PRESETS.${key} is unreachable`,
        ).toHaveCount(1);
      }
      for (const key of ['clear', 'quiet', 'presentation', 'character', 'fast', 'accessibility']) {
        await expect(
          page.locator(`[data-mod-preset="${key}"]`),
          `a modulation chip for "${key}" must exist, or VOICE_MODULATION_QUICK_PRESETS.${key} is unreachable`,
        ).toHaveCount(1);
      }

      // No chip may name a preset the handlers cannot look up.
      const blendKeys = await page.locator('[data-blend-preset]').evaluateAll(
        (els) => els.map((el) => el.dataset.blendPreset),
      );
      assertSubset(blendKeys, ['softer', 'brighter', 'lower', 'narrator', 'assistant'], 'blend');
      const modKeys = await page.locator('[data-mod-preset]').evaluateAll(
        (els) => els.map((el) => el.dataset.modPreset),
      );
      assertSubset(modKeys, ['clear', 'quiet', 'presentation', 'character', 'fast', 'accessibility'], 'modulation');

      const pauseValues = await page.locator('#voicePauseStyle option').evaluateAll(
        (els) => els.map((el) => el.value),
      );
      expect(
        pauseValues.slice().sort(),
        'pause-style options must be exactly voiceStudio.js\'s PAUSE_STYLES set',
      ).toEqual(['compact', 'dramatic', 'natural']);

      // FUNCTIONAL, not just present: clicking a blend chip must move the
      // real modulation sliders to that preset's exact values.
      // VOICE_BLEND_QUICK_PRESETS.softer = { energy: 0.35, warmth: 0.3 }.
      await page.click('[data-blend-preset="softer"]');
      await expect(page.locator('#voiceEnergy'), 'the softer blend preset must set energy to 0.35').toHaveValue('0.35');
      await expect(page.locator('#voiceWarmth'), 'the softer blend preset must set warmth to 0.3').toHaveValue('0.3');

      // A second, different click must move the SAME sliders again -- proving
      // this is a live binding reacting to each click, not the page's static
      // default values coincidentally matching the first assertion.
      // VOICE_MODULATION_QUICK_PRESETS.quiet = { speed: 0.9, energy: 0.3,
      // warmth: 0.2, brightness: 0, pause_style: 'compact' }.
      await page.click('[data-mod-preset="quiet"]');
      await expect(page.locator('#voiceEnergy'), 'the quiet modulation preset must move energy to 0.3').toHaveValue('0.3');
      await expect(page.locator('#voiceWarmth'), 'the quiet modulation preset must move warmth to 0.2').toHaveValue('0.2');
      await expect(page.locator('#voiceBrightness'), 'the quiet modulation preset must set brightness to 0').toHaveValue('0');
      await expect(page.locator('#voicePauseStyle'), 'the quiet modulation preset must select the compact pause style').toHaveValue('compact');
      await expect(page.locator('#settingReviewTtsSpeed'), 'the quiet modulation preset must set speed to 0.9').toHaveValue('0.9');
    },
    screenshots: [{ name: 'voice-studio-quick-presets-exist-and-match-their-handlers' }],
  },
];

/** Every observed key must be one the handler can resolve. */
function assertSubset(observed, allowed, label) {
  const unknown = observed.filter((key) => !allowed.includes(key));
  expect(unknown, `${label} chips naming presets no handler can look up: ${unknown.join(', ')}`).toEqual([]);
}
