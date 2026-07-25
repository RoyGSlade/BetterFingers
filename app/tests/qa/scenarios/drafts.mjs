// A1.12: QA coverage for the DRAFTS feature module extracted in Phase 1
// (app/src/renderer/features/drafts.js). Closes the Phase 1 gate gap logged in
// docs/BUILD_WEEK_LOG.md -- A1.3 moved every draft render path out of main.js
// and nothing under tests/qa/scenarios proved the composition root still wires
// it up. These scenarios drive the REAL Electron app against the stub backend
// and assert the user-visible text drafts.js produced, so a broken
// createDraftsFeature() wiring in main.js fails here loudly.
//
// Covered render paths (all in features/drafts.js):
//   renderDraft()          -> raw/final columns, status pill, confidence badge,
//                             token summary, recording-metadata line + tooltip
//   setDraftControlsEnabled() -> which action buttons are live for which status
//   renderDraftHistory()   -> the multi-entry history list, newest first,
//                             140-char detail truncation, click-to-reselect
//   handleHistorySearch()/renderHistoryResults() -> the FTS archive view and
//                             its restore-on-empty-query behaviour
//
// Determinism: every value asserted below comes from the stub's fixed payloads.
// Nothing here reads the clock, sleeps, or touches a real model/network.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

// Shapes copied from server.py: create_draft() + update_draft_review_fields()
// (token_count/token_limit/long_text), get_recording_metadata() (metadata.*)
// and transcriber._compute_confidence() (confidence.score/avg_logprob/
// no_speech_prob). Not guessed -- see the "coordinating stub shapes" section of
// docs/QA_VISUAL_WALKBOOK.md.
const PENDING_DRAFT = {
  id: 7,
  status: 'pending',
  raw_text: 'um so can we move the standup to like four thirty',
  final_text: 'Can we move the standup to 4:30?',
  confidence: { score: 0.42, avg_logprob: -0.867, no_speech_prob: 0.11 },
  token_count: 12,
  token_limit: 1200,
  long_text: false,
  metadata: {
    sample_rate: 16000,
    duration_seconds: 4.2,
    frame_count: 131,
    sample_count: 67200,
    max_amplitude: 0.421,
    rms_amplitude: 0.0123,
    stop_reason: 'silence',
  },
};

// Deliberately longer than renderDraftHistory()'s 140-char cutoff so the
// truncation branch is exercised rather than assumed.
const LONG_FINAL_TEXT =
  'Following up on the deploy window: we need the migration to land before the freeze, ' +
  'so please confirm the rollback plan and who is on call before Thursday afternoon.';

const SENT_DRAFT = {
  id: 6,
  status: 'sent',
  raw_text: 'following up on the deploy window',
  final_text: LONG_FINAL_TEXT,
  token_count: 27,
  token_limit: 1200,
  long_text: false,
};

const DECLINED_DRAFT = {
  id: 5,
  status: 'declined',
  raw_text: 'scratch that never mind',
  final_text: 'Scratch that, never mind.',
  token_count: 5,
  token_limit: 1200,
  long_text: false,
};

// GET /drafts returns oldest-first (server.py list_drafts() dumps draft_queue
// in order), and drafts.js renders the LAST element as the current draft while
// renderDraftHistory() displays the list reversed (newest first).
const HISTORY = [DECLINED_DRAFT, SENT_DRAFT, PENDING_DRAFT];

function baseState(overrides = {}) {
  return {
    ...coldBoot(),
    'GET /drafts': { drafts: [PENDING_DRAFT] },
    'GET /drafts/latest': { draft: PENDING_DRAFT },
    ...overrides,
  };
}

async function goToDashboard(page) {
  await page.click('#tabButtonDashboard');
  await expect(page.locator('#tabDashboard')).toBeVisible();
}

