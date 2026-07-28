// Wave 5 QA: persona guided flow, disclosed Settings toggles, and contacts.
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs wave5-studio
//
// These scenarios target the PRODUCTION composition root (signal-desk.html via
// the signal-desk-prod harness target), not the preview page. That matters
// most for the contacts scenarios: the preview seeds fixtures, and a manage
// list rendered from MOCK data would prove nothing about whether Delete
// reaches the backend.
//
// The three areas here map to the three Wave 5 deliverables whose failure
// modes are invisible in a screenshot:
//
//   1. persona-flow -- Edit must open the SAME dialog as New Persona, at a
//      different step, and must not be a second editor with its own save. A
//      screenshot of "an edit dialog" looks identical whether it patches the
//      persona or silently creates a duplicate, so the request capture below
//      is the actual evidence.
//   2. disclosure -- a toggle that discloses six things and a toggle that
//      discloses two look similar at a glance and read completely differently.
//      Each required line is asserted by content, and the audience control is
//      asserted to be UNSWITCHABLE, which is the whole of D-0005.
//   3. contacts -- the D-0004 contract. Before Wave 5 contacts were
//      create-only; "Manage" opened the create wizard. A manage list that
//      renders but whose Delete does nothing is the exact shape of the bug
//      this suite has to catch.
//
// REQUEST CAPTURE (D-0021). Every capture below lives in the STUB HANDLER,
// never on `page.on('request')`. Renderer backend traffic goes through the
// main-process proxy over IPC, so the page never issues the HTTP request and
// a page-level listener counts zero forever -- which would pass every
// "performed no calls" assertion vacuously and fail every "performed exactly
// one" assertion even against a perfectly behaved app. The stub is the one
// place a real backend call lands. Arrays are module-scoped and reset in each
// scenario's navigate(); backendState() is rebuilt per run, so the handler
// closures always point at the fresh arrays.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

const CONTACTS = [
  { id: 'a1', name: 'Priya', relationship: 'my manager', tone_guidance: 'Direct, no filler.', notes: '', preferred_persona: 'Formal' },
  { id: 'b2', name: 'Sam', relationship: 'my brother', tone_guidance: 'Warm.', notes: '', preferred_persona: null },
];

const PERSONAS = {
  'True Janitor': { prompt: 'Clean it up.', temperature: 0.1 },
  Formal: { prompt: 'Be formal.', temperature: 0.2 },
};

// --- captures ----------------------------------------------------------------

let personaWrites = [];
let contactWrites = [];
let contactDeletes = [];
let activeContactWrites = [];
let profilePatches = [];
let deletedContactIds = new Set();

function withContacts(extra = {}) {
  return () => ({
    ...(deletedContactIds = new Set(), {}),
    ...readyProfile(),
    // The Active badge and Talk's persona display read settings.current_preset.
    'GET /settings/profiles': {
      ...readyProfile()['GET /settings/profiles'],
      settings: {
        ...readyProfile()['GET /settings/profiles'].settings,
        current_preset: 'True Janitor',
      },
    },
    'GET /personas': PERSONAS,
    'GET /personas/True%20Janitor': { name: 'True Janitor', ...PERSONAS['True Janitor'] },
    'GET /personas/Formal': { name: 'Formal', ...PERSONAS.Formal },
    'GET /personas-builtins': { builtins: ['True Janitor'] },
    'GET /contacts': () => ({ ok: true, contacts: CONTACTS.filter((c) => !deletedContactIds.has(c.id)) }),
    'GET /contacts/active': { ok: true, contact_id: '' },
    'POST /contacts/active': (_req, { body }) => {
      activeContactWrites.push(body);
      return { ok: true };
    },
    'POST /contacts': (_req, { body }) => {
      contactWrites.push({ method: 'POST', body });
      return { ok: true, contact: { id: 'new1', ...body } };
    },
    'POST /contacts/a1': (_req, { body }) => {
      contactWrites.push({ method: 'PATCH', id: 'a1', body });
      return { ok: true, contact: { id: 'a1', ...body } };
    },
    'DELETE /contacts/a1': () => {
      contactDeletes.push('a1');
      deletedContactIds.add('a1');
      return { ok: true };
    },
    ...extra,
  });
}

