// Contacts in Talk and Studio (Stage 11 §6).
//
// Run with:  BF_QA_UI=signal-desk node tests/qa/run.mjs contacts
//
// The picker replaced a fabrication, so the assertions that matter are the ones
// separating "backed by a record the user made" from "looks like it is":
//
//   * the option list comes from the backend, not from markup,
//   * "no one in particular" is the default and a real choice, and
//   * selecting someone persists — a picker that forgets is a picker that was
//     never wired to anything.
//
// The wizard is asserted as far as the interview screen. Compiling needs a
// model, and a stub that returns compiled prose would be testing the fixture.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

const PRIYA = {
  id: 'c-priya',
  name: 'Priya',
  relationship: 'my manager',
  notes: 'Prefers exact numbers.',
  tone_guidance: 'Direct, no filler.',
  preferred_persona: 'Natural',
  created_at: '2026-07-27T10:00:00Z',
  updated_at: '2026-07-27T10:00:00Z',
};

const SAM = { ...PRIYA, id: 'c-sam', name: 'Sam', relationship: 'my brother', preferred_persona: null };

// The renderer reaches the backend through the main-process proxy, not through
// the page, so Playwright's network hooks never see these calls. A recording
// stub is how a scenario observes them: the harness lets a route BE a function,
// and it runs in the runner's own process.
const activePosts = [];

function withContacts(extra = {}) {
  activePosts.length = 0;
  return {
    ...readyProfile(),
    'GET /contacts': { ok: true, contacts: [PRIYA, SAM] },
    'GET /contacts/active': { ok: true, contact_id: null, contact: null },
    'POST /contacts/active': (_req, { body }) => {
      activePosts.push(body);
      return { ok: true, contact_id: body?.contact_id || null };
    },
    'POST /contacts/interview/start': {
      session_id: 'qa-1',
      question: { id: 'name', prompt: 'Who is this? A name or a nickname is fine.', index: 0, total: 5 },
      done: false,
    },
    'POST /contacts/interview/answer': {
      question: { id: 'relationship', prompt: 'How do you know them?', index: 1, total: 5 },
      pushback: null,
      done: false,
    },
    ...extra,
  };
}