export const draftsScenarios = [
  {
    area: 'drafts',
    name: 'latest-draft-renders-with-confidence',
    kind: 'standard',
    description:
      'A single pending draft from the backend renders through features/drafts.js renderDraft(): the raw transcript ' +
      'and cleaned output columns carry the stubbed text verbatim, the status pill reads "pending", the confidence ' +
      'badge shows the transcriber score as "42% confident" tinted warning, the token summary reads "12 / 1200 ' +
      'tokens", and the recording-metadata line humanises duration + stop reason with the raw acoustic telemetry ' +
      'kept in the hover tooltip. No long-text warning is shown, because this draft is under its token limit.',
    backendState: () => baseState(),
    async navigate(page) {
      await goToDashboard(page);
    },
    async expects(page) {
      await expect(page.locator('#draftStatus')).toHaveText('pending');
      await expect(page.locator('#draftStatus')).toHaveAttribute('data-state', 'connecting');

      // Both columns come straight from the stubbed draft -- raw is never
      // overwritten with the cleaned text, and vice versa.
      await expect(page.locator('#draftRawText')).toHaveText(PENDING_DRAFT.raw_text);
      await expect(page.locator('#draftFinalText')).toHaveValue(PENDING_DRAFT.final_text);

      // renderConfidenceBadge(): 0.42 -> 42%, and 0.4 <= score < 0.65 -> warning.
      const badge = page.locator('#draftConfidence');
      await expect(badge).toBeVisible();
      await expect(badge).toHaveText('42% confident');
      await expect(badge).toHaveAttribute('data-tone', 'warning');

      // renderTokenSummary(): limit present -> "count / limit tokens", no
      // "· long text" suffix and no warning state because long_text is false.
      await expect(page.locator('#draftTokenSummary')).toHaveText('12 / 1200 tokens');
      await expect(page.locator('#draftTokenSummary')).not.toHaveAttribute('data-state', 'warning');

      // formatDraftMetadata() / formatDraftMetadataDetail().
      await expect(page.locator('#draftMetadata')).toHaveText('4.2s recording · auto-stopped on silence');
      await expect(page.locator('#draftMetadata')).toHaveAttribute(
        'title',
        'samples 67200 @ 16000 Hz · peak 0.42100 · rms 0.01230',
      );

      // No spurious long-text warning for a draft that is comfortably short.
      await expect(page.locator('#draftMessage')).toHaveText('');

      // setDraftControlsEnabled(): a pending draft with final text is fully
      // reviewable; Retry is only for blocked/error drafts.
      await expect(page.locator('#draftFinalText')).toBeEnabled();
      await expect(page.locator('#acceptDraftButton')).toBeEnabled();
      await expect(page.locator('#sendDraftButton')).toBeEnabled();
      await expect(page.locator('#copyDraftButton')).toBeEnabled();
      await expect(page.locator('#retryDraftButton')).toBeDisabled();
    },
    screenshots: [{ name: 'latest-draft-renders-with-confidence' }],
  },
  {
    area: 'drafts',
    name: 'draft-history-lists-and-selects',
    kind: 'standard',
    description:
      'Three drafts in the backend render as three history entries via renderDraftHistory(), newest first, each ' +
      'labelled "#id · status" with its text truncated to 140 characters plus an ellipsis. The newest draft is the ' +
      'one loaded into the review editor on boot. Clicking an older, declined entry re-renders it through the same ' +
      'renderDraft() path: the editor, status pill and action buttons all follow it, and the confidence badge from ' +
      'the previously selected draft disappears rather than lingering as stale state.',
    backendState: () => baseState({ 'GET /drafts': { drafts: HISTORY } }),
    async navigate(page) {
      await goToDashboard(page);
    },
    async expects(page) {
      const items = page.locator('#draftHistoryList .draft-history-item');
      await expect(items).toHaveCount(3);

      // Reversed: newest (#7, last in the API payload) sits at the top.
      await expect(items.nth(0).locator('strong')).toHaveText('#7 · pending');
      await expect(items.nth(1).locator('strong')).toHaveText('#6 · sent');
      await expect(items.nth(2).locator('strong')).toHaveText('#5 · declined');

      // Status drives the per-entry data attribute used for the colour coding.
      await expect(page.locator('#draftHistoryList .draft-history-item[data-status="declined"]')).toHaveCount(1);

      // Short text is shown whole; anything over 140 chars is cut and elided.
      await expect(items.nth(0).locator('small')).toHaveText(PENDING_DRAFT.final_text);
      await expect(items.nth(1).locator('small')).toHaveText(`${LONG_FINAL_TEXT.slice(0, 140)}...`);

      // refreshDrafts() renders the LAST draft in the payload as the current one.
      await expect(page.locator('#draftFinalText')).toHaveValue(PENDING_DRAFT.final_text);
      await expect(page.locator('#draftConfidence')).toBeVisible();

      // Clicking an older entry re-renders it -- same renderDraft() path.
      await items.nth(2).click();
      await expect(page.locator('#draftStatus')).toHaveText('declined');
      await expect(page.locator('#draftRawText')).toHaveText(DECLINED_DRAFT.raw_text);
      await expect(page.locator('#draftFinalText')).toHaveValue(DECLINED_DRAFT.final_text);
      await expect(page.locator('#draftTokenSummary')).toHaveText('5 / 1200 tokens');
      // #5 carries no confidence, so the badge must hide rather than keep #7's.
      await expect(page.locator('#draftConfidence')).toBeHidden();
      // ...and it has no recording metadata at all.
      await expect(page.locator('#draftMetadata')).toHaveText('No recording metadata available.');
      // Accept only applies to pending drafts, so it must have gone dead.
      await expect(page.locator('#acceptDraftButton')).toBeDisabled();
    },
    screenshots: [{ name: 'draft-history-lists-and-selects' }],
  },
  {
    area: 'drafts',
    name: 'history-search-renders-archive-results',
    kind: 'standard',
    description:
      'Typing into the history search box routes through handleHistorySearch() to the FTS archive endpoint and ' +
      'replaces the recent-drafts list with renderHistoryResults() output: one entry per matching archived row, ' +
      'each labelled with its status and its stored text. Emptying the query restores the ordinary recent-drafts ' +
      'view from /drafts, so search is a filter over the list rather than a one-way trip.',
    backendState: () =>
      baseState({
        'GET /drafts': { drafts: HISTORY },
        // Shape from server.py history_search() -> history_store.search(), whose
        // rows are history_store._row_to_dict(): id/created_at/status/profile/
        // raw_text/final_text.
        'GET /history/search': (req, { query }) => ({
          ok: true,
          query: query.q,
          count: 2,
          results: [
            {
              id: 8,
              created_at: '2026-07-20T09:15:00+00:00',
              status: 'sent',
              profile: 'Default',
              raw_text: 'following up on the deploy window',
              final_text: 'Confirmed the deploy window with the on-call rotation.',
            },
            {
              id: 3,
              created_at: '2026-07-19T17:02:00+00:00',
              status: 'declined',
              profile: 'Default',
              raw_text: 'deploy window question',
              final_text: 'Do we still need the deploy window on Thursday?',
            },
          ],
        }),
      }),
    async navigate(page) {
      await goToDashboard(page);
    },
    async expects(page) {
      const items = page.locator('#draftHistoryList .draft-history-item');
      await expect(items).toHaveCount(3);

      // handleHistorySearch() debounces internally; expect() auto-retries, so
      // this needs no sleep and makes no assertion about how long it took.
      await page.fill('#historySearchInput', 'deploy');
      await expect(items).toHaveCount(2);

      // Archive rows are labelled "<when> · <status>". The timestamp is
      // rendered with toLocaleString(), so only the status half is asserted --
      // the harness pins TZ but not the locale's date formatting.
      await expect(items.nth(0).locator('strong')).toContainText('· sent');
      await expect(items.nth(1).locator('strong')).toContainText('· declined');
      await expect(items.nth(0).locator('small')).toHaveText(
        'Confirmed the deploy window with the on-call rotation.',
      );
      await expect(items.nth(1).locator('small')).toHaveText('Do we still need the deploy window on Thursday?');
      await expect(page.locator('#draftHistoryList .draft-history-item[data-status="sent"]')).toHaveCount(1);

      // Clearing the box restores the recent-drafts view (ids, not timestamps).
      await page.fill('#historySearchInput', '');
      await expect(items).toHaveCount(3);
      await expect(items.nth(0).locator('strong')).toHaveText('#7 · pending');
    },
    screenshots: [{ name: 'history-search-renders-archive-results' }],
  },
];