async function openStudio(page) {
  await page.click('.sd-nav__button[data-nav="studio"]');
  await expect(page.locator('#workspace-studio')).toBeVisible();
}

async function openSettingsSection(page, section) {
  await page.click('.sd-nav__button[data-nav="settings"]');
  await expect(page.locator('#workspace-settings')).toBeVisible();
  await page.click(`#sdSetNav${section}`);
}

export const wave5StudioScenarios = [
  // --- 1. persona guided flow ------------------------------------------------
  {
    area: 'wave5-persona-flow',
    ui: 'signal-desk-prod',
    name: 'edit-opens-the-same-shell-at-review',
    kind: 'standard',
    description:
      'Studio\'s Edit opens the SAME guided-flow dialog that "+ New Persona" opens -- same #foundryOverlay, same '
      + 'wizard footer -- but at "Review & save" with the selected persona loaded, rather than at "Goal & role". '
      + 'Before Wave 5 this handler reached across the ambient document for #wizardPersonaName and fired a '
      + 'synthetic change event at it, editing a form in whichever page happened to be loaded. The assertion that '
      + 'matters is that the dialog is the same element in the same document at a different step: a separate '
      + 'editor would look almost identical and would be a second save path.',
    backendState: withContacts(),
    async navigate(page) {
      personaWrites = [];
      await openStudio(page);
      await page.click('.sd-persona-card[data-persona-name="Formal"]');
      await page.click('#sdPersonaEditButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
    },
    async expects(page) {
      await expect(
        page.locator('#foundryOverlay [data-flow-title]'),
        'Edit lands on Review & save, not on step 1',
      ).toHaveText('Review & save');

      // The wizard path, therefore the wizard footer -- the same one New
      // Persona gets. A Foundry-path dialog hides this.
      await expect(page.locator('#sdPersonaFlowFooter')).toBeVisible();
      await expect(page.locator('#wizardNextButton')).toHaveText('Save Persona');

      // The persona is actually LOADED, not just named. Its saved prompt must
      // be shown rather than a freshly regenerated one -- regenerating here
      // would silently discard a hand-tuned prompt the moment someone clicked
      // Edit.
      await expect(page.locator('#wizardPersonaName')).toHaveValue('Formal');
      await expect(page.locator('#wizardPromptPreview')).toHaveValue('Be formal.');

      // Opening an editor must not itself write anything.
      expect(personaWrites.length, 'opening Edit must perform ZERO persona writes').toBe(0);
    },
    screenshots: [{ name: 'edit-opens-the-same-shell-at-review' }],
  },
  {
    area: 'wave5-persona-flow',
    ui: 'signal-desk-prod',
    name: 'new-persona-and-edit-share-one-dialog',
    kind: 'standard',
    description:
      'The two entry points resolve to one dialog element. Opening New Persona, closing it, then opening Edit '
      + 'must reuse #foundryOverlay rather than mounting a second dialog -- two overlays with the same ids in one '
      + 'document is how a click lands on the hidden one. Also asserts the step differs, so "same dialog" is not '
      + 'achieved by making Edit behave identically to New.',
    backendState: withContacts(),
    async navigate(page) {
      await openStudio(page);
    },
    async expects(page) {
      await page.click('#sdNewPersonaButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
      await expect(page.locator('#foundryOverlay [data-flow-title]')).toHaveText('Goal & role');
      expect(await page.locator('#foundryOverlay').count(), 'exactly one dialog element').toBe(1);
      await page.click('#foundryCloseButton');

      await page.click('.sd-persona-card[data-persona-name="Formal"]');
      await page.click('#sdPersonaEditButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
      await expect(page.locator('#foundryOverlay [data-flow-title]')).toHaveText('Review & save');
      expect(await page.locator('#foundryOverlay').count(), 'still exactly one dialog element').toBe(1);
    },
    screenshots: [{ name: 'new-persona-and-edit-share-one-dialog' }],
  },
  {
    area: 'wave5-persona-flow',
    ui: 'signal-desk-prod',
    name: 'active-badge-reads-current-preset',
    kind: 'standard',
    description:
      'The "Active" badge names the profile\'s current_preset, not whichever persona the cursor is on. With '
      + 'current_preset = "True Janitor", selecting "Formal" must leave the badge hidden. This defaulted to '
      + '"always active when selected", so clicking through a grid of personas lit "Active" on each in turn while '
      + 'only one of them was the persona the app would actually use.',
    backendState: withContacts(),
    async navigate(page) {
      await openStudio(page);
    },
    async expects(page) {
      await page.click('.sd-persona-card[data-persona-name="True Janitor"]');
      await expect(page.locator('#sdCtxPersonaBadge'), 'the active persona is badged').toBeVisible();

      await page.click('.sd-persona-card[data-persona-name="Formal"]');
      await expect(
        page.locator('#sdCtxPersonaBadge'),
        'selecting a persona must not make it the active one',
      ).toBeHidden();
    },
    screenshots: [{ name: 'active-badge-reads-current-preset' }],
  },
  {
    area: 'wave5-persona-flow',
    ui: 'signal-desk-prod',
    name: 'cut-fields-are-absent-not-blank',
    kind: 'standard',
    description:
      'Persona tags and "Last updated" are GONE from the Studio context panel, not rendered as an em dash or an '
      + 'empty chip row. No persona schema field backs either one. A permanently blank field still tells the user '
      + 'a value is coming, so the release rule is absence, and this asserts absence rather than emptiness -- '
      + 'those two states are indistinguishable in a screenshot and completely different promises.',
    backendState: withContacts(),
    async navigate(page) {
      await openStudio(page);
      await page.click('.sd-persona-card[data-persona-name="Formal"]');
    },
    async expects(page) {
      expect(await page.locator('#sdCtxTags').count(), 'the tags row must not exist').toBe(0);
      expect(await page.locator('#sdCtxAddTagButton').count(), 'the add-tag button must not exist').toBe(0);
      expect(await page.locator('#sdCtxLastUpdated').count(), 'the last-updated field must not exist').toBe(0);

      // And the labels are gone too, not just the value elements.
      await expect(page.locator('#workspace-studio')).not.toContainText('Last Updated');
      // Paired Voice is REAL (persona.voice.base) and must survive the cut.
      await expect(page.locator('#sdCtxPairedVoiceName')).toBeVisible();
    },
    screenshots: [{ name: 'cut-fields-are-absent-not-blank' }],
  },
  {
    area: 'wave5-persona-flow',
    ui: 'signal-desk-prod',
    name: 'traits-disclose-experimental-unavailable',
    kind: 'standard',
    description:
      'D-0006. The five trait sliders remain editable and are still saved with the persona, but the panel states '
      + 'plainly that they are Experimental -- unavailable, and why: preservation qualification has not passed. '
      + 'Critically there is NO control that could enable them -- no checkbox, no switch, no "try it anyway". A '
      + 'saved slider that silently does nothing is the failure this disclosure exists to prevent, and a slider '
      + 'with an enabling switch beside it would be a worse one.',
    backendState: withContacts(),
    async navigate(page) {
      await openStudio(page);
      await page.click('#sdNewPersonaButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
    },
    async expects(page) {
      await expect(page.locator('#sdStudioTraitsStatusLabel'))
        .toHaveText('Persona traits: Experimental — unavailable');
      await expect(page.locator('#sdStudioTraitsStatusReason'))
        .toContainText('Preservation qualification has not passed');
      await expect(page.locator('#sdStudioTraitsStatusDetail')).not.toBeEmpty();

      // No enabling control anywhere in the traits area.
      const traitsArea = page.locator('#sdStudioTraitsStatus');
      expect(
        await traitsArea.locator('input[type="checkbox"], button[role="switch"]').count(),
        'D-0006 forbids any control that could turn traits on',
      ).toBe(0);

      // The sliders still work -- the data is preserved, only the effect is gated.
      await expect(page.locator('#wizardTraitWarmth')).toBeEnabled();
    },
    screenshots: [{ name: 'traits-disclose-experimental-unavailable' }],
  },

  // --- 2. disclosed Settings toggles (D-0005) --------------------------------
  {
    area: 'wave5-disclosure',
    ui: 'signal-desk-prod',
    name: 'delivery-signals-discloses-all-six',
    kind: 'standard',
    description:
      'The "Use speech delivery signals" control discloses all six required pieces: the data it uses, what it may '
      + 'change, what it must preserve, its default, a link to inspect the associated data, and its '
      + 'preservation-gate status. Each is asserted by content rather than by presence -- an empty element under '
      + 'the right label discloses nothing. Ships OFF.',
    backendState: withContacts(),
    async navigate(page) {
      await openSettingsSection(page, 'AiCleanup');
    },
    async expects(page) {
      await expect(page.locator('#sdSetUseDeliverySignals')).not.toBeChecked();
      await expect(page.locator('#sdSetUseDeliverySignals'), 'delivery signals are the user\'s to enable').toBeEnabled();

      await expect(page.locator('#sdSetDeliverySignalsDataUsed')).toContainText('pace', { ignoreCase: true });
      await expect(page.locator('#sdSetDeliverySignalsMayChange')).toContainText('unctuation');
      await expect(page.locator('#sdSetDeliverySignalsMustPreserve')).toContainText('meaning');
      await expect(page.locator('#sdSetDeliverySignalsDefault')).toHaveText('Off');
      await expect(page.locator('#sdSetDeliverySignalsInspect')).toBeVisible();
      await expect(page.locator('#sdSetDeliverySignalsGate')).toContainText('PASS 3/3');
    },
    screenshots: [{ name: 'delivery-signals-discloses-all-six' }],
  },
  {
    area: 'wave5-disclosure',
    ui: 'signal-desk-prod',
    name: 'audience-context-is-disclosed-but-unswitchable',
    kind: 'standard',
    description:
      'D-0005. The audience control renders its full disclosure and its gate status, ships OFF, and CANNOT be '
      + 'switched on: enabling it is a release-gate decision that has not been made. Asserts the control is '
      + 'disabled, that clicking it changes nothing, and -- the assertion that actually matters -- that no '
      + 'profile write carrying use_audience_context reaches the backend. A disabled attribute is a promise; the '
      + 'absent key is the guarantee.',
    backendState: withContacts({
      'POST /settings/profiles/Default': (_req, { body }) => {
        profilePatches.push(body);
        return { ok: true };
      },
    }),
    async navigate(page) {
      profilePatches = [];
      await openSettingsSection(page, 'AiCleanup');
    },
    async expects(page) {
      const toggle = page.locator('#sdSetUseAudienceContext');
      await expect(toggle).not.toBeChecked();
      await expect(toggle, 'enabling audience context is a gate decision, not a user setting yet').toBeDisabled();

      await expect(page.locator('#sdSetAudienceContextDataUsed')).toContainText('contact');
      await expect(page.locator('#sdSetAudienceContextMustPreserve')).toContainText('meaning');
      await expect(page.locator('#sdSetAudienceContextDefault')).toHaveText('Off');
      await expect(page.locator('#sdSetAudienceContextGate')).toContainText('cannot be switched on yet');

      // Forcing it must not stick.
      await toggle.click({ force: true }).catch(() => {});
      await expect(toggle, 'a forced click must not enable it').not.toBeChecked();

      // And nothing Settings saves may ever carry the key.
      for (const patch of profilePatches) {
        expect(
          Object.prototype.hasOwnProperty.call(patch || {}, 'use_audience_context'),
          'no profile write may carry use_audience_context',
        ).toBe(false);
      }
    },
    screenshots: [{ name: 'audience-context-is-disclosed-but-unswitchable' }],
  },

  // --- 3. contacts (D-0004) --------------------------------------------------
  {
    area: 'wave5-contacts',
    ui: 'signal-desk-prod',
    name: 'manage-lists-contacts-with-edit-and-delete',
    kind: 'standard',
    description:
      'Manage opens a list of the contacts that exist, each with Edit and Delete. Before Wave 5, Manage opened '
      + 'the CREATE wizard, so the only thing a user could do to an existing contact was make another one -- the '
      + 'create-only state D-0004 forbids shipping. Asserts real names from the backend list rather than any '
      + 'placeholder row.',
    backendState: withContacts(),
    async navigate(page) {
      await page.click('#sdContactManageButton');
    },
    async expects(page) {
      const rows = page.locator('#sdContactManageList .sd-contact-row');
      await expect(rows).toHaveCount(2);
      await expect(rows.nth(0)).toContainText('Priya');
      await expect(rows.nth(1)).toContainText('Sam');
      await expect(rows.nth(0).locator('.sd-contact-row__edit')).toBeVisible();
      await expect(rows.nth(0).locator('.sd-contact-row__delete')).toBeVisible();
      await expect(page.locator('#sdContactManageEmpty')).toBeHidden();
    },
    screenshots: [{ name: 'manage-lists-contacts-with-edit-and-delete' }],
  },
  {
    area: 'wave5-contacts',
    ui: 'signal-desk-prod',
    name: 'editing-a-contact-patches-it-rather-than-duplicating',
    kind: 'standard',
    description:
      'Editing an existing contact sends exactly one write, and that write is an update to a1 -- not a create. '
      + 'This is the failure a screenshot cannot show: an "edit" dialog that posts a new contact looks like a '
      + 'successful save and silently duplicates the person. The capture lives in the stub because renderer '
      + 'traffic goes through the IPC proxy (D-0021).',
    backendState: withContacts(),
    async navigate(page) {
      contactWrites = [];
      await page.click('#sdContactManageButton');
      await page.click('#sdContactManageList .sd-contact-row:has-text("Priya") .sd-contact-row__edit');
      await expect(page.locator('#sdContactFlow')).toBeVisible();
    },
    async expects(page) {
      // Opened at review, loaded, and not re-interviewing.
      await expect(page.locator('#sdContactFlow [data-flow-title]')).toHaveText('Review & save');
      await expect(page.locator('#sdContactName')).toHaveValue('Priya');
      await expect(page.locator('#sdContactRelationship')).toHaveValue('my manager');

      await page.fill('#sdContactTone', 'Warmer than before.');
      await page.click('#sdContactSave');

      await expect.poll(() => contactWrites.length, {
        message: 'saving an edit should perform exactly one contact write',
      }).toBe(1);
      expect(contactWrites[0].method, 'an edit must PATCH, not POST a new contact').toBe('PATCH');
      expect(contactWrites[0].id).toBe('a1');
      expect(contactWrites[0].body.tone_guidance).toBe('Warmer than before.');
    },
    screenshots: [{ name: 'editing-a-contact-patches-it-rather-than-duplicating' }],
  },
  {
    area: 'wave5-contacts',
    ui: 'signal-desk-prod',
    name: 'deleting-a-contact-reaches-the-backend',
    kind: 'standard',
    description:
      'Delete asks for confirmation and then actually issues DELETE /contacts/a1. A manage list whose Delete '
      + 'removes the row locally without telling the backend is the exact bug that looks perfect in a screenshot '
      + 'and loses the deletion on the next refresh -- so the stub-side capture, not the disappearing row, is the '
      + 'assertion.',
    backendState: withContacts(),
    async navigate(page) {
      contactDeletes = [];
      page.on('dialog', (dialog) => dialog.accept());
      await page.click('#sdContactManageButton');
    },
    async expects(page) {
      await page.click('#sdContactManageList .sd-contact-row:has-text("Priya") .sd-contact-row__delete');

      await expect.poll(() => contactDeletes.length, {
        message: 'Delete must issue a real DELETE /contacts/a1',
      }).toBe(1);
      await expect(page.locator('#sdContactManageList .sd-contact-row')).toHaveCount(1);
      await expect(page.locator('#sdContactManageList')).not.toContainText('Priya');
    },
    screenshots: [{ name: 'deleting-a-contact-reaches-the-backend' }],
  },
  {
    area: 'wave5-contacts',
    ui: 'signal-desk-prod',
    name: 'applying-a-contact-shows-it-in-the-status-bar',
    kind: 'standard',
    description:
      'Applying a contact fills the status-bar contact cell and persists the sticky selection. With nothing '
      + 'applied the cell is ABSENT rather than reading an em dash: "no one in particular" is the default and a '
      + 'real choice, and a permanent rail cell reading "—" beside it would turn that default into a gap the user '
      + 'feels invited to fill.',
    backendState: withContacts(),
    async navigate(page) {
      activeContactWrites = [];
    },
    async expects(page) {
      await expect(
        page.locator('#sdStatusContactCell'),
        'with nothing applied the cell is absent, not an em dash',
      ).toBeHidden();

      await page.selectOption('#sdContactPicker', 'b2');

      await expect(page.locator('#sdStatusContactCell')).toBeVisible();
      await expect(page.locator('#sdStatusContactValue')).toHaveText('Sam');
      await expect.poll(() => activeContactWrites.length, {
        message: 'a sticky selection must be persisted, not just painted',
      }).toBe(1);
      expect(activeContactWrites[0].contact_id).toBe('b2');
    },
    screenshots: [{ name: 'applying-a-contact-shows-it-in-the-status-bar' }],
  },
  {
    area: 'wave5-contacts',
    ui: 'signal-desk-prod',
    name: 'clearing-the-applied-contact-persists',
    kind: 'standard',
    description:
      'Clearing an applied contact hides the status-bar cell AND persists the empty selection. A sticky selection '
      + 'that un-sticks only in the UI would come back on the next launch, which is worse than not being sticky: '
      + 'the user believes they have stopped recording an audience on their drafts and has not.',
    backendState: withContacts(),
    async navigate(page) {
      activeContactWrites = [];
      await page.selectOption('#sdContactPicker', 'b2');
      await expect(page.locator('#sdStatusContactCell')).toBeVisible();
    },
    async expects(page) {
      await page.click('#sdContactClearButton');

      await expect(page.locator('#sdStatusContactCell')).toBeHidden();
      await expect(page.locator('#sdContactPicker')).toHaveValue('');
      await expect.poll(() => activeContactWrites.map((w) => w.contact_id), {
        message: 'the cleared selection must be written through',
      }).toContain('');
    },
    screenshots: [{ name: 'clearing-the-applied-contact-persists' }],
  },
  {
    area: 'wave5-contacts',
    ui: 'signal-desk-prod',
    name: 'applying-a-contact-does-not-claim-to-change-cleanup',
    kind: 'standard',
    description:
      'With use_audience_context off -- which is how it ships -- applying a contact must NOT suggest the cleanup '
      + 'model has been told who you are writing to. The selection is still recorded on drafts (that is what lets '
      + 'Library filter by contact), and the UI says exactly that. This is the seam where a user could reasonably '
      + 'conclude the feature is live when D-0005 keeps it off.',
    backendState: withContacts(),
    async navigate(page) {
      await page.selectOption('#sdContactPicker', 'a1');
    },
    async expects(page) {
      const note = page.locator('#sdContactPickerNote');
      await expect(note).toBeVisible();
      await expect(note).not.toContainText('cleanup will be told');
    },
    screenshots: [{ name: 'applying-a-contact-does-not-claim-to-change-cleanup' }],
  },
];
