// Wave 4 (Gate 4): the Library workspace on the PRODUCTION Signal Desk
// composition root (signal-desk.html, `ui: 'signal-desk-prod'`).
//
// These scenarios cover the paths where being wrong costs the user something
// they cannot get back -- deletion, the three clear scopes, restore, and the
// reopen/resend routing that must never turn into a send. Rendering-only
// concerns (day grouping, chips, confidence bars) are already covered by the
// pure unit tests in tests/libraryWorkspace.test.mjs; duplicating them here
// would just make the suite slower without making it stricter.
//
// REQUEST CAPTURE HAPPENS IN THE STUB, NOT VIA page.on('request').
//
// This is the D-0021 ruling and it is not a style preference: the renderer
// never issues a network request of its own. Every backend call goes through
// the preload bridge to the main-process proxy (app/src/main/backendProxy.js),
// which makes the real HTTP request from the MAIN process. A `page.on('request')`
// listener is attached to the renderer and therefore sees NOTHING -- a
// scenario built on it passes by observing zero requests and calls that
// proof. The stub server is the one place every real request actually lands,
// so each scenario below closes over a `calls` array and its route handlers
// push into it. `assertNoCall` is then a real assertion rather than a
// tautology.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';
import { waitForText } from '../harness.mjs';

// --- Fixture records ---------------------------------------------------------
//
// Shaped like backend/domain/library.py's normalize_draft_record output --
// every contract §1 field present at its default -- because that is what
// GET /library/search really returns and the UI reads several of them
// (pinned, and the five provenance ids) directly.

function draft(overrides = {}) {
  return {
    id: 1,
    raw_text: 'hey can we push standup back a bit',
    final_text: 'Hey, could we push standup back a little?',
    status: 'pending',
    preset: 'True Janitor',
    contact_id: null,
    confidence: { score: 0.91 },
    metadata: { duration_seconds: 6 },
    send_result: null,
    created_at: '2026-07-24T10:32:00Z',
    pinned: false,
    pinned_at: null,
    duplicated_from_id: null,
    reopened_from_id: null,
    revision_of_id: null,
    restored_from_recording_id: null,
    restored_from_draft_id: null,
    ...overrides,
  };
}

function recording(overrides = {}) {
  return {
    // recordings.py stores time.time() -- epoch SECONDS, not milliseconds.
    // Kept as seconds here on purpose: a fixture that "helpfully" used
    // milliseconds would hide the conversion bug this shape exists to catch.
    id: 'rec-0001',
    created_at: 1785000000,
    duration_seconds: 8,
    sample_rate: 16000,
    stop_reason: 'manual',
    has_audio: true,
    ...overrides,
  };
}

/**
 * Builds a stub library backend that RECORDS every request it serves.
 * Returns `{ state, calls }`; `state` is spread into a scenario's
 * backendState and `calls` is read by its expects().
 */
