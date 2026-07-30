// Talk's draft editor (SPEC 6 keystone) driven by a real draft.
//
// Until now Talk showed placeholder prose and nothing else: the refined-message
// card was a <p>, there was no action row, and drafts.js -- the module the
// shipping dashboard uses for accept/decline/retry/send/rewrite -- was not
// mounted here at all. Four keyboard shortcuts were bound to nothing.
//
// These scenarios assert the editor is a REAL editable surface fed by backend
// data, because the failure mode being guarded against is precisely a
// convincing-looking card that displays text and does nothing with it.

import { expect } from '@playwright/test';
import { coldBoot, readyProfile } from './fixtures/cold-boot.mjs';

const DRAFT = {
  id: 42,
  raw_text: 'okay so i should be there around six ill message you when im leaving',
  final_text: "I should be there around six. I'll message you when I'm leaving.",
  status: 'pending',
  confidence: { score: 0.94, avg_logprob: -0.2, no_speech_prob: 0.01 },
  token_count: 14,
  token_limit: 1200,
  long_text: false,
  metadata: { duration_seconds: 4.2, stop_reason: 'silence' },
};

// readyProfile, not coldBoot: these scenarios are about editing a transcribed
// draft, which a profile with no speech model could not have produced. It also
// keeps the first-run banner off screen, where it belongs for a set-up install.
const withDraft = () => ({
  ...readyProfile(),
  'GET /drafts/latest': { draft: DRAFT },
  'GET /drafts': { drafts: [DRAFT] },
});

// --- editing-teaches-only-with-approval's request capture ---------------------
//
// The capture MUST live in the stub handler, not on Playwright's page:
// renderer backend traffic goes through the main-process proxy over IPC
// (Phase 3c -- the page never holds the origin or token), so page-level
// `page.on('request')` NEVER sees a backend call and would count zero
// forever, passing the "saving performed zero calls" assertion vacuously and
// failing the "confirm performed exactly one" assertion even when the app
// behaves perfectly. The stub is the one place every real backend request
// lands. The array is module-scoped and reset in navigate(); backendState()
// is rebuilt per run, so its handler closure always points at the fresh
// array.
let teachExampleRequests = [];

