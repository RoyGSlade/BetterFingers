// Wave 7 QA: application context and automatic profiles on the production
// composition root.
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs wave7-app-context
//
// PREREQUISITE (stated because it is the difference between these scenarios
// proving something and passing vacuously): renderer backend traffic reaches
// the stub through the MAIN-PROCESS proxy, whose ROUTE_ALLOWLIST in
// app/src/main/backendProxy.js is an exact (method, route) table -- the stub is
// BEHIND the proxy, so the allowlist gates QA exactly as it gates production.
//
// That wiring has landed: server.py mounts the route module, the allowlist
// carries GET /app-context/status + /app-context/profiles and
// POST /app-context/override + /app-context/pin, and api/backend.js defines
// fetchAppContextStatus / fetchAppProfiles / overrideAppProfile / pinAppProfile.
//
// ONE PIECE IS STILL OUTSTANDING and these scenarios cannot pass without it:
// those four helpers are DEFINED in api/backend.js but are not listed in its
// `export { ... }` block, so `import * as api` sees them as undefined and
// features/applicationProfiles.js correctly reports itself UNAVAILABLE. That
// file is integration-owned; the one-line fix is D-3b in
// docs/release/WAVE7_INTEGRATION_DIFFS.md.
//
// REQUEST CAPTURE (D-0021). Every capture lives in the STUB HANDLER, never on
// `page.on('request')`: the renderer never issues the HTTP request itself, so a
// page-level listener counts zero forever -- passing every "performed no calls"
// assertion vacuously and failing every "performed exactly one".
//
// SELECTORS (D-0023). Attribute selectors throughout, never `:has-text`. The
// profile rows carry data-app-profile / data-active / data-selected precisely
// so a row can be addressed by identity rather than by the words inside it --
// text matching would silently pick a different row the moment a label changes.
//
// WHAT THESE SCENARIOS ARE REALLY FOR. The Wave 7 rule is that the app may pick
// a profile and may NOT infer who you are writing to. That failure does not
// crash or look broken; it looks like a helpful new label. So the last scenario
// asserts, against a stub that deliberately returns recipient-shaped fields,
// that none of them reach the screen.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

const PROFILE_DEFAULT = {
  schema_version: 1,
  id: 'default',
  match: { process_names: [], window_patterns: [] },
  writing_preset: null,
  performance_preset: 'balanced',
  injection_policy: 'auto',
  tts: { announce_activation: false },
  bindings: {},
};

const PROFILE_DISCORD = {
  schema_version: 1,
  id: 'discord',
  match: { process_names: ['discord', 'discord.exe'], window_patterns: ['^discord'] },
  writing_preset: null,
  performance_preset: 'low_latency',
  injection_policy: 'auto',
  tts: { announce_activation: false },
  bindings: {},
};

const PROFILE_ROCKET_LEAGUE = {
  schema_version: 1,
  id: 'rocket_league',
  match: { process_names: ['rocketleague.exe'], window_patterns: ['rocketleague'] },
  writing_preset: null,
  performance_preset: 'minimal',
  injection_policy: 'review_only',
  tts: { announce_activation: true },
  bindings: {},
};

const PROFILES = [PROFILE_DEFAULT, PROFILE_DISCORD, PROFILE_ROCKET_LEAGUE];

function context(extra = {}) {
  return {
    app_key: '',
    detected: false,
    profile_id: 'default',
    source: 'unknown',
    override_active: false,
    pinned: false,
    deferred: false,
    pending_profile_id: null,
    announcement: '',
    writing_preset: null,
    performance_preset: 'balanced',
    injection_policy: 'auto',
    tts: { announce_activation: false },
    bindings: {},
    gaming_policy: { active: false },
    ...extra,
  };
}

const DISCORD_CONTEXT = context({
  app_key: 'discord',
  detected: true,
  profile_id: 'discord',
  source: 'matched',
  performance_preset: 'low_latency',
});

// --- captures ----------------------------------------------------------------

let overrideWrites = [];
let pinWrites = [];