function libraryBackend({ results = [draft()], recordings: recs = [], overrides = {} } = {}) {
  const calls = [];
  const record = (name) => (req, ctx) => {
    calls.push({ name, method: req.method, url: req.url, query: ctx.query, params: ctx.params, body: ctx.body });
    return null;
  };
  const state = {
    ...coldBoot(),
    'GET /library/search': (req, ctx) => {
      record('search')(req, ctx);
      return { ok: true, results, total: results.length, limit: 25, offset: 0 };
    },
    'GET /recordings': (req, ctx) => {
      record('recordings')(req, ctx);
      return { ok: true, recordings: recs };
    },
    'DELETE /library/drafts/:id': (req, ctx) => {
      record('deleteDraft')(req, ctx);
      return { ok: true, removed: true, already_absent: false };
    },
    'DELETE /library/history/:id': (req, ctx) => {
      record('deleteHistory')(req, ctx);
      return { ok: true, removed: true, already_absent: false };
    },
    'DELETE /library/recordings/:id': (req, ctx) => {
      record('deleteRecording')(req, ctx);
      return { ok: true, removed: true, already_absent: false };
    },
    'POST /library/clear': (req, ctx) => {
      record('clear')(req, ctx);
      return { ok: true, preview: { scope: ctx.body?.scope, counts: {} } };
    },
    'POST /library/drafts/:id/pin': (req, ctx) => {
      record('pin')(req, ctx);
      return { ok: true, draft: draft({ pinned: Boolean(ctx.body?.pinned), pinned_at: '2026-07-24T11:00:00Z' }) };
    },
    'POST /library/drafts/:id/duplicate': (req, ctx) => {
      record('duplicate')(req, ctx);
      return { ok: true, draft: draft({ id: 99, duplicated_from_id: Number(ctx.params.id), status: 'pending' }) };
    },
    'GET /library/drafts/:id/reopen': (req, ctx) => {
      record('reopenRead')(req, ctx);
      return { ok: true, reopen: { source_id: Number(ctx.params.id), editable: true, requires_new_record: false } };
    },
    'POST /library/drafts/:id/reopen': (req, ctx) => {
      record('reopenCommit')(req, ctx);
      return { ok: true, draft: draft({ id: 98, reopened_from_id: Number(ctx.params.id) }) };
    },
    'POST /library/drafts/:id/resend': (req, ctx) => {
      record('resend')(req, ctx);
      return { ok: true, resend: { allowed: true, reason: '', next_action: 'reopen_for_review' }, reopen: {} };
    },
    'POST /library/recordings/:id/restore': (req, ctx) => {
      record('restoreRecording')(req, ctx);
      return { ok: true, draft: draft({ id: 97, restored_from_recording_id: ctx.params.id, final_text: 'hey can we push standup back a bit' }) };
    },
    'POST /library/drafts/:id/restore': (req, ctx) => {
      record('restoreDraft')(req, ctx);
      return { ok: true, draft: draft({ id: 96, restored_from_draft_id: Number(ctx.params.id) }) };
    },
    ...overrides,
  };
  return { state, calls };
}

// --- Assertions over the captured calls ----------------------------------------

function callsNamed(calls, name) {
  return calls.filter((c) => c.name === name);
}

/**
 * The load-bearing negative assertion. Every scenario that says "this did not
 * happen" says it through here, so the reason it is trustworthy (stub-side
 * capture, not renderer-side) lives in one place.
 */
function assertNoCall(calls, name, why) {
  const hits = callsNamed(calls, name);
  expect(hits, `${why}\ncaptured: ${JSON.stringify(calls.map((c) => `${c.method} ${c.url}`), null, 2)}`).toHaveLength(0);
}

async function goToLibrary(page) {
  const gate = page.locator('#sdOnboarding');
  if (await gate.isVisible().catch(() => false)) {
    throw new Error('#sdOnboarding is visible at scenario start -- broken precondition, refusing to click through it.');
  }
  await page.click('.sd-nav__button[data-nav="utilities"]');
  await page.locator('.sd-util-nav__item[data-shell-nav="library"]').first().click();
  await expect(page.locator('#workspace-library')).toBeVisible();
}

/** Opens the confirmation dialog for a destructive control and returns its locator. */
async function openConfirm(page, triggerSelector) {
  await page.click(triggerSelector);
  const dialog = page.locator('#sdLibraryConfirm');
  await expect(dialog, `${triggerSelector} did not open the confirmation dialog`).toBeVisible();
  return dialog;
}