export const signalDeskTalkScenarios = [
  {
    area: 'signal-desk-talk',
    ui: 'signal-desk',
    name: 'draft-editor-is-real-and-editable',
    kind: 'standard',
    description:
      'The refined-message card is a real <textarea> carrying the backend draft, not a paragraph of placeholder ' +
      'text. Asserts it exposes a selection API (drafts.js reads .value/.selectionStart/.selectionEnd for Read ' +
      'Selection and for the edit diff that feeds dictionary suggestions), that it holds the draft\'s final text, ' +
      'and that typing into it actually changes the value -- a styled contenteditable or a disabled box would ' +
      'look identical in a screenshot and fail here.',
    backendState: withDraft,
    async navigate(_page) {},
    async expects(page) {
      const editor = page.locator('#sdRefinedHero');
      await expect(editor).toBeVisible();

      // A real form control, not a dressed-up paragraph.
      const tag = await editor.evaluate((el) => el.tagName.toLowerCase());
      expect(tag, 'the draft editor must be a real textarea').toBe('textarea');

      const hasSelectionApi = await editor.evaluate(
        (el) => typeof el.selectionStart === 'number' && typeof el.selectionEnd === 'number',
      );
      expect(hasSelectionApi, 'editor exposes no selection API — drafts.js needs one').toBe(true);

      // Fed by the backend, not by markup.
      await expect(editor).toHaveValue(DRAFT.final_text);

      // Genuinely editable.
      await editor.click();
      await editor.fill('Edited by QA.');
      await expect(editor).toHaveValue('Edited by QA.');
    },
    screenshots: [{ name: 'draft-editor-is-real-and-editable' }],
  },
  {
    area: 'signal-desk-talk',
    ui: 'signal-desk',
    name: 'decision-row-and-revise-drawer',
    kind: 'standard',
    description:
      'Accept / Decline / Retry / Copy exist and are enabled for a pending draft, and the Revise button opens the ' +
      'rewrite drawer it used to stub out. The decision row sits below the drawer so Accept and Decline do not ' +
      'move when it opens — a Decline button that shifts position is one that gets mis-clicked.',
    backendState: withDraft,
    async navigate(_page) {},
    async expects(page) {
      for (const id of ['sdAcceptButton', 'sdDeclineButton', 'sdCopyButton', 'sdSendButton']) {
        await expect(page.locator(`#${id}`), `#${id} missing`).toBeVisible();
        await expect(page.locator(`#${id}`), `#${id} should be enabled for a pending draft`).toBeEnabled();
      }

      // Drawer starts closed and the Revise button says so.
      const drawer = page.locator('#sdReviseDrawer');
      await expect(drawer).toBeHidden();
      await expect(page.locator('#sdReviseButton')).toHaveAttribute('aria-expanded', 'false');

      // Accept/Decline must not move when the drawer opens.
      const before = await page.locator('#sdDeclineButton').boundingBox();
      await page.click('#sdReviseButton');
      await expect(drawer).toBeVisible();
      await expect(page.locator('#sdReviseButton')).toHaveAttribute('aria-expanded', 'true');
      for (const id of ['sdSaveEditButton', 'sdRewriteShorterButton', 'sdRewriteClearerButton', 'sdRewriteToneButton']) {
        await expect(page.locator(`#${id}`)).toBeVisible();
      }
      const after = await page.locator('#sdDeclineButton').boundingBox();
      expect(after.y, 'Decline moved when the Revise drawer opened').toBe(before.y);

      await page.click('#sdReviseButton');
      await expect(drawer).toBeHidden();
    },
    screenshots: [{ name: 'decision-row-and-revise-drawer' }],
  },
  {
    area: 'signal-desk-talk',
    ui: 'signal-desk',
    name: 'delivery-controls-replace-destination',
    kind: 'standard',
    description:
      'The card used to show "Destination: Discord" — fiction, since no draft carries a destination and the app ' +
      'has no concept of a channel or a person. It now exposes the two things the user genuinely controls: ' +
      'review-first vs send-immediately, and how the text is inserted at the cursor. The insert method feeds ' +
      'drafts.js\'s getSelectedSendAction() hook, so it drives real behaviour rather than decorating the card.',
    backendState: withDraft,
    async navigate(_page) {},
    async expects(page) {
      await expect(page.locator('#sdDeliveryMode')).toBeVisible();
      await expect(page.locator('#sdDeliveryType')).toBeVisible();

      // The fabricated destination is gone for good.
      await expect(page.locator('#sdDestinationLabel')).toHaveCount(0);
      const card = await page.locator('.sd-refined-card').innerText();
      expect(card, 'the fabricated Discord destination is back').not.toContain('Discord');

      // Insert method is wired to the hook drafts.js reads.
      await page.selectOption('#sdDeliveryType', 'paste');
      const selected = await page.evaluate(() => document.getElementById('sdDeliveryType').value);
      expect(selected).toBe('paste');
    },
    screenshots: [{ name: 'delivery-controls-replace-destination' }],
  },

  // ---------------------------------------------------------------------
  // Wave 2 Gate 2 (Task C): capture actions, the single delivery selector,
  // the send-result surface, confidence-links-to-Settings, and the D-0018
  // teaching-from-edits restoration -- all against the PRODUCTION Signal
  // Desk composition root (signal-desk.html, `ui: 'signal-desk-prod'`), not
  // the design/mockup preview the four scenarios above target. See
  // harness.mjs's UI_TARGETS comment for why persona-learning-shaped
  // scenarios belong on this target rather than 'signal-desk': the markup
  // and wiring under test here (features/talkCapture.js, the segmented
  // delivery control's real resolveSendAction() binding, features/
  // talkTeaching.js) exist only on the page that actually ships.
  // ---------------------------------------------------------------------

  {
    area: 'signal-desk-talk-prod',
    ui: 'signal-desk-prod',
    name: 'talk-capture-actions-exist',
    kind: 'standard',
    description:
      'The production Talk page has a real capture action row -- Start Recording, Stop Recording, Emergency Stop ' +
      '(features/talkCapture.js) -- where until Wave 2 the Signal Core ring was display-only and the hotkey was ' +
      'the only way to start or stop a recording. On a cold profile with no draft and nothing recording, Start is ' +
      'enabled (idle -> can start), Stop is disabled (nothing to stop), and Emergency Stop is enabled regardless -- ' +
      'a stop control that can be greyed out is the exact failure mode this row exists to prevent.',
    backendState: coldBoot,
    async navigate(_page) {},
    async expects(page) {
      for (const id of ['sdCaptureStartButton', 'sdCaptureStopButton', 'sdEmergencyStopButton']) {
        await expect(page.locator(`#${id}`), `#${id} missing`).toBeVisible();
      }
      await expect(page.locator('#sdCaptureStartButton'), 'Start should be enabled while idle').toBeEnabled();
      await expect(page.locator('#sdCaptureStopButton'), 'Stop should be disabled with nothing recording').toBeDisabled();
      await expect(
        page.locator('#sdEmergencyStopButton'),
        'Emergency Stop must stay enabled with no draft and no recording in progress',
      ).toBeEnabled();
    },
    screenshots: [{ name: 'talk-capture-actions-exist' }],
  },

  {
    area: 'signal-desk-talk-prod',
    ui: 'signal-desk-prod',
    name: 'talk-single-delivery-selector',
    kind: 'standard',
    description:
      'DIRECTOR RULING (Wave 2 Gate 2): Talk used to carry two competing delivery controls plus a decorative send ' +
      'chevron with no popover anywhere in the repo. Exactly ONE survives -- #sdDeliverySegmented -- so this ' +
      'asserts the old #sdDeliveryType dropdown and #sdSendChevronButton are gone outright (not merely hidden). ' +
      'D-0036 (docs/release/DECISIONS.md) further narrows that survivor to Paste only for v0.2.0-alpha.1 -- UI-06-038 ' +
      'is `intentional_cut` -- so this also asserts Type and Copy are gone as user choices (not merely hidden) and ' +
      'exactly one option, Paste, is offered. The primary button label (#sdSendButtonLabel) must still always state ' +
      'what Send will actually do, and clicking the one remaining option must still visibly move the control -- an ' +
      'existence check alone would pass a dead binding.',
    backendState: withDraft,
    async navigate(_page) {},
    async expects(page) {
      const segmented = page.locator('#sdDeliverySegmented');
      await expect(segmented, '#sdDeliverySegmented must be the one delivery selector').toBeVisible();
      await expect(
        segmented.locator('[data-delivery-option]'),
        'D-0036: exactly one delivery option (Paste) may be offered',
      ).toHaveCount(1);
      await expect(segmented.locator('[data-delivery-option="paste"]', { hasText: 'Paste' })).toBeVisible();
      for (const option of ['type', 'copy']) {
        await expect(
          segmented.locator(`[data-delivery-option="${option}"]`),
          `D-0036: "${option}" must be gone as a user choice, not merely hidden`,
        ).toHaveCount(0);
      }

      await expect(page.locator('#sdDeliveryType'), 'the old insert-method dropdown must be gone outright').toHaveCount(0);
      await expect(page.locator('#sdSendChevronButton'), 'the decorative split-button chevron must be gone outright').toHaveCount(0);

      // Cold-boot output settings: review_first + injection supported, so the
      // resolved default (no explicit selection) is already 'paste' -- see
      // talkWorkspace.js's resolveSendAction()/primaryActionLabel().
      await expect(page.locator('#sdSendButtonLabel')).toHaveText('Paste at Cursor');

      // FUNCTIONAL, not just present: clicking the one remaining option must
      // still visibly press it and the label must still reflect it -- proving
      // the binding survived the markup change rather than becoming dead code.
      await page.click('#sdDeliverySegmented [data-delivery-option="paste"]');
      await expect(page.locator('#sdDeliverySegmented [data-delivery-option="paste"]')).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('#sdSendButtonLabel')).toHaveText('Paste at Cursor');
    },
    screenshots: [{ name: 'talk-single-delivery-selector' }],
  },

  {
    area: 'signal-desk-talk-prod',
    ui: 'signal-desk-prod',
    name: 'talk-send-result-surface',
    kind: 'standard',
    description:
      'server.py\'s perform_output_action already returns requested/actual action, fallback + fallback_reason, a ' +
      'clipboard_result, and the draft\'s own status on every send -- until Wave 2 the production page threw all ' +
      'of it away (renderSendResult() was a documented no-op), so a send that silently fell back to the clipboard ' +
      'looked identical to one that typed into the target app. This stubs a send whose backend response reports a ' +
      'real fallback (input injection unsupported, copied to clipboard instead) and asserts the send-result panel ' +
      'shows every one of those six facts truthfully, sourced from the real response.',
    backendState: () => {
      // Stateful on purpose: after the send POST, the real backend's GET
      // /drafts and /drafts/latest return the SENT draft with its
      // send_result. A static stub that keeps serving the pre-send draft
      // makes handleSendClick's follow-up refreshDrafts() erase the
      // just-rendered result panel -- a fixture lie, not app behavior.
      const sentDraft = {
        ...DRAFT,
        status: 'sent',
        send_outcome: 'sent',
        send_result: {
          ok: true,
          requested_action: 'paste',
          actual_action: 'copy_only',
          fallback: true,
          fallback_reason: 'input_injection_unsupported',
          clipboard_result: { ok: true, message: 'Copied to clipboard.' },
          message: 'Input injection unavailable -- copied to clipboard instead.',
        },
      };
      let sent = false;
      return {
        ...withDraft(),
        'GET /drafts/latest': () => ({ draft: sent ? sentDraft : DRAFT }),
        'GET /drafts': () => ({ drafts: [sent ? sentDraft : DRAFT] }),
        'POST /drafts/42/send': () => {
          sent = true;
          return sentDraft;
        },
      };
    },
    async navigate(_page) {},
    async expects(page) {
      await expect(page.locator('#sdSendResult'), 'send result panel should be hidden before any send').toBeHidden();

      await page.click('#sdSendButton');

      await expect(page.locator('#sdSendResult')).toBeVisible();
      await expect(page.locator('#sdSendResultRequested')).toHaveText('paste');
      await expect(page.locator('#sdSendResultActual')).toHaveText('copy_only');
      await expect(page.locator('#sdSendResultFallback')).toHaveText('Yes');
      await expect(page.locator('#sdSendResultFallbackReason')).toHaveText('Input injection unavailable on this system');
      await expect(page.locator('#sdSendResultClipboard')).toHaveText('text copied');
      await expect(page.locator('#sdSendResultSubmission')).toHaveText('sent');
    },
    screenshots: [{ name: 'talk-send-result-surface' }],
  },

  {
    area: 'signal-desk-talk-prod',
    ui: 'signal-desk-prod',
    name: 'talk-confidence-links-to-settings',
    kind: 'standard',
    description:
      'Talk\'s context panel used to be an id-less, handler-less <input type="range"> labelled "Confidence ' +
      'threshold" -- a control that looked like it set the gate (confidence_force_review_enabled / ' +
      '_below / confidence_auto_send_above) while actually setting nothing, because that gate is a Settings-owned ' +
      'profile field enforced by send_policy.py. Talk now DISPLAYS the draft confidence and a link to the real ' +
      'owner (#sdConfidenceSettingsLink) instead of miming a second, disconnected control. Asserts the fake range ' +
      'input is gone from Talk\'s context content specifically (not merely renamed).',
    backendState: withDraft,
    async navigate(_page) {},
    async expects(page) {
      await expect(page.locator('#sdConfidenceValue')).toHaveText('94%');
      await expect(page.locator('#sdConfidenceSettingsLink')).toBeVisible();

      const talkContext = page.locator('.sd-context__content[data-context-for="talk"]');
      await expect(
        talkContext.locator('input[type="range"]'),
        'Talk must not carry its own threshold-editing control -- Settings owns that field',
      ).toHaveCount(0);
    },
    screenshots: [{ name: 'talk-confidence-links-to-settings' }],
  },

  {
    area: 'signal-desk-talk-prod',
    ui: 'signal-desk-prod',
    name: 'editing-teaches-only-with-approval',
    kind: 'standard',
    description:
      'D-0018 RESTORATION. Wave 1 QA had to substitute the original privacy-invariant assertion -- "editing never ' +
      'learns anything on its own" became "running Test Persona never learns anything on its own" -- because ' +
      'Studio\'s teach panel has no live-draft concept. This is the real trigger, restored: editing the draft in ' +
      '#sdRefinedHero and saving it must NEVER by itself call POST /personas/:name/examples -- saving only offers ' +
      '(#sdTalkTeachPanel appears, showing the raw input, the pre-edit model output, and the saved edit side by ' +
      'side). Only checking consent and clicking Confirm reaches the network, and it must send the EDITED text as ' +
      '`out`, never the model\'s pre-edit output. Written to fail loudly if saving an edit ever teaches on its own.',
    backendState: () => ({
      ...withDraft(),
      'GET /personas': { friendly: { prompt: 'Be warm and concise.' } },
      'GET /settings/profiles': {
        active_profile: 'Default',
        profiles: ['Default'],
        settings: { ...readyProfile()['GET /settings/profiles'].settings, current_preset: 'friendly' },
      },
      'GET /personas/friendly/examples': { persona: 'friendly', examples: [] },
      'POST /drafts/42/edit': (_req, { body }) => ({
        ...DRAFT,
        final_text: body?.final_text ?? DRAFT.final_text,
      }),
      'POST /personas/friendly/examples': (_req, { body }) => {
        teachExampleRequests.push(body ?? null);
        return {
          ok: true,
          duplicate: false,
          id: `ex-${teachExampleRequests.length}`,
          evicted_id: null,
        };
      },
    }),
    async navigate(_page) {
      teachExampleRequests = [];
    },
    async expects(page) {
      try {
        const EDITED_TEXT = "I'll be there closer to six thirty, message you when I'm on my way.";

        const editor = page.locator('#sdRefinedHero');
        await editor.click();
        await editor.fill(EDITED_TEXT);

        // Save Edit lives in the Revise drawer.
        const drawer = page.locator('#sdReviseDrawer');
        if (!(await drawer.isVisible().catch(() => false))) {
          await page.click('#sdReviseButton');
          await expect(drawer).toBeVisible();
        }
        await page.click('#sdSaveEditButton');

        // Saving alone must never teach: the offer panel appears, but
        // nothing was learned yet.
        const panel = page.locator('#sdTalkTeachPanel');
        await expect(panel, 'saving an edit must offer to teach, not skip straight past it').toBeVisible();
        await expect(page.locator('#sdTalkTeachRaw')).toHaveText(DRAFT.raw_text);
        await expect(page.locator('#sdTalkTeachModel')).toHaveText(DRAFT.final_text);
        await expect(page.locator('#sdTalkTeachEdited')).toHaveText(EDITED_TEXT);

        expect(
          teachExampleRequests.length,
          'saving an edit must perform ZERO backend calls to /personas/friendly/examples',
        ).toBe(0);
        await expect(page.locator('#sdTalkTeachConfirmButton'), 'Confirm must stay disabled until consent is checked').toBeDisabled();

        await page.check('#sdTalkTeachConsent');
        await expect(page.locator('#sdTalkTeachConfirmButton')).toBeEnabled();
        await page.click('#sdTalkTeachConfirmButton');

        await expect
          .poll(() => teachExampleRequests.length, {
            message: 'exactly one POST to /personas/friendly/examples should follow the explicit consent + confirm click',
          })
          .toBe(1);
        const learned = teachExampleRequests[0];
        expect(learned?.raw, 'the raw text sent must be what the user said').toBe(DRAFT.raw_text);
        expect(learned?.out, 'the learned output must be the EDITED text, not the model\'s pre-edit output').toBe(EDITED_TEXT);
        expect(learned?.out).not.toBe(DRAFT.final_text);
        expect(learned?.consent, 'consent must be sent true -- this is the only consent-gated call site').toBe(true);
      } finally {
        // Stub-side capture holds no page listener; nothing to tear down.
        // (navigate() resets the array for the next run.)
      }
    },
    screenshots: [{ name: 'editing-teaches-only-with-approval' }],
  },
];