function withAppContext(current = context(), extra = {}) {
  return () => {
    // STATEFUL, deliberately: the real service holds a temporary override in
    // memory (D-0024), so GET /app-context/status reports the held profile
    // until it is cleared. A static status stub is unfaithful in a way that
    // does not merely under-test -- the status bar re-polls every 3s, so a
    // static stub actively repaints the rail back to the unheld profile a
    // moment after the override lands, and the scenario watches a race it
    // can only lose. Same class as the Wave 2 send stub and the Wave 5
    // contacts stub (D-0021, D-0023).
    let live = current;
    return {
    ...readyProfile(),
    'GET /app-context/status': () => ({ ok: true, context: live }),
    'GET /app-context/profiles': {
      ok: true,
      profiles: PROFILES,
      builtin_ids: PROFILES.map((p) => p.id),
      pinned: {},
      performance_presets: ['balanced', 'low_latency', 'quality', 'minimal'],
      injection_policies: ['auto', 'type', 'paste', 'clipboard_only', 'review_only'],
      gaming_policy: {
        max_completion_tokens: 50,
        max_tts_sentences: 2,
        queue_tts: false,
        auto_submit: false,
        review_only: true,
        clipboard_fallback: true,
        minimal_overlay: true,
      },
    },
    'POST /app-context/override': (_req, { body }) => {
      overrideWrites.push(body);
      const id = (body && body.profile_id) || '';
      live = id
        ? context({ ...DISCORD_CONTEXT, profile_id: id, source: 'override', override_active: true })
        : current;
      return {
        ok: true,
        context: id
          ? context({ ...DISCORD_CONTEXT, profile_id: id, source: 'override', override_active: true })
          : DISCORD_CONTEXT,
      };
    },
    'POST /app-context/pin': (_req, { body }) => {
      pinWrites.push(body);
      const id = (body && body.profile_id) || '';
      // A pin is durable in the real store, so the next status poll still
      // reports it -- same faithfulness rule as the override above.
      live = id
        ? context({ ...DISCORD_CONTEXT, profile_id: id, source: 'pinned', pinned: true })
        : current;
      return {
        ok: true,
        app_key: 'discord',
        profile_id: id || null,
        context: id
          ? context({ ...DISCORD_CONTEXT, profile_id: id, source: 'pinned', pinned: true })
          : DISCORD_CONTEXT,
      };
    },
    ...extra,
    };
  };
}

async function openAppProfiles(page) {
  await page.click('.sd-nav__button[data-nav="settings"]');
  await expect(page.locator('#workspace-settings')).toBeVisible();
  await page.click('#sdSetNavAiCleanup');
  await expect(page.locator('#sdSetAppProfileGroup')).toBeVisible();
}

