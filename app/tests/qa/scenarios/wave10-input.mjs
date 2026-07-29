// Wave 10 QA: the game setup wizard on the production composition root.
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs wave10-input
//
// WHAT IS AND IS NOT COVERED HERE, stated up front because the gap is the point.
// There is no controller and no Stream Deck on this project's machines, so no
// scenario below presses a physical button. What these scenarios cover is the
// renderer surface: that the wizard refuses to advance past a step the user has
// not completed, that the anti-cheat warning cannot be skipped on the way to the
// mode that carries the risk, that the test step sends only ids that cannot do
// anything, and that Save is dead until the test has run. The device-side
// behaviour — bounce, chord timing, unplug releasing a held recording — is
// covered by tests/test_controller_engine.py with pygame fully mocked, and by
// the manual pass in integrations/streamdeck/QUALIFICATION.md.
//
// REQUEST CAPTURE (D-0021) lives in the STUB HANDLER, never on
// `page.on('request')`: the renderer never issues the HTTP request itself — it
// goes through the main-process proxy — so a page-level listener counts zero
// forever and passes every "sent nothing" assertion vacuously.
//
// SELECTORS (D-0023): attribute selectors only. The wizard section carries
// data-wizard-step / data-wizard-rehearsed / data-wizard-saved and the warning
// carries data-required / data-satisfied precisely so a state can be addressed
// by identity rather than by the words inside it.
//
// THE ONE THAT MATTERS. `the-test-step-cannot-send-anything` asserts the
// requirement in the wave text: "the test can never fire a real send". It
// asserts on the WIRE — the exact ids the wizard transmitted — rather than on
// the absence of a visible effect, because "nothing appeared to happen" is also
// what a broken assertion looks like.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

const DEVICE = 'controller:xbox_wireless_controller';

let dispatchCalls = [];
let bindingSetCalls = [];
let profileSaveCalls = [];
// The presses the fake controller will report, one per capture start.
let captureQueue = [];
let pendingCapture = null;

/**
 * A backend with one controller plugged in.
 *
 * `POST /input/dispatch` answers the way the REAL rehearsal dispatcher does —
 * `{ok: false, status: "unavailable"}` for every id — because it is constructed
 * with no handlers. A stub that answered `ok: true` would let a wizard that
 * forgot the `rehearsal` flag pass.
 */
function inputBackend({ devices = [DEVICE], extra = {} } = {}) {
  return () => {
    // Two DIFFERENT buttons, drained one per capture start. A stub that answered
    // the same binding twice would hide the "dictation and commands are on the
    // same button" refusal instead of exercising the path around it.
    captureQueue = [
      { device_key: DEVICE, style: 'single', events: ['button:4'] },
      { device_key: DEVICE, style: 'single', events: ['button:5'] },
    ];
    pendingCapture = null;
    return {
      ...readyProfile(),
      'GET /input/vocabulary': {
        ok: true,
        schema_version: 1,
        actions: [],
        bindable: ['dictation.begin', 'command.begin', 'emergency.stop'],
        required: ['dictation.begin', 'command.begin', 'emergency.stop'],
        available: [],
        device_kinds: ['controller', 'stream_deck'],
        emergency_stop: 'emergency.stop',
      },
      'GET /input/bindings': {
        ok: true,
        enabled: true,
        debounce_ms: 40,
        devices,
        layers: { global: {}, device: {}, application_profile: {} },
        resolved: {},
        coverage: { bound: [], reachable: [], missing_required: [], has_emergency_stop: false },
        device_kinds: ['controller', 'stream_deck'],
      },
      // The capture handle: the engine listens, these routes are the poll.
      'POST /input/capture/start': () => {
        pendingCapture = captureQueue.shift() || null;
        return { ok: true, capturing: true };
      },
      'GET /input/capture/result': () => ({
        ok: true, capturing: true, binding: pendingCapture,
      }),
      'POST /input/capture/cancel': { ok: true, capturing: false },
      'POST /input/bindings/set': (_req, { body }) => {
        bindingSetCalls.push(body);
        return { ok: true, binding: body && body.binding, device_key: body && body.device_key };
      },
      'POST /input/dispatch': (_req, { body }) => {
        dispatchCalls.push(body);
        return {
          ok: false,
          action_id: (body && body.action_id) || '',
          status: 'unavailable',
          source: (body && body.source) || '',
        };
      },
      'POST /app-context/profiles': (_req, { body }) => {
        profileSaveCalls.push(body);
        return { ok: true, profile: body && body.profile, dropped_fields: [] };
      },
      ...extra,
    };
  };
}

function resetCaptures() {
  dispatchCalls = [];
  bindingSetCalls = [];
  profileSaveCalls = [];
}

async function openGameSetup(page) {
  await page.click('.sd-nav__button[data-nav="utilities"]');
  await expect(page.locator('#workspace-utilities')).toBeVisible();
  await page.click('#sdUtilNavAdvanced');
  await expect(page.locator('#sdUtilGameSetupGroup')).toBeVisible();
}