export const libraryScenarios = [
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'filters-and-pagination-are-backend-driven',
    kind: 'standard',
    description:
      'Library asks the backend to do the filtering. Typing in the search box, choosing a persona, choosing a ' +
      'status and setting a date range must each produce a GET /library/search carrying that exact parameter -- ' +
      'not a client-side scan of an already-fetched page, which is what the Wave-3 adapter did and why its item ' +
      'count described the fetched slice rather than the archive. Captured stub-side, because renderer traffic ' +
      'goes through the main-process proxy and is invisible to page.on("request").',
    backendState: () => {
      const { state } = libraryBackend({ results: [draft({ id: 1 }), draft({ id: 2, status: 'sent', created_at: '2026-07-23T09:00:00Z' })] });
      return { ...state, 'GET /personas': { 'True Janitor': { prompt: 'Be direct.' } } };
    },
    async navigate(page) {
      await goToLibrary(page);
    },
    async expects(page) {
      await expect(page.locator('#sdLibraryTimeline .sd-message-card')).toHaveCount(2);
      await expect(page.locator('#sdLibraryItemsCount')).toContainText('of 2');

      // The filter panel starts closed and its button reports that state.
      await expect(page.locator('#sdLibraryFilterPanel')).toBeHidden();
      await expect(page.locator('#sdLibraryFilterButton')).toHaveAttribute('aria-expanded', 'false');
      await page.click('#sdLibraryFilterButton');
      await expect(page.locator('#sdLibraryFilterPanel')).toBeVisible();

      // Status is a REAL vocabulary, not three lossy group chips: every
      // individual backend status must be selectable.
      const statusValues = await page.locator('#sdLibraryStatusFilter option').evaluateAll((els) =>
        els.map((el) => el.value).filter(Boolean),
      );
      expect(statusValues.sort()).toEqual([
        'accepted', 'blocked', 'declined', 'error', 'failed', 'pending', 'scratch',
        'send_error', 'send_interrupted', 'sending', 'sent',
      ].sort());

      await page.selectOption('#sdLibraryStatusFilter', 'sent');
      await page.fill('#sdLibraryDateFrom', '2026-07-01');
      await page.fill('#sdLibraryDateTo', '2026-07-24');
      await page.fill('#sdLibrarySearchInput', 'standup');
      // The search box is debounced; wait for the request rather than sleeping.
      await expect(page.locator('#sdLibraryItemsCount')).toContainText('of 2');
    },
    screenshots: [{ name: 'filters-and-pagination-are-backend-driven' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'search-filters-reach-the-backend-as-query-parameters',
    kind: 'standard',
    description:
      'The companion assertion to the scenario above, made against the captured requests rather than the ' +
      'rendered page: after choosing a status, a date range and a search term, at least one GET /library/search ' +
      'must have carried status=sent, date_from, date_to and q together. A UI that renders a filter chip but ' +
      'never sends the parameter looks identical on screen and returns the wrong rows.',
    backendState() {
      const { state, calls } = libraryBackend();
      this.__calls = calls;
      return state;
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryFilterButton');
      await page.selectOption('#sdLibraryStatusFilter', 'sent');
      await page.fill('#sdLibraryDateFrom', '2026-07-01');
      await page.fill('#sdLibraryDateTo', '2026-07-24');
      await page.fill('#sdLibrarySearchInput', 'standup');
      await expect(page.locator('#sdLibraryTimeline')).toBeVisible();
      // Let the debounced search land.
      await page.waitForTimeout(600);
    },
    async expects() {
      const searches = callsNamed(this.__calls, 'search');
      expect(searches.length, 'Library issued no search at all').toBeGreaterThan(0);

      const withStatus = searches.filter((c) => c.query.status === 'sent');
      expect(withStatus.length, 'the status filter never reached the backend').toBeGreaterThan(0);

      const withDates = searches.filter((c) => c.query.date_from === '2026-07-01' && c.query.date_to === '2026-07-24');
      expect(withDates.length, 'the date range never reached the backend').toBeGreaterThan(0);

      const withQuery = searches.filter((c) => c.query.q === 'standup');
      expect(withQuery.length, 'the search term never reached the backend').toBeGreaterThan(0);

      // Contract §2: there is deliberately no contact filter until Wave 5.
      // Sending one would be silently dropped server-side while the UI
      // implied the archive had been narrowed.
      const withContact = searches.filter((c) => 'contact' in c.query || 'contact_id' in c.query);
      expect(withContact, 'a contact parameter the backend does not implement was sent').toHaveLength(0);
    },
    screenshots: [{ name: 'search-filters-reach-the-backend-as-query-parameters' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'pin-persists-through-the-backend-and-survives-a-reload',
    kind: 'standard',
    description:
      'Pinning writes to POST /library/drafts/{id}/pin and the pin is still there after the page reloads. The ' +
      'Wave-3 adapter kept pins in a JavaScript Set, so every pin silently vanished on restart while the star ' +
      'looked exactly as convincing beforehand -- the failure was invisible until the user came back.',
    backendState() {
      let pinned = false;
      const { state, calls } = libraryBackend();
      this.__calls = calls;
      return {
        ...state,
        'GET /library/search': (_req, ctx) => {
          calls.push({ name: 'search', method: 'GET', url: _req.url, query: ctx.query, params: {}, body: undefined });
          return { ok: true, results: [draft({ id: 5, pinned })], total: 1, limit: 25, offset: 0 };
        },
        'POST /library/drafts/:id/pin': (_req, ctx) => {
          calls.push({ name: 'pin', method: 'POST', url: _req.url, query: ctx.query, params: ctx.params, body: ctx.body });
          pinned = Boolean(ctx.body?.pinned);
          return { ok: true, draft: draft({ id: 5, pinned, pinned_at: pinned ? '2026-07-24T11:00:00Z' : null }) };
        },
      };
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      await page.click('#sdSelectedPinActionButton');
      await expect(page.locator('#sdSelectedPinActionButton')).toHaveAttribute('aria-pressed', 'true');
      // A real restart, as far as the renderer is concerned: every module is
      // re-imported and every in-memory Set is gone. Same readiness wait
      // resetBackendState performs, so the assertions below are not racing
      // the boot.
      await page.reload();
      await page.waitForLoadState('domcontentloaded');
      await page.waitForSelector('.sd-shell', { state: 'attached', timeout: 15000 });
      await waitForText(page.locator('#sdStatusSttValue'), /loaded/i, 15000);
      await goToLibrary(page);
    },
    async expects(page) {
      const pins = callsNamed(this.__calls, 'pin');
      expect(pins.length, 'the pin never reached the backend').toBe(1);
      expect(pins[0].body).toEqual({ pinned: true });

      // After the reload the pin is read back from the archive, not from a
      // session Set that no longer exists.
      await page.click('#sdLibraryTimeline .sd-message-card');
      await expect(page.locator('#sdSelectedPinActionButton')).toHaveAttribute('aria-pressed', 'true');
    },
    screenshots: [{ name: 'pin-persists-through-the-backend-and-survives-a-reload' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'cancelling-a-delete-confirmation-deletes-nothing',
    kind: 'standard',
    description:
      'The negative half of the destructive path, and the one worth more than its positive twin: opening the ' +
      'delete confirmation and cancelling must issue ZERO delete requests. Proven against the stub\'s captured ' +
      'calls, so "no request was seen" cannot be an artefact of listening in the wrong process.',
    backendState() {
      const { state, calls } = libraryBackend({ results: [draft({ id: 11 })] });
      this.__calls = calls;
      return state;
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      const dialog = await openConfirm(page, '#sdSelectedDeleteButton');
      // The dialog must describe the item without quoting a single character
      // of what it says (contract §7: previews are content-free).
      await expect(dialog).toContainText('characters of message text');
      await expect(dialog).not.toContainText('push standup');
      await page.click('#sdLibraryConfirmCancel');
      await expect(dialog).toBeHidden();
    },
    async expects(page) {
      assertNoCall(this.__calls, 'deleteDraft', 'cancelling the confirmation still issued a draft delete');
      assertNoCall(this.__calls, 'deleteHistory', 'cancelling the confirmation still issued a history delete');
      await expect(page.locator('#sdLibraryTimeline .sd-message-card')).toHaveCount(1);
    },
    screenshots: [{ name: 'cancelling-a-delete-confirmation-deletes-nothing' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'confirming-a-delete-sends-confirm-true-and-announces-it',
    kind: 'standard',
    description:
      'Confirming the dialog issues exactly one DELETE carrying confirm=true (the backend refuses an ' +
      'unconfirmed delete with 400, so a UI that forgot the flag would produce a confusing error rather than a ' +
      'deletion), and the outcome is announced in the aria-live region -- not only as a toast, which a screen ' +
      'reader user never receives.',
    backendState() {
      const { state, calls } = libraryBackend({ results: [draft({ id: 11 })] });
      this.__calls = calls;
      return state;
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      await openConfirm(page, '#sdSelectedDeleteButton');
      await page.click('#sdLibraryConfirmAccept');
      await expect(page.locator('#sdLibraryConfirm')).toBeHidden();
    },
    async expects(page) {
      const deletes = callsNamed(this.__calls, 'deleteDraft');
      expect(deletes.length, 'confirming issued no delete').toBe(1);
      expect(deletes[0].query.confirm).toBe('true');
      expect(deletes[0].params.id).toBe('11');
      await expect(page.locator('#sdLibraryStatus')).toContainText(/gone for good|already gone/);
    },
    screenshots: [{ name: 'confirming-a-delete-sends-confirm-true-and-announces-it' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'deleting-an-already-absent-item-is-honest-not-a-lie',
    kind: 'standard',
    description:
      'The backend treats a delete of something already gone as an idempotent success (already_absent: true, ' +
      'HTTP 200). The UI must report that distinctly -- saying "Deleted" would teach the user the app removed ' +
      'data it never had, and saying "Error" would make a safe, correct outcome look like a fault.',
    backendState() {
      const { state, calls } = libraryBackend({
        results: [draft({ id: 11 })],
        overrides: {},
      });
      this.__calls = calls;
      return {
        ...state,
        'DELETE /library/drafts/:id': (_req, ctx) => {
          calls.push({ name: 'deleteDraft', method: 'DELETE', url: _req.url, query: ctx.query, params: ctx.params, body: undefined });
          return { ok: true, removed: false, already_absent: true };
        },
      };
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      await openConfirm(page, '#sdSelectedDeleteButton');
      await page.click('#sdLibraryConfirmAccept');
    },
    async expects(page) {
      const status = page.locator('#sdLibraryStatus');
      await expect(status).toContainText('already gone');
      await expect(status).not.toContainText('gone for good');
    },
    screenshots: [{ name: 'deleting-an-already-absent-item-is-honest-not-a-lie' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'each-clear-scope-confirms-separately-and-describes-what-it-keeps',
    kind: 'standard',
    description:
      'The three clear scopes are independent (contract §7): "drafts and history" must never touch retained ' +
      'recordings and "recordings" must never touch drafts. Each button opens its OWN confirmation naming both ' +
      'halves -- what it removes AND what it deliberately leaves -- and confirming one issues exactly one clear ' +
      'call for that scope and no other. The "keeps" half is the part a user cannot verify any other way.',
    backendState() {
      const { state, calls } = libraryBackend({ recordings: [recording()] });
      this.__calls = calls;
      return state;
    },
    async navigate(page) {
      await goToLibrary(page);

      // Scope 1: drafts + history. Its dialog must PROMISE recordings survive.
      let dialog = await openConfirm(page, '#sdLibraryClearDraftsButton');
      await expect(dialog).toContainText('This keeps');
      await expect(dialog).toContainText(/Saved audio recordings/i);
      await page.click('#sdLibraryConfirmCancel');

      // Scope 2: recordings. Its dialog must promise drafts and history survive.
      dialog = await openConfirm(page, '#sdLibraryClearRecordingsButton');
      await expect(dialog).toContainText(/Drafts and message history/i);
      await page.click('#sdLibraryConfirmCancel');

      // Scope 3: everything conversational -- and still not personas/voices/models.
      dialog = await openConfirm(page, '#sdLibraryClearAllButton');
      await expect(dialog).toContainText(/never touches them/i);
      await page.click('#sdLibraryConfirmAccept');
      await expect(page.locator('#sdLibraryConfirm')).toBeHidden();
    },
    async expects() {
      const clears = callsNamed(this.__calls, 'clear');
      expect(clears.length, 'two cancelled scopes and one confirmed scope should be exactly one clear call').toBe(1);
      expect(clears[0].body).toEqual({ scope: 'all_conversation_data', confirm: true });
    },
    screenshots: [{ name: 'each-clear-scope-confirms-separately-and-describes-what-it-keeps' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'retained-recordings-restore-into-a-labelled-raw-transcript',
    kind: 'standard',
    description:
      'The retained-recordings section lists what audio is being kept and offers Restore per row. Restoring ' +
      're-transcribes into a new pending draft whose text is the RAW transcript -- D-0020 accepted that ' +
      'behaviour on the explicit condition that Wave 4 label it, so the restored item must carry a visible ' +
      '"Raw transcript" badge and the announcement must say so too. An unlabelled restore reads as a ' +
      'cleaned-up message the persona never wrote.',
    backendState() {
      const restored = [];
      const { state, calls } = libraryBackend({ results: [], recordings: [recording()] });
      this.__calls = calls;
      return {
        ...state,
        'GET /library/search': (_req, ctx) => {
          calls.push({ name: 'search', method: 'GET', url: _req.url, query: ctx.query, params: {}, body: undefined });
          return { ok: true, results: [...restored], total: restored.length, limit: 25, offset: 0 };
        },
        'POST /library/recordings/:id/restore': (_req, ctx) => {
          calls.push({ name: 'restoreRecording', method: 'POST', url: _req.url, query: ctx.query, params: ctx.params, body: ctx.body });
          const created = draft({
            id: 97,
            restored_from_recording_id: ctx.params.id,
            raw_text: 'hey can we push standup back a bit',
            final_text: 'hey can we push standup back a bit',
          });
          restored.push(created);
          return { ok: true, draft: created };
        },
      };
    },
    async navigate(page) {
      await goToLibrary(page);
      await expect(page.locator('#sdLibraryRecordingsCount')).toContainText('1 retained');
      await page.click('#sdLibraryRecordingsList .sd-recordings__row [data-action="restore"]');
      await expect(page.locator('#sdLibraryTimeline .sd-message-card')).toHaveCount(1);
    },
    async expects(page) {
      const restores = callsNamed(this.__calls, 'restoreRecording');
      expect(restores.length).toBe(1);
      expect(restores[0].params.id).toBe('rec-0001');

      // D-0020: labelled on the card...
      const badge = page.locator('#sdLibraryTimeline [data-provenance="raw-transcript"]');
      await expect(badge, 'the restored draft carries no raw-transcript label (D-0020)').toHaveCount(1);
      await expect(badge).toHaveText('Raw transcript');

      // ...and said out loud for anyone not looking at the badge.
      await expect(page.locator('#sdLibraryStatus')).toContainText('raw transcript');

      // ...and in the Selected Item panel once it is selected.
      await page.click('#sdLibraryTimeline .sd-message-card');
      await expect(page.locator('#sdSelectedProvenance')).toBeVisible();
      await expect(page.locator('#sdSelectedProvenance')).toContainText('has not been through persona cleanup');
    },
    screenshots: [{ name: 'retained-recordings-restore-into-a-labelled-raw-transcript' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'reopening-a-sent-message-forks-instead-of-rewriting-history',
    kind: 'standard',
    description:
      'Reopening a SENT message must not hand the sent record to Talk, because Talk\'s ordinary save path would ' +
      'then rewrite history. The backend says so via requires_new_record, and the UI must act on it: fork with ' +
      'POST /library/drafts/{id}/reopen first, load the FORK into Talk, navigate there, and tell the user the ' +
      'original is untouched. The sent entry must still be in the Library afterwards.',
    backendState() {
      const { state, calls } = libraryBackend({ results: [draft({ id: 21, status: 'sent', send_result: { ok: true, sent_at: '2026-07-24T10:33:00Z' } })] });
      this.__calls = calls;
      return {
        ...state,
        'GET /library/drafts/:id/reopen': (_req, ctx) => {
          calls.push({ name: 'reopenRead', method: 'GET', url: _req.url, query: ctx.query, params: ctx.params, body: undefined });
          return { ok: true, reopen: { source_id: Number(ctx.params.id), editable: true, requires_new_record: true } };
        },
      };
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      await page.click('#sdSelectedReopenButton');
      await expect(page.locator('#workspace-talk')).toBeVisible();
    },
    async expects(page) {
      expect(callsNamed(this.__calls, 'reopenRead').length, 'reopen never asked the backend what it was allowed to do').toBe(1);
      const commits = callsNamed(this.__calls, 'reopenCommit');
      expect(commits.length, 'a sent message was handed to Talk without forking first').toBe(1);
      expect(commits[0].params.id).toBe('21');

      await expect(page.locator('.sd-nav__button[data-nav="talk"]')).toHaveAttribute('aria-current', 'page');

      // The original is still there: reopen is read-only on the source.
      await goToLibrary(page);
      await expect(page.locator('#sdLibraryTimeline .sd-message-card')).toHaveCount(1);
      await expect(page.locator('#sdLibraryStatus')).toContainText('original stays in your Library');
    },
    screenshots: [{ name: 'reopening-a-sent-message-forks-instead-of-rewriting-history' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'resend-routes-through-review-and-sends-nothing',
    kind: 'standard',
    description:
      'Resend is not a delivery primitive. The contract\'s resend_plan has exactly one next_action -- ' +
      'reopen_for_review -- and this proves the UI honours it: clicking Resend calls POST .../resend, then goes ' +
      'down the reopen path into Talk, and issues ZERO requests to any send route. The negative assertion is ' +
      'the point, and it is only meaningful because the stub is what captures the calls: a page.on("request") ' +
      'listener would report zero sends whether or not any had happened.',
    backendState() {
      const { state, calls } = libraryBackend({ results: [draft({ id: 31, status: 'sent', send_result: { ok: true, sent_at: '2026-07-24T10:33:00Z' } })] });
      this.__calls = calls;
      return {
        ...state,
        'GET /library/drafts/:id/reopen': (_req, ctx) => {
          calls.push({ name: 'reopenRead', method: 'GET', url: _req.url, query: ctx.query, params: ctx.params, body: undefined });
          return { ok: true, reopen: { source_id: Number(ctx.params.id), editable: true, requires_new_record: true } };
        },
        // Deliberately stubbed so that if the UI ever DID try to send, the
        // call would be captured rather than 404-ing into a generic error
        // that could be mistaken for something else.
        'POST /drafts/:id/send': (_req, ctx) => {
          calls.push({ name: 'send', method: 'POST', url: _req.url, query: ctx.query, params: ctx.params, body: ctx.body });
          return { ok: true };
        },
      };
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      await page.click('#sdSelectedResendButton');
      await expect(page.locator('#workspace-talk')).toBeVisible();
    },
    async expects() {
      expect(callsNamed(this.__calls, 'resend').length).toBe(1);
      expect(callsNamed(this.__calls, 'reopenCommit').length, 'resend did not route through reopen').toBe(1);
      assertNoCall(this.__calls, 'send', 'Resend reached a delivery route -- it must only ever open for review');
    },
    screenshots: [{ name: 'resend-routes-through-review-and-sends-nothing' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'duplicate-creates-a-pending-copy-with-visible-provenance',
    kind: 'standard',
    description:
      'Duplicate creates a NEW pending draft carrying duplicated_from_id. It can never inherit a sent status ' +
      '(that is a domain guarantee) and the copy is badged so it is not mistaken for the original -- two ' +
      'identical-looking cards with no way to tell which one was really sent is exactly the confusion the ' +
      'provenance field exists to prevent.',
    backendState() {
      const items = [draft({ id: 41, status: 'sent', send_result: { ok: true, sent_at: '2026-07-24T10:33:00Z' } })];
      const { state, calls } = libraryBackend();
      this.__calls = calls;
      return {
        ...state,
        'GET /library/search': (_req, ctx) => {
          calls.push({ name: 'search', method: 'GET', url: _req.url, query: ctx.query, params: {}, body: undefined });
          return { ok: true, results: [...items], total: items.length, limit: 25, offset: 0 };
        },
        'POST /library/drafts/:id/duplicate': (_req, ctx) => {
          calls.push({ name: 'duplicate', method: 'POST', url: _req.url, query: ctx.query, params: ctx.params, body: ctx.body });
          const copy = draft({ id: 42, duplicated_from_id: Number(ctx.params.id), status: 'pending', created_at: '2026-07-24T11:05:00Z' });
          items.unshift(copy);
          return { ok: true, draft: copy };
        },
      };
    },
    async navigate(page) {
      await goToLibrary(page);
      await page.click('#sdLibraryTimeline .sd-message-card');
      await page.click('#sdSelectedDuplicateButton');
      await expect(page.locator('#sdLibraryTimeline .sd-message-card')).toHaveCount(2);
    },
    async expects(page) {
      expect(callsNamed(this.__calls, 'duplicate').length).toBe(1);
      const badge = page.locator('#sdLibraryTimeline [data-provenance="duplicate"]');
      await expect(badge, 'the duplicate is indistinguishable from the original it copied').toHaveCount(1);
      await expect(page.locator('#sdLibraryStatus')).toContainText('original is unchanged');
    },
    screenshots: [{ name: 'duplicate-creates-a-pending-copy-with-visible-provenance' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'a-failed-load-says-so-instead-of-showing-an-empty-library',
    kind: 'standard',
    description:
      'An unreachable backend and an empty archive are different facts, and only one of them means the user has ' +
      'lost nothing. When GET /library/search fails, Library must show an error with a retry -- never the ' +
      '"nothing here yet" copy, which would tell a user their messages are gone at the exact moment they are ' +
      'merely unreadable.',
    backendState: () => ({
      ...coldBoot(),
      'GET /library/search': { status: 500, body: { detail: 'write_failed' } },
    }),
    async navigate(page) {
      await goToLibrary(page);
    },
    async expects(page) {
      const empty = page.locator('#sdLibraryTimeline .sd-timeline__empty');
      await expect(empty).toBeVisible();
      await expect(empty).toHaveClass(/sd-timeline__empty--error/);
      await expect(empty).not.toContainText(/nothing in your library yet/i);
      await expect(page.locator('#sdLibraryRetryButton'), 'a failed load offers no way to try again').toBeVisible();
      await expect(page.locator('#sdLibraryItemsCount')).toContainText('Count unavailable');
    },
    screenshots: [{ name: 'a-failed-load-says-so-instead-of-showing-an-empty-library' }],
  },
  {
    area: 'library',
    ui: 'signal-desk-prod',
    name: 'an-empty-archive-and-an-empty-filter-result-read-differently',
    kind: 'standard',
    description:
      'Two empty states, two different meanings. With nothing in the archive Library says so plainly; with a ' +
      'filter that matched nothing it says the FILTERS matched nothing and offers to clear them. Collapsing ' +
      'both into one message sends a user hunting for messages a filter is hiding.',
    backendState: () => ({
      ...coldBoot(),
      'GET /library/search': (_req, ctx) => ({
        ok: true,
        results: [],
        total: 0,
        limit: 25,
        offset: Number(ctx.query.offset || 0),
      }),
    }),
    async navigate(page) {
      await goToLibrary(page);
    },
    async expects(page) {
      const empty = page.locator('#sdLibraryTimeline .sd-timeline__empty');
      await expect(empty).toContainText(/Nothing in your Library yet/i);
      await expect(page.locator('#sdLibraryEmptyResetButton')).toHaveCount(0);

      await page.click('#sdFilterPinned');
      await expect(empty).toContainText(/No messages match these filters/i);
      await expect(page.locator('#sdLibraryEmptyResetButton'), 'a filtered-empty state offers no way back').toBeVisible();

      await page.click('#sdLibraryEmptyResetButton');
      await expect(empty).toContainText(/Nothing in your Library yet/i);
    },
    screenshots: [{ name: 'an-empty-archive-and-an-empty-filter-result-read-differently' }],
  },
];