export const wave7AppContextScenarios = [
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'unknown-application-shows-no-status-cell',
    kind: 'standard',
    description:
      'With nothing detected -- the routine state on Wayland, which has no portable focused-window query -- the '
      + 'application-profile status cell is ABSENT, not an em dash and not the word "Default". Default is what an '
      + 'unidentified application resolves to, and both that and a genuine Default mean "the app is behaving '
      + 'normally"; a permanent rail cell announcing a profile would claim activity where there is none. The '
      + 'Settings group says plainly that the application could not be identified rather than leaving a blank.',
    backendState: withAppContext(context()),
    async navigate(page) {
      await openAppProfiles(page);
    },
    async expects(page) {
      await expect(
        page.locator('#sdStatusAppProfileCell'),
        'an unidentified application must not light a rail cell',
      ).toBeHidden();
      await expect(page.locator('#sdSetAppProfileCurrent')).toHaveText('Default');
      await expect(page.locator('#sdSetAppProfileSource')).toContainText('could not be identified');
      await expect(page.locator('#sdSetAppProfileDetected')).toContainText('Not identified');
      // Nothing to pin to, so the durable control refuses rather than pinning
      // to the empty app key -- which would apply to every unidentifiable
      // application at once.
      await expect(page.locator('#sdSetAppProfilePinButton')).toBeDisabled();
    },
    screenshots: [{ name: 'unknown-application-shows-no-status-cell' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'a-matched-application-fills-the-status-cell',
    kind: 'standard',
    description:
      'With Discord detected and matched, the rail cell appears and names the PROFILE -- not a person, not a '
      + 'channel. The Settings list marks exactly one row active, addressed by data-app-profile rather than by its '
      + 'label, so the assertion cannot be satisfied by a differently-named row that happens to contain the same '
      + 'text.',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      await openAppProfiles(page);
    },
    async expects(page) {
      await expect(page.locator('#sdStatusAppProfileCell')).toBeVisible();
      await expect(page.locator('#sdStatusAppProfileValue')).toHaveText('Discord');

      await expect(page.locator('#sdSetAppProfileCurrent')).toHaveText('Discord');
      await expect(page.locator('#sdSetAppProfileDetected')).toHaveText('discord');
      await expect(page.locator('[data-app-profile="discord"][data-active="true"]')).toHaveCount(1);
      await expect(page.locator('[data-app-profile][data-active="true"]')).toHaveCount(1);
      await expect(page.locator('[data-app-profile="rocket_league"][data-active="true"]')).toHaveCount(0);
    },
    screenshots: [{ name: 'a-matched-application-fills-the-status-cell' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'the-required-builtin-profiles-are-listed',
    kind: 'standard',
    description:
      'Every profile the backend reports is rendered as its own addressable row. Asserted by identity attribute, '
      + 'and asserted to include the match rules -- a profile row that shows a name but not what it matches gives '
      + 'the user no way to tell why an application behaved the way it did. The Default row states that it matches '
      + 'nothing automatically instead of showing an empty rule list, which reads as missing data.',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      await openAppProfiles(page);
    },
    async expects(page) {
      for (const id of ['default', 'discord', 'rocket_league']) {
        await expect(page.locator(`[data-app-profile="${id}"]`), id).toHaveCount(1);
      }
      await expect(page.locator('[data-app-profile="discord"]')).toContainText('discord.exe');
      await expect(page.locator('[data-app-profile="default"]')).toContainText('Matches nothing automatically');
      // The gaming profile discloses that it will not deliver automatically.
      await expect(page.locator('[data-app-profile="rocket_league"]')).toContainText('review_only');
    },
    screenshots: [{ name: 'the-required-builtin-profiles-are-listed' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'a-temporary-override-is-sent-and-shown-as-held',
    kind: 'standard',
    description:
      'Choosing an override issues exactly one POST /app-context/override carrying the chosen id, and the rail '
      + 'marks the profile as held rather than looking identical to an automatic match. An override the user '
      + 'forgot they set is precisely what the rail has to remind them about, and an override that repainted '
      + 'locally without reaching the backend would look perfect and change nothing about how text is delivered. '
      + 'The capture is stub-side (D-0021).',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      overrideWrites = [];
      await openAppProfiles(page);
    },
    async expects(page) {
      await page.selectOption('#sdSetAppProfileOverride', 'rocket_league');

      await expect.poll(() => overrideWrites.length, {
        message: 'choosing an override must issue exactly one write',
      }).toBe(1);
      expect(overrideWrites[0].profile_id).toBe('rocket_league');

      await expect(page.locator('#sdStatusAppProfileValue')).toHaveText('Rocket League (held)');
      await expect(page.locator('#sdSetAppProfileOverrideClear')).toBeEnabled();
    },
    screenshots: [{ name: 'a-temporary-override-is-sent-and-shown-as-held' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'clearing-the-override-sends-an-empty-id',
    kind: 'standard',
    description:
      'Clearing the override writes through an EMPTY profile id rather than re-sending the current profile. The '
      + 'difference is invisible on screen and total in effect: re-sending the current id would leave the override '
      + 'latched on the profile that happened to be active, so the next application switch would be silently '
      + 'ignored.',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      overrideWrites = [];
      await openAppProfiles(page);
      await page.selectOption('#sdSetAppProfileOverride', 'rocket_league');
      await expect.poll(() => overrideWrites.length).toBe(1);
    },
    async expects(page) {
      await page.click('#sdSetAppProfileOverrideClear');
      await expect.poll(() => overrideWrites.length).toBe(2);
      expect(overrideWrites[1].profile_id).toBe('');
    },
    screenshots: [{ name: 'clearing-the-override-sends-an-empty-id' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'always-use-here-pins-the-selected-profile',
    kind: 'standard',
    description:
      '"Always use this profile here" pins the profile the user SELECTED, not whichever one happens to be active. '
      + 'That bug writes a durable decision about the wrong profile, looks entirely correct at the moment it '
      + 'happens, and only surfaces the next time the application is focused -- so the stub-side capture of the '
      + 'pinned id, not the button state, is the assertion.',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      pinWrites = [];
      await openAppProfiles(page);
      await page.click('[data-app-profile-select="rocket_league"]');
      await expect(page.locator('[data-app-profile="rocket_league"][data-selected="true"]')).toHaveCount(1);
    },
    async expects(page) {
      await page.click('#sdSetAppProfilePinButton');

      await expect.poll(() => pinWrites.length, {
        message: 'the pin must reach the backend, not just repaint',
      }).toBe(1);
      expect(
        pinWrites[0].profile_id,
        'the SELECTED profile is pinned, never the merely active one',
      ).toBe('rocket_league');
      await expect(page.locator('#sdSetAppProfilePinButton')).toHaveText('Remove pin');
    },
    screenshots: [{ name: 'always-use-here-pins-the-selected-profile' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'a-pinned-profile-reads-as-a-user-decision',
    kind: 'standard',
    description:
      'A pinned resolution is described as the user\'s own decision, not as a rule this build shipped. Someone '
      + 'working out why an application behaves oddly needs to be able to tell those two apart; collapsing them '
      + 'into one "active profile" line leaves the pin invisible and unfindable.',
    backendState: withAppContext(
      context({ ...DISCORD_CONTEXT, source: 'pinned', pinned: true }),
    ),
    async navigate(page) {
      await openAppProfiles(page);
    },
    async expects(page) {
      await expect(page.locator('#sdSetAppProfileSource')).toContainText('pinned');
      await expect(page.locator('#sdSetAppProfilePinButton')).toHaveText('Remove pin');
      await expect(page.locator('#sdSetAppProfilePinNote')).toContainText('discord');
    },
    screenshots: [{ name: 'a-pinned-profile-reads-as-a-user-decision' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'spoken-activation-is-disclosed-as-off-with-no-switch',
    kind: 'standard',
    description:
      'Spoken profile announcements ship OFF, are disclosed as one short sentence and never queued, and there is '
      + 'NO control here that could turn them on -- the backend exposes no route to, and a switch that silently '
      + 'did nothing would be worse than the sentence. Same disclosure-without-a-dead-control shape as the Wave 5 '
      + 'traits panel (D-0006).',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      await openAppProfiles(page);
    },
    async expects(page) {
      const note = page.locator('#sdSetAppProfileAnnounceNote');
      await expect(note).toContainText('off');
      await expect(note).toContainText('one short sentence');
      await expect(note).toContainText('never queued');
      expect(
        await page.locator('#sdSetAppProfileGroup input[type="checkbox"], #sdSetAppProfileGroup button[role="switch"]').count(),
        'no control in this group may claim to enable announcements',
      ).toBe(0);
    },
    screenshots: [{ name: 'spoken-activation-is-disclosed-as-off-with-no-switch' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'no-recipient-is-ever-inferred-from-the-focused-application',
    kind: 'standard',
    description:
      'THE Wave 7 rule, asserted against a stub that deliberately lies: the backend returns recipient-, contact- '
      + 'and conversation-shaped fields alongside a matched Discord profile, and none of them may reach the '
      + 'screen. This failure does not crash and does not look broken -- it looks like a helpful new label naming '
      + 'the person you are apparently writing to, which the app has no way to know. Also asserts the rail cell '
      + 'still says only the profile name.',
    backendState: withAppContext(
      context({
        ...DISCORD_CONTEXT,
        recipient: 'Priya',
        contact_name: 'Priya',
        relationship: 'my manager',
        conversation_topic: 'the trip',
        user_intent: 'apologise',
      }),
    ),
    async navigate(page) {
      await openAppProfiles(page);
    },
    async expects(page) {
      await expect(page.locator('#sdStatusAppProfileValue')).toHaveText('Discord');

      const group = page.locator('#sdSetAppProfileGroup');
      for (const leak of ['Priya', 'my manager', 'the trip', 'apologise']) {
        await expect(group, `"${leak}" must never appear in the application-profile UI`)
          .not.toContainText(leak);
      }
      // And the whole rail, not just this one cell.
      await expect(page.locator('.sd-statusbar')).not.toContainText('Priya');
    },
    screenshots: [{ name: 'no-recipient-is-ever-inferred-from-the-focused-application' }],
  },
  {
    area: 'wave7-app-context',
    ui: 'signal-desk-prod',
    name: 'a-profile-switch-does-not-disturb-the-rest-of-the-rail',
    kind: 'standard',
    description:
      'Applying a profile is a data change, never a model change: the mic, speech-to-text and LLM cells read the '
      + 'same before and after. A profile switch that dropped and reloaded a model would turn alt-tabbing into a '
      + 'multi-second stall, which is exactly the interruption the activation design exists to avoid -- and the '
      + 'only visible symptom would be these cells flipping to "Not loaded".',
    backendState: withAppContext(DISCORD_CONTEXT),
    async navigate(page) {
      overrideWrites = [];
      await openAppProfiles(page);
    },
    async expects(page) {
      const before = {
        stt: await page.locator('#sdStatusSttValue').textContent(),
        llm: await page.locator('#sdStatusLlmValue').textContent(),
        mic: await page.locator('#sdStatusMicValue').textContent(),
      };

      await page.selectOption('#sdSetAppProfileOverride', 'rocket_league');
      await expect(page.locator('#sdStatusAppProfileValue')).toHaveText('Rocket League (held)');

      await expect(page.locator('#sdStatusSttValue')).toHaveText(before.stt);
      await expect(page.locator('#sdStatusLlmValue')).toHaveText(before.llm);
      await expect(page.locator('#sdStatusMicValue')).toHaveText(before.mic);
    },
    screenshots: [{ name: 'a-profile-switch-does-not-disturb-the-rest-of-the-rail' }],
  },
];