/**
 * Drive the wizard to the point where the test step is unlocked.
 *
 * The two record buttons are CLICKED, not called: they drive the wizard's own
 * poll loop against /input/capture/*, which is the part of the record step that
 * can be qualified without hardware. Only the listening itself needs a
 * controller, and that lives in the engine (tests/test_controller_engine.py).
 */
async function reachRehearsal(page, { delivery = 'review_only' } = {}) {
  await page.click('#sdUtilGameSetupDetectButton');
  await expect(page.locator('#sdUtilGameSetupDevices')).toHaveAttribute('data-device-count', '1');
  await page.click('#sdUtilGameSetupRecordDictation');
  await expect(page.locator('#sdUtilGameSetupDictationValue')).toHaveText('button:4');
  await page.click('#sdUtilGameSetupRecordCommand');
  await expect(page.locator('#sdUtilGameSetupCommandValue')).toHaveText('button:5');
  await page.fill('#sdUtilGameSetupChatKey', 'Enter');
  await page.dispatchEvent('#sdUtilGameSetupChatKey', 'change');
  await page.selectOption('#sdUtilGameSetupDelivery', delivery);
}

export const wave10InputScenarios = [
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'the-wizard-starts-at-detect-and-nothing-else-is-live',
    kind: 'standard',
    description:
      'Before a controller has been found there is nothing to bind, so every later control is dead. A wizard that '
      + 'lets a user record a binding for a device that is not there produces a profile that silently never '
      + 'applies — the failure mode is a game session where the buttons do nothing and no error was ever shown.',
    backendState: inputBackend({ devices: [] }),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
    },
    async expects(page) {
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-step', 'detect');
      await expect(page.locator('#sdUtilGameSetupRecordDictation')).toBeDisabled();
      await expect(page.locator('#sdUtilGameSetupRecordCommand')).toBeDisabled();
      await expect(page.locator('#sdUtilGameSetupRehearseButton')).toBeDisabled();
      await expect(page.locator('#sdUtilGameSetupSaveButton')).toBeDisabled();
    },
    screenshots: [{ name: 'the-wizard-starts-at-detect-and-nothing-else-is-live' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'no-controller-found-says-what-to-do',
    kind: 'standard',
    description:
      'An empty device list is not an error and must not read as one, but it must not read as success either. The '
      + 'wizard says what to do next rather than showing a blank field, because "nothing here" and "not working" '
      + 'look identical to somebody who has just plugged a controller in.',
    backendState: inputBackend({ devices: [] }),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await page.click('#sdUtilGameSetupDetectButton');
    },
    async expects(page) {
      await expect(page.locator('#sdUtilGameSetupDevices')).toHaveAttribute('data-device-count', '0');
      await expect(page.locator('#sdUtilGameSetupMessage')).toContainText('Plug one in');
    },
    screenshots: [{ name: 'no-controller-found-says-what-to-do' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'typing-into-a-game-requires-acknowledging-the-anti-cheat-risk',
    kind: 'standard',
    description:
      'The only delivery mode that synthesises a keystroke is the only one an anti-cheat system can classify as '
      + 'input automation, and some ban for it. Choosing it stops the wizard at the warning until the risk is '
      + 'acknowledged; the two modes that never synthesise input pass straight through. A warning that can be '
      + 'walked past is decoration.',
    backendState: inputBackend(),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await reachRehearsal(page, { delivery: 'type' });
    },
    async expects(page) {
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-step', 'warning');
      await expect(page.locator('#sdUtilGameSetupWarning')).toHaveAttribute('data-required', 'true');
      await expect(page.locator('#sdUtilGameSetupWarning')).toHaveAttribute('data-satisfied', 'false');
      await expect(page.locator('#sdUtilGameSetupWarning')).toContainText('input automation');
      await expect(page.locator('#sdUtilGameSetupRehearseButton')).toBeDisabled();

      await page.check('#sdUtilGameSetupAcknowledge');
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-step', 'rehearsal');
      await expect(page.locator('#sdUtilGameSetupRehearseButton')).toBeEnabled();
    },
    screenshots: [{ name: 'typing-into-a-game-requires-acknowledging-the-anti-cheat-risk' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'the-safe-delivery-modes-need-no-acknowledgement',
    kind: 'standard',
    description:
      'Review-first and copy-to-clipboard never synthesise a keystroke, so there is nothing for an anti-cheat '
      + 'system to detect and nothing for the user to accept. Making them require a tick anyway would train people '
      + 'to tick warnings, which is exactly how the one that matters stops being read.',
    backendState: inputBackend(),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await reachRehearsal(page, { delivery: 'clipboard_only' });
    },
    async expects(page) {
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-step', 'rehearsal');
      await expect(page.locator('#sdUtilGameSetupWarning')).toHaveAttribute('data-required', 'false');
      await expect(page.locator('#sdUtilGameSetupRehearseButton')).toBeEnabled();
    },
    screenshots: [{ name: 'the-safe-delivery-modes-need-no-acknowledgement' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'the-test-step-cannot-send-anything',
    kind: 'standard',
    description:
      'The requirement, asserted on the wire. Every press the test step sends is marked as a rehearsal and is '
      + 'answered by a dispatcher built with no handlers, and the two ids whose refusal would be the only thing '
      + 'between a rehearsal and a real consequence — typing the latest draft into the focused window, and stopping '
      + 'a recording nobody started — are never transmitted at all. Asserting on the ids sent rather than on the '
      + 'absence of a visible effect matters: "nothing appeared to happen" is also what a broken assertion looks '
      + 'like.',
    backendState: inputBackend(),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await reachRehearsal(page);
      await page.click('#sdUtilGameSetupRehearseButton');
    },
    async expects(page) {
      await expect.poll(() => dispatchCalls.length).toBe(2);
      const ids = dispatchCalls.map((row) => row.action_id).sort();
      expect(ids, 'only the two capture ids may be transmitted')
        .toEqual(['command.begin', 'dictation.begin']);
      for (const forbidden of ['latest.inject', 'emergency.stop']) {
        expect(ids, `${forbidden} must never be transmitted during a rehearsal`)
          .not.toContain(forbidden);
      }
      for (const row of dispatchCalls) {
        expect(row.rehearsal, 'every rehearsal press must be marked as one').toBe(true);
      }
      await expect(page.locator('#sdUtilGameSetupRehearsalLog'))
        .toHaveAttribute('data-press-count', '2');
      await expect(page.locator('#sdUtilGameSetupRehearsalLog')).toContainText('Nothing was sent');
      await expect(page.locator('#sdUtilGameSetupMessage')).toContainText('Nothing was sent');
    },
    screenshots: [{ name: 'the-test-step-cannot-send-anything' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'save-is-dead-until-the-test-has-run',
    kind: 'standard',
    description:
      'A profile saved without a test is a profile whose buttons the user has never seen arrive. The wizard makes '
      + 'the test the last gate rather than an optional extra, so somebody who clicks straight through still finds '
      + 'out before a game session whether BetterFingers can see their controller at all.',
    backendState: inputBackend(),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await reachRehearsal(page);
    },
    async expects(page) {
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-rehearsed', 'false');
      await expect(page.locator('#sdUtilGameSetupSaveButton')).toBeDisabled();
      expect(profileSaveCalls.length, 'nothing may be saved before the test').toBe(0);

      await page.click('#sdUtilGameSetupRehearseButton');
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-rehearsed', 'true');
      await expect(page.locator('#sdUtilGameSetupSaveButton')).toBeEnabled();
    },
    screenshots: [{ name: 'save-is-dead-until-the-test-has-run' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'saving-writes-the-profile-and-the-device-level-bindings',
    kind: 'standard',
    description:
      'The per-application layer goes into the bindings slot Wave 7 reserved on the profile, using the same action '
      + 'ids the device and global layers use — one vocabulary, one resolver, three layers. The bindings are ALSO '
      + 'written at device level, because "the left bumper on my flight stick" is a fact about the stick and must '
      + 'survive switching to a different game.',
    backendState: inputBackend(),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await reachRehearsal(page);
      await page.click('#sdUtilGameSetupRehearseButton');
      await page.fill('#sdUtilGameSetupProfileName', 'rocket_league');
      await page.click('#sdUtilGameSetupSaveButton');
    },
    async expects(page) {
      await expect.poll(() => profileSaveCalls.length).toBe(1);
      const profile = profileSaveCalls[0].profile;
      expect(profile.id).toBe('rocket_league');
      expect(profile.injection_policy).toBe('review_only');
      expect(Object.keys(profile.bindings).sort())
        .toEqual(['command.begin', 'dictation.begin']);
      // Wave 7's rule survives the wizard: no window title, ever.
      expect(profile.match.window_patterns).toEqual([]);

      expect(bindingSetCalls.length, 'both bindings go to the device layer too').toBe(2);
      for (const call of bindingSetCalls) {
        expect(call.device_key).toBe(DEVICE);
      }
      await expect(page.locator('#sdUtilGameSetupGroup')).toHaveAttribute('data-wizard-saved', 'true');
    },
    screenshots: [{ name: 'saving-writes-the-profile-and-the-device-level-bindings' }],
  },
  {
    area: 'wave10-input',
    ui: 'signal-desk-prod',
    name: 'a-build-without-the-input-routes-says-so',
    kind: 'standard',
    description:
      'Backend traffic reaches this feature through the main-process proxy\'s exact (method, route) allowlist. If '
      + 'the /input routes are missing the wizard says so in one sentence rather than rendering a form whose Save '
      + 'button silently does nothing — an empty form and a disconnected feature look identical, and only one of '
      + 'them means "you have not set anything up yet".',
    backendState: () => ({
      ...readyProfile(),
      'GET /input/bindings': { status: 404, body: { detail: 'not mounted' } },
    }),
    async navigate(page) {
      resetCaptures();
      await openGameSetup(page);
      await page.click('#sdUtilGameSetupDetectButton');
    },
    async expects(page) {
      await expect(page.locator('#sdUtilGameSetupMessage')).toContainText('Could not look for controllers');
      await expect(page.locator('#sdUtilGameSetupSaveButton')).toBeDisabled();
      expect(profileSaveCalls.length).toBe(0);
    },
    screenshots: [{ name: 'a-build-without-the-input-routes-says-so' }],
  },
];
