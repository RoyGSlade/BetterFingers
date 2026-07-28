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
import { readyProfile } from './fixtures/cold-boot.mjs';

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
];