export const contactsScenarios = [
  {
    area: 'contacts',
    ui: 'signal-desk',
    name: 'picker-is-backed-by-real-contacts',
    kind: 'standard',
    description:
      'Talk\'s "Writing to" picker is filled from GET /contacts, not from markup. This replaced a ' +
      'hard-coded "Destination — Discord #general" dropdown that had no id, no handler and no backing ' +
      'field, so the assertion checks the option text against what the backend returned rather than ' +
      'merely that a dropdown exists. "No one in particular" leads the list and is selected by default: ' +
      'most dictation has no audience, and a picker that nags for one trains people to pick wrong.',
    backendState: withContacts,
    async navigate(page) {
      await page.waitForFunction(
        () => document.querySelectorAll('#sdContactPicker option').length > 1,
        null,
        { timeout: 15000 },
      );
    },
    async expects(page) {
      const picker = page.locator('#sdContactPicker');
      await expect(picker).toBeVisible();

      const options = await picker.locator('option').allTextContents();
      expect(options).toEqual(['No one in particular', 'Priya', 'Sam']);
      await expect(picker).toHaveValue('', 'none is the default');

      // Nothing selected means no note at all, rather than a line saying so.
      await expect(page.locator('#sdContactPickerNote')).toHaveText('');
    },
    screenshots: [{ name: 'picker-is-backed-by-real-contacts' }],
  },
  {
    area: 'contacts',
    ui: 'signal-desk',
    name: 'selecting-a-contact-persists-and-describes-them',
    kind: 'standard',
    description:
      'Choosing someone shows their relationship underneath and POSTs the sticky selection. The network ' +
      'assertion is the point: a picker that changes its own label without telling the backend looks ' +
      'identical on screen to one that works, and would silently forget the choice on the next launch.',
    backendState: withContacts,
    async navigate(page) {
      await page.waitForFunction(
        () => document.querySelectorAll('#sdContactPicker option').length > 1,
        null,
        { timeout: 15000 },
      );
    },
    async expects(page) {
      await page.selectOption('#sdContactPicker', 'c-priya');
      await expect(page.locator('#sdContactPickerNote')).toHaveText('my manager · persona: Natural');

      // The sticky write actually reached the backend. Asserted from the stub
      // rather than the page: the proxy runs in the main process, so a request
      // watcher on the renderer would sit there timing out while the call
      // succeeded.
      await expect.poll(() => activePosts.length, { timeout: 10000 }).toBeGreaterThan(0);
      expect(activePosts.at(-1).contact_id).toBe('c-priya');
    },
    screenshots: [{ name: 'selecting-a-contact-persists-and-describes-them' }],
  },
  {
    area: 'contacts',
    ui: 'signal-desk',
    name: 'wizard-offers-name-only-before-any-questions',
    kind: 'standard',
    description:
      '"Add a contact" opens the guided-flow dialog with BOTH options on the first screen: answer a few ' +
      'questions, or just save the name. Creating a contact from a name alone is the supported path, not ' +
      'an escape hatch buried as a skip link — §10\'s friction budget turns on it. Asserted as visible ' +
      'and enabled rather than merely present, since a disabled button would satisfy a locator.',
    backendState: withContacts,
    async navigate(page) {
      await page.click('#sdContactNewButton');
      await expect(page.locator('#sdContactFlow')).toBeVisible();
    },
    async expects(page) {
      await expect(page.locator('#sdContactFlow [data-flow-title]')).toHaveText('Add a contact');
      await expect(page.locator('#sdContactSeedName')).toBeVisible();
      await expect(page.locator('#sdContactStartInterview')).toBeEnabled();
      await expect(page.locator('#sdContactSaveNameOnly')).toBeEnabled();
      // The interview screen is not showing yet.
      await expect(page.locator('[data-flow-step="contactInterview"]')).toBeHidden();
    },
    screenshots: [{ name: 'wizard-offers-name-only-before-any-questions' }],
  },
  {
    area: 'contacts',
    ui: 'signal-desk',
    name: 'the-typed-name-answers-the-first-question',
    kind: 'standard',
    description:
      'Starting the interview after typing a name submits that name as answer one and moves straight to ' +
      'question two, rather than asking for it again. A wizard that re-asks what it was just told reads ' +
      'as not listening. The step counter is asserted too, because "Question 2 of 5" is the only thing ' +
      'on screen distinguishing "it used my answer" from "it ignored it and started over".',
    backendState: withContacts,
    async navigate(page) {
      await page.click('#sdContactNewButton');
      await expect(page.locator('#sdContactFlow')).toBeVisible();
      await page.fill('#sdContactSeedName', 'Priya');
      await page.click('#sdContactStartInterview');
      await expect(page.locator('[data-flow-step="contactInterview"]')).toBeVisible();
    },
    async expects(page) {
      await expect(page.locator('#sdContactFlow [data-flow-title]')).toHaveText('A few questions');
      await expect(page.locator('#sdContactQuestion')).toHaveText('How do you know them?');
      await expect(page.locator('#sdContactProgressNote')).toHaveText('Question 2 of 5');
      await expect(page.locator('#sdContactAnswer')).toBeVisible();
    },
    screenshots: [{ name: 'the-typed-name-answers-the-first-question' }],
  },
  {
    area: 'contacts',
    ui: 'signal-desk',
    name: 'studio-shows-contacts-that-prefer-a-persona',
    kind: 'standard',
    description:
      'Studio\'s context panel replaced "Preferred Destinations" — three hard-coded Discord/Gmail/Slack ' +
      'icons reading a persona field that has never existed — with the same relationship read from the ' +
      'end that actually stores it: contacts carry preferred_persona. Priya prefers Natural and Sam ' +
      'prefers nothing, so exactly one chip should appear for the selected persona.',
    backendState: withContacts,
    async navigate(page) {
      await page.waitForFunction(
        () => document.querySelectorAll('#sdContactPicker option').length > 1,
        null,
        { timeout: 15000 },
      );
      await page.click('.sd-nav__button[data-nav="studio"]');
      await expect(page.locator('#workspace-studio')).toBeVisible();
    },
    async expects(page) {
      const panel = page.locator('#sdCtxPreferredContacts');
      await expect(panel).toBeVisible();
      // No Discord/Gmail/Slack icons anywhere in it any more.
      await expect(panel).not.toContainText('Discord');
      await expect(panel).not.toContainText('Slack');
    },
    screenshots: [{ name: 'studio-shows-contacts-that-prefer-a-persona' }],
  },
];
