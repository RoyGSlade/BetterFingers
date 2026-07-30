// Unit tests for the Library workspace wiring adapter's PURE helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 5). Mirrors talkWorkspace.test.mjs's
// approach: only the DOM-free "data -> view model" logic is exercised here
// (day grouping, glyph/color mapping, confidence banding, filter predicate) --
// createLibraryWorkspaceFeature()'s DOM wiring itself needs a real document
// and is exercised manually via signal-desk-preview.html per the phase brief.
//
// Run with: node --test app/tests/libraryWorkspace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  dayLabelFor,
  formatClockTime,
  formatDuration,
  groupByDay,
  deriveLibraryStatusFromDraft,
  statusToGlyph,
  glyphColorVar,
  pipelineStatusLabel,
  resolvedStatusTimestamp,
  statusLineText,
  mapLibraryConfidenceBand,
  itemMatchesFilters,
  filterItems,
  deriveLibraryItemFromDraft,
  contactNameFor,
  deriveLibraryItemFromRecording,
  LIBRARY_ELEMENT_IDS,
  collectLibraryElements,
  createLibraryWorkspaceFeature,
} from '../src/renderer/features/libraryWorkspace.js';
import { makeDocument, installDomGlobals } from './helpers/rendererDom.mjs';

const NOW = new Date(2026, 6, 24, 12, 0, 0); // Fri Jul 24 2026, noon local time

// --- dayLabelFor / groupByDay -------------------------------------------------

test('dayLabelFor: same calendar day as `now` is Today', () => {
  const ts = new Date(2026, 6, 24, 9, 15, 0).getTime();
  assert.equal(dayLabelFor(ts, NOW), 'Today');
});

test('dayLabelFor: one calendar day back is Yesterday, even close to midnight', () => {
  const ts = new Date(2026, 6, 23, 23, 59, 0).getTime();
  assert.equal(dayLabelFor(ts, NOW), 'Yesterday');
});

test('dayLabelFor: older dates render as an abbreviated month + day', () => {
  const ts = new Date(2026, 6, 20, 10, 0, 0).getTime();
  assert.equal(dayLabelFor(ts, NOW), 'Jul 20');
});

test('dayLabelFor: an invalid timestamp never throws, returns Unknown', () => {
  assert.equal(dayLabelFor('not-a-date', NOW), 'Unknown');
  assert.equal(dayLabelFor(undefined, NOW), 'Unknown');
});

test('groupByDay: buckets items by day label, preserving first-seen day order', () => {
  const items = [
    { id: 1, timestamp: new Date(2026, 6, 24, 10, 32).getTime() },
    { id: 2, timestamp: new Date(2026, 6, 24, 9, 47).getTime() },
    { id: 3, timestamp: new Date(2026, 6, 23, 16, 22).getTime() },
  ];
  const groups = groupByDay(items, NOW);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].label, 'Today');
  assert.equal(groups[0].items.length, 2);
  assert.equal(groups[1].label, 'Yesterday');
  assert.equal(groups[1].items.length, 1);
});

test('groupByDay: empty/undefined input yields no groups, never throws', () => {
  assert.deepEqual(groupByDay(undefined, NOW), []);
  assert.deepEqual(groupByDay([], NOW), []);
});

// --- formatClockTime / formatDuration -----------------------------------------

test('formatClockTime: renders 12-hour time with AM/PM and zero-padded minutes', () => {
  assert.equal(formatClockTime(new Date(2026, 6, 24, 10, 32).getTime()), '10:32 AM');
  assert.equal(formatClockTime(new Date(2026, 6, 24, 0, 5).getTime()), '12:05 AM');
  assert.equal(formatClockTime(new Date(2026, 6, 24, 12, 0).getTime()), '12:00 PM');
  assert.equal(formatClockTime(new Date(2026, 6, 24, 16, 22).getTime()), '4:22 PM');
});

test('formatClockTime: invalid timestamp returns empty string, never throws', () => {
  assert.equal(formatClockTime('nonsense'), '');
});

test('formatDuration: seconds render as m:ss, zero-padded', () => {
  assert.equal(formatDuration(6), '0:06');
  assert.equal(formatDuration(65), '1:05');
  assert.equal(formatDuration(0), '0:00');
});

test('formatDuration: negative/NaN input clamps to 0:00', () => {
  assert.equal(formatDuration(-5), '0:00');
  assert.equal(formatDuration(NaN), '0:00');
  assert.equal(formatDuration(undefined), '0:00');
});

// --- deriveLibraryStatusFromDraft ---------------------------------------------

test('deriveLibraryStatusFromDraft: a successful send_result is sent', () => {
  assert.equal(deriveLibraryStatusFromDraft({ status: 'pending', send_result: { ok: true } }), 'sent');
});

test('deriveLibraryStatusFromDraft: a failed send_result is failed', () => {
  assert.equal(deriveLibraryStatusFromDraft({ status: 'pending', send_result: { ok: false } }), 'failed');
});

test('deriveLibraryStatusFromDraft: blocked/error status with no send_result is recoverable', () => {
  assert.equal(deriveLibraryStatusFromDraft({ status: 'blocked' }), 'recoverable');
  assert.equal(deriveLibraryStatusFromDraft({ status: 'error' }), 'recoverable');
});

test('deriveLibraryStatusFromDraft: pending with no send_result is unsent', () => {
  assert.equal(deriveLibraryStatusFromDraft({ status: 'pending' }), 'unsent');
});

test('deriveLibraryStatusFromDraft: null draft is unsent, never throws', () => {
  assert.equal(deriveLibraryStatusFromDraft(null), 'unsent');
});

// --- statusToGlyph / glyphColorVar ---------------------------------------------

test('statusToGlyph: pinned always wins regardless of status', () => {
  assert.equal(statusToGlyph({ status: 'sent', pinned: true }), 'pin');
  assert.equal(statusToGlyph({ status: 'recoverable', pinned: true }), 'pin');
});

test('statusToGlyph: sent -> sent, recoverable/failed -> warn, else -> draft', () => {
  assert.equal(statusToGlyph({ status: 'sent' }), 'sent');
  assert.equal(statusToGlyph({ status: 'recoverable' }), 'warn');
  assert.equal(statusToGlyph({ status: 'failed' }), 'warn');
  assert.equal(statusToGlyph({ status: 'unsent' }), 'draft');
  assert.equal(statusToGlyph({}), 'draft');
});

test('glyphColorVar: maps every known glyph to a css var(), unknown falls back to draft', () => {
  assert.equal(glyphColorVar('pin'), 'var(--sd-amber)');
  assert.equal(glyphColorVar('sent'), 'var(--sd-blue-light)');
  assert.equal(glyphColorVar('warn'), 'var(--sd-amber)');
  assert.equal(glyphColorVar('draft'), 'var(--sd-text-muted)');
  assert.equal(glyphColorVar('nonsense'), 'var(--sd-text-muted)');
});

// --- pipelineStatusLabel / statusLineText --------------------------------------

test('pipelineStatusLabel: sent/recoverable/unsent map to the mockup\'s exact labels', () => {
  assert.equal(pipelineStatusLabel('sent'), 'Sent');
  assert.equal(pipelineStatusLabel('recoverable'), 'Recoverable');
  assert.equal(pipelineStatusLabel('failed'), 'Recoverable');
  assert.equal(pipelineStatusLabel('unsent'), 'Unsent');
  assert.equal(pipelineStatusLabel('anything-else'), 'Unsent');
});

test('statusLineText: sent includes the day/time; failed/unsent use fixed copy', () => {
  assert.equal(statusLineText({ status: 'sent', dayLabel: 'Today', timeLabel: '10:33 AM' }), 'Sent • Today, 10:33 AM');
  assert.equal(statusLineText({ status: 'failed' }), 'Failed to send');
  assert.equal(statusLineText({ status: 'recoverable' }), 'Failed to send');
  assert.equal(statusLineText({ status: 'unsent' }), 'Unsent • Draft');
  assert.equal(statusLineText({}), 'Unsent • Draft');
});

// --- resolvedStatusTimestamp -----------------------------------------------------

test('resolvedStatusTimestamp: a sent item with a sentAtTimestamp quotes that, not the capture time', () => {
  const captureTs = new Date(2026, 6, 24, 10, 32).getTime();
  const sentTs = new Date(2026, 6, 24, 10, 33).getTime();
  assert.equal(resolvedStatusTimestamp({ status: 'sent', timestamp: captureTs, sentAtTimestamp: sentTs }), sentTs);
});

test('resolvedStatusTimestamp: a sent item with no sentAtTimestamp falls back to capture time', () => {
  const captureTs = new Date(2026, 6, 24, 10, 32).getTime();
  assert.equal(resolvedStatusTimestamp({ status: 'sent', timestamp: captureTs, sentAtTimestamp: null }), captureTs);
});

test('resolvedStatusTimestamp: a non-sent item always uses the capture time, ignoring sentAtTimestamp', () => {
  const captureTs = new Date(2026, 6, 24, 8, 15).getTime();
  const bogusSentTs = new Date(2026, 6, 24, 9, 0).getTime();
  assert.equal(resolvedStatusTimestamp({ status: 'recoverable', timestamp: captureTs, sentAtTimestamp: bogusSentTs }), captureTs);
});

// --- mapLibraryConfidenceBand ---------------------------------------------------

test('mapLibraryConfidenceBand: >=85 is always high regardless of status', () => {
  assert.equal(mapLibraryConfidenceBand(0.94, 'sent'), 'high');
  assert.equal(mapLibraryConfidenceBand(0.94, 'unsent'), 'high');
});

test('mapLibraryConfidenceBand: 70-84 is high when sent, draft(blue) when unsent', () => {
  assert.equal(mapLibraryConfidenceBand(0.72, 'sent'), 'high');
  assert.equal(mapLibraryConfidenceBand(0.72, 'unsent'), 'draft');
  assert.equal(mapLibraryConfidenceBand(0.72, 'draft'), 'draft');
});

test('mapLibraryConfidenceBand: 60-69 is mid(amber); below 60 is low', () => {
  assert.equal(mapLibraryConfidenceBand(0.61, 'recoverable'), 'mid');
  assert.equal(mapLibraryConfidenceBand(0.42, 'failed'), 'low');
});

// --- itemMatchesFilters / filterItems -------------------------------------------

const SAMPLE_ITEMS = [
  { id: 'a', status: 'sent', pinned: true, persona: 'Natural', contact: 'Priya', preview: 'I should be there around six' },
  { id: 'b', status: 'sent', pinned: false, persona: 'Professional', contact: 'Sam', preview: 'Can we push the meeting back?' },
  { id: 'c', status: 'recoverable', pinned: false, persona: 'Natural', contact: 'Priya', preview: 'I wasn’t trying to be rude' },
  { id: 'd', status: 'unsent', pinned: false, persona: 'Creative', contact: 'Sam', preview: 'I have a few ideas to share' },
];

test('itemMatchesFilters: chip=all with no query/persona/contact matches everything', () => {
  assert.equal(SAMPLE_ITEMS.every((item) => itemMatchesFilters(item, { chip: 'all' })), true);
});

test('itemMatchesFilters: chip=pinned only matches pinned items', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'pinned' }).map((i) => i.id), ['a']);
});

test('itemMatchesFilters: chip=sent / recoverable / unsent partition correctly', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'sent' }).map((i) => i.id), ['a', 'b']);
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'recoverable' }).map((i) => i.id), ['c']);
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'unsent' }).map((i) => i.id), ['d']);
});

test('itemMatchesFilters: persona/contact filters narrow further', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', persona: 'Natural' }).map((i) => i.id), ['a', 'c']);
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', contact: 'Sam' }).map((i) => i.id), ['b', 'd']);
});

test('itemMatchesFilters: query does a case-insensitive substring match across preview/persona/contact', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', query: 'MEETING' }).map((i) => i.id), ['b']);
  // Searching a contact name finds their messages: the haystack covers the
  // contact, which is now a real field rather than the always-null
  // `destination` it replaced.
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', query: 'priya' }).map((i) => i.id), ['a', 'c']);
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', query: 'zzz-no-match' }), []);
});

test('filterItems: combines chip + query (AND semantics)', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'sent', query: 'push' }).map((i) => i.id), ['b']);
});

// --- deriveLibraryItemFromDraft / deriveLibraryItemFromRecording ----------------

test('deriveLibraryItemFromDraft: maps a sent, high-confidence draft into a Library item', () => {
  const draft = {
    id: 42,
    final_text: 'I should be there around six.',
    raw_text: 'i should be there around six',
    status: 'pending',
    confidence: { score: 0.94 },
    metadata: { duration_seconds: 6 },
    send_result: { ok: true },
    created_at: '2026-07-24T10:32:00Z',
  };
  const item = deriveLibraryItemFromDraft(draft);
  assert.equal(item.id, 'draft-42');
  assert.equal(item.sourceType, 'draft');
  assert.equal(item.status, 'sent');
  assert.equal(item.confidencePct, 94);
  assert.equal(item.confidenceBand, 'high');
  assert.equal(item.durationSeconds, 6);
  assert.equal(item.raw, draft);
});

test('deriveLibraryItemFromDraft: a null draft does not throw and yields an unsent item', () => {
  const item = deriveLibraryItemFromDraft(null);
  assert.equal(item.status, 'unsent');
  assert.equal(item.confidencePct, null);
});

test('deriveLibraryItemFromRecording: maps a recording row into a Library item', () => {
  const recording = { id: 7, raw_text: 'some raw capture', duration_seconds: 12, created_at: '2026-07-23T16:22:00Z' };
  const item = deriveLibraryItemFromRecording(recording);
  assert.equal(item.id, 'recording-7');
  assert.equal(item.sourceType, 'recording');
  assert.equal(item.status, 'unsent');
  assert.equal(item.durationSeconds, 12);
  assert.equal(item.raw, recording);
});

// --- collectLibraryElements ------------------------------------------------------

test('collectLibraryElements: every LIBRARY_ELEMENT_IDS key resolves to null against a stub with no matching ids', () => {
  const stubDoc = { getElementById: () => null };
  const els = collectLibraryElements(stubDoc);
  for (const key of Object.keys(LIBRARY_ELEMENT_IDS)) {
    assert.equal(els[key], null, `${key} should be null`);
  }
});

test('collectLibraryElements: resolves elements present in a stub document', () => {
  const found = { id: 'sdLibrarySearchInput' };
  const stubDoc = { getElementById: (id) => (id === 'sdLibrarySearchInput' ? found : null) };
  const els = collectLibraryElements(stubDoc);
  assert.equal(els.searchInput, found);
  assert.equal(els.filterButton, null);
});

// --- createLibraryWorkspaceFeature: safe no-op behavior with no elements -------

test('createLibraryWorkspaceFeature: init()/renderAll() never throw with empty elements/hooks', () => {
  const feature = createLibraryWorkspaceFeature({});
  assert.doesNotThrow(() => feature.init());
  assert.doesNotThrow(() => feature.renderAll());
  assert.equal(feature.getSelectedItem(), null);
});

test('createLibraryWorkspaceFeature: action handlers are safe no-ops with no hooks/selection', () => {
  // Wave 4 renamed these off the `*Click` suffix (they are no longer bound
  // one-to-one to a button) and made them async. With nothing selected they
  // must still resolve rather than reject -- an unhandled rejection here
  // would surface as a console error on a page where the user did nothing
  // wrong.
  const feature = createLibraryWorkspaceFeature({});
  return Promise.all([
    feature.handleReopen(),
    feature.handleDuplicate(),
    feature.handlePinToggle(),
    feature.handleRestore(),
    feature.handleResend(),
    feature.handleDeleteItem(),
  ]);
});

test('createLibraryWorkspaceFeature: setChipFilter/handleSearchInput never throw with no DOM', () => {
  const feature = createLibraryWorkspaceFeature({});
  assert.doesNotThrow(() => feature.setChipFilter('sent'));
  // An empty query takes the synchronous "restore view" branch (no network
  // call, no pending timer) -- the non-empty/debounced-search branch is I/O
  // (searchHistory() over fetch) and is intentionally left to manual/preview
  // verification rather than a unit test, same as talkWorkspace.test.mjs
  // does for its network-calling handlers.
  assert.doesNotThrow(() => feature.handleSearchInput(''));
});

// --- contacts (Stage 11) ------------------------------------------------------
//
// Replaces the `destination` fabrication: drafts never had a destination_name
// field, so that mapper was always null and the filter above it always matched
// everything. contact_id is real; the NAME needs the contact list.

test('contactNameFor resolves an id through the supplied lookup', () => {
  const byId = new Map([['a1', { id: 'a1', name: 'Priya' }]]);
  assert.equal(contactNameFor('a1', byId), 'Priya');
  assert.equal(contactNameFor('a1', { a1: { name: 'Priya' } }), 'Priya', 'plain objects work too');
});

test('contactNameFor returns null rather than an unreadable id', () => {
  // A draft written before contacts existed, or whose contact was deleted,
  // shows no contact -- never a raw id nobody can read.
  assert.equal(contactNameFor('gone', new Map()), null);
  assert.equal(contactNameFor(null, new Map()), null);
  assert.equal(contactNameFor('a1', null), null);
});

test('deriveLibraryItemFromDraft carries the contact id and resolved name', () => {
  const byId = new Map([['a1', { id: 'a1', name: 'Priya' }]]);
  const item = deriveLibraryItemFromDraft({ id: 7, final_text: 'hi', contact_id: 'a1' }, byId);
  assert.equal(item.contactId, 'a1');
  assert.equal(item.contact, 'Priya');
});

test('a draft with no contact is a first-class state, not an empty label', () => {
  const item = deriveLibraryItemFromDraft({ id: 7, final_text: 'hi' });
  assert.equal(item.contactId, null);
  assert.equal(item.contact, null);
});

test('a recording carries no contact — it has not been through cleanup', () => {
  const item = deriveLibraryItemFromRecording({ id: 3, raw_text: 'hi' });
  assert.equal(item.contactId, null);
  assert.equal(item.contact, null);
});

// ============================================================================
// WAVE 4 (Gate 4) -- the real /library/* surface.
//
// The Phase-3 module had nothing to test past its pure mappers because every
// mutation was a stub. Now the interesting behaviour IS the orchestration:
// which endpoint a decision routes to, whether confirmation actually gates
// the destructive call, whether reopen forks before Talk can touch history,
// and whether resend can reach a send path (it must not). All of that is
// exercised here with an injected `api`, so none of it needs a DOM or a
// backend -- the same reason the Python service takes its stores injected.
// ============================================================================

import {
  toEpochMs,
  buildSearchQuery,
  hasActiveFilters,
  narrowByContact,
  provenanceLabel,
  isRawTranscriptRestore,
  describeDeletePreview,
  describeClearPreview,
  describeLibraryError,
  statusLabel,
  LIBRARY_STATUS_GROUPS,
  KNOWN_STATUSES,
  CLEAR_SCOPES,
  LIBRARY_PLACEMENT_MAP,
  DEFAULT_LIBRARY_API,
} from '../src/renderer/features/libraryWorkspace.js';

// --- toEpochMs ---------------------------------------------------------------

test('toEpochMs: a recordings.py epoch-SECONDS float becomes milliseconds', () => {
  // recordings.py:96 stores time.time(). Passing that straight to new Date()
  // dates every retained recording to 1970 -- which is exactly what the
  // previous version of this module did.
  const seconds = 1785000000; // 2026-07-24-ish, in seconds
  assert.equal(toEpochMs(seconds), seconds * 1000);
  assert.equal(new Date(toEpochMs(seconds)).getUTCFullYear(), 2026);
});

test('toEpochMs: a millisecond epoch is left alone', () => {
  const ms = Date.UTC(2026, 6, 24, 10, 32);
  assert.equal(toEpochMs(ms), ms);
});

test('toEpochMs: an ISO string parses; junk and blanks yield null rather than NaN', () => {
  assert.equal(toEpochMs('2026-07-24T10:32:00Z'), Date.UTC(2026, 6, 24, 10, 32));
  assert.equal(toEpochMs('nonsense'), null);
  assert.equal(toEpochMs(null), null);
  assert.equal(toEpochMs(''), null);
});

test('deriveLibraryItemFromRecording dates an epoch-seconds recording in the right decade', () => {
  const item = deriveLibraryItemFromRecording({ id: 9, created_at: 1785000000, duration_seconds: 3 });
  assert.equal(new Date(item.timestamp).getUTCFullYear(), 2026);
});

// --- buildSearchQuery --------------------------------------------------------

test('buildSearchQuery: empty filters send only pagination', () => {
  assert.deepEqual(buildSearchQuery({}, { limit: 25, offset: 0 }), { limit: 25, offset: 0 });
});

test('buildSearchQuery: each backend filter maps to its documented parameter name', () => {
  const query = buildSearchQuery(
    { persona: 'True Janitor', status: 'sent', dateFrom: '2026-07-01', dateTo: '2026-07-24', query: '  standup  ' },
    { limit: 10, offset: 20 },
  );
  assert.deepEqual(query, {
    limit: 10,
    offset: 20,
    persona: 'True Janitor',
    status: 'sent',
    date_from: '2026-07-01',
    date_to: '2026-07-24',
    q: 'standup',
  });
});

test('buildSearchQuery: the pinned chip is the only chip that becomes a parameter', () => {
  assert.equal(buildSearchQuery({ chip: 'pinned' }).pinned, true);
  assert.equal('pinned' in buildSearchQuery({ chip: 'all' }), false);
});

test('buildSearchQuery: contact is NEVER sent — the route has no contact filter until Wave 5', () => {
  // Sending it would be silently dropped by parse_filters while the UI
  // implied the archive had been narrowed. Contract §2.
  const query = buildSearchQuery({ contact: 'c-1' });
  assert.equal('contact' in query, false);
  assert.equal(Object.keys(query).sort().join(','), 'limit,offset');
});

test('hasActiveFilters: distinguishes "empty archive" from "filters matched nothing"', () => {
  assert.equal(hasActiveFilters({}), false);
  assert.equal(hasActiveFilters({ chip: 'all', query: '   ' }), false);
  assert.equal(hasActiveFilters({ chip: 'pinned' }), true);
  assert.equal(hasActiveFilters({ status: 'sent' }), true);
  assert.equal(hasActiveFilters({ contact: 'c-1' }), true);
});

test('narrowByContact: no contact selected returns the list untouched', () => {
  const items = [{ contactId: 'a' }, { contactId: null }];
  assert.equal(narrowByContact(items, ''), items);
  assert.deepEqual(narrowByContact(items, 'a'), [{ contactId: 'a' }]);
});

// --- provenance (contract §1 + D-0020) ----------------------------------------

test('provenanceLabel: a restored RECORDING is labelled a raw transcript (D-0020)', () => {
  const label = provenanceLabel({ restored_from_recording_id: 'rec-1' });
  assert.equal(label.key, 'raw-transcript');
  assert.equal(label.label, 'Raw transcript');
  assert.equal(label.tone, 'warn');
  assert.match(label.detail, /has not been through persona cleanup/);
});

test('provenanceLabel: a restored DRAFT is NOT labelled a raw transcript', () => {
  // build_restore_from_draft carries the source's final_text over, so that
  // text HAS been cleaned up. Calling it raw would be its own inaccuracy.
  const label = provenanceLabel({ restored_from_draft_id: 12 });
  assert.equal(label.key, 'restored');
  assert.equal(isRawTranscriptRestore({ restored_from_draft_id: 12 }), false);
});

test('provenanceLabel: duplicate / reopened / revision each name the untouched original', () => {
  assert.match(provenanceLabel({ duplicated_from_id: 3 }).detail, /#3.*unchanged/);
  assert.match(provenanceLabel({ reopened_from_id: 4 }).detail, /#4.*untouched/);
  assert.match(provenanceLabel({ revision_of_id: 5 }).detail, /#5.*unchanged/);
});

test('provenanceLabel: a plain captured draft has no provenance badge', () => {
  assert.equal(provenanceLabel({ id: 1, status: 'pending' }), null);
  assert.equal(provenanceLabel(null), null);
});

test('provenanceLabel: reads through a view model as well as a raw record', () => {
  const item = deriveLibraryItemFromDraft({ id: 8, restored_from_recording_id: 'rec-9' });
  assert.equal(item.provenance.key, 'raw-transcript');
  assert.equal(isRawTranscriptRestore(item), true);
});

test('provenanceLabel: id 0 is a real id, not an absent one', () => {
  // A `!rec.duplicated_from_id` test would treat draft #0 as "no provenance".
  assert.equal(provenanceLabel({ duplicated_from_id: 0 }).key, 'duplicate');
});

// --- status vocabulary --------------------------------------------------------

test('the status filter offers exactly the backend KNOWN_STATUSES set', () => {
  // A status the UI offers but the backend rejects is a 400 the user cannot
  // explain; a status the store holds but the UI cannot select is history the
  // user cannot reach. Both are why this list is a contract copy.
  assert.deepEqual(
    [...KNOWN_STATUSES].sort(),
    ['accepted', 'blocked', 'declined', 'error', 'failed', 'pending', 'scratch',
      'send_error', 'send_interrupted', 'sending', 'sent'].sort(),
  );
});

test('every status the filter offers has a human label', () => {
  for (const status of KNOWN_STATUSES) {
    assert.notEqual(statusLabel(status), status, `${status} renders as its raw code`);
  }
});

test('the status groups partition the vocabulary — no status listed twice, none missing', () => {
  const flat = LIBRARY_STATUS_GROUPS.flatMap((g) => g.statuses);
  assert.equal(new Set(flat).size, flat.length, 'a status appears in two groups');
  assert.equal(flat.length, KNOWN_STATUSES.length);
});

// --- destructive-action copy (contract §7: content-free) -----------------------

const SECRET = 'my bank password is hunter2';

test('describeDeletePreview: quotes a character COUNT, never the characters', () => {
  const spec = describeDeletePreview('draft', {
    id: 4,
    created_at: '2026-07-24T10:32:00Z',
    status: 'pending',
    char_count: SECRET.length,
    has_recording: false,
  });
  const blob = JSON.stringify(spec);
  assert.equal(blob.includes(SECRET), false, 'message text leaked into the dialog');
  assert.equal(blob.includes('hunter2'), false);
  assert.ok(spec.details.some((d) => d.includes(`${SECRET.length} characters`)));
});

test('describeDeletePreview: says out loud when audio goes with the item', () => {
  const withAudio = describeDeletePreview('draft', { has_recording: true });
  assert.ok(withAudio.details.some((d) => /audio recording is removed too/.test(d)));
  const without = describeDeletePreview('draft', { has_recording: false });
  assert.equal(without.details.some((d) => /audio/.test(d)), false);
});

test('describeDeletePreview: each kind names where the item actually lives', () => {
  assert.match(describeDeletePreview('draft', {}).body, /draft queue/);
  assert.match(describeDeletePreview('history_entry', {}).body, /message history/);
  assert.match(describeDeletePreview('recording', {}).body, /saved recordings/);
});

test('describeClearPreview: each scope states what it KEEPS, not only what it destroys', () => {
  // Contract §7 requires drafts_and_history to leave recordings alone and
  // vice versa. A dialog listing only casualties gives the user no way to
  // check that promise.
  const drafts = describeClearPreview('drafts_and_history', {});
  assert.ok(drafts.keeps.some((k) => /recording/i.test(k)), 'does not promise recordings survive');
  assert.equal(drafts.removes.some((r) => /recording/i.test(r)), false, 'claims to remove recordings');

  const recordings = describeClearPreview('recordings', {});
  assert.ok(recordings.keeps.some((k) => /history/i.test(k)));
  assert.equal(recordings.removes.some((r) => /draft/i.test(r)), false);

  const all = describeClearPreview('all_conversation_data', {});
  assert.equal(all.removes.length, 3);
  assert.ok(all.keeps.some((k) => /personas/i.test(k)));
});

test('describeClearPreview: every scope says confirming one says nothing about the others', () => {
  for (const scope of CLEAR_SCOPES) {
    assert.match(describeClearPreview(scope, {}).body, /on its own/);
  }
});

test('describeClearPreview: an unobserved category is described WITHOUT a count, never as zero', () => {
  // "0 recordings" when we simply have not looked is a lie that talks a user
  // into a destructive click.
  const unknown = describeClearPreview('all_conversation_data', {});
  assert.deepEqual(unknown.details, []);
  const partial = describeClearPreview('all_conversation_data', { recordings: 2 });
  assert.deepEqual(partial.details, ['2 saved recordings']);
  const one = describeClearPreview('recordings', { recordings: 1 });
  assert.deepEqual(one.details, ['1 saved recording'], 'singular/plural');
});

// --- error copy ----------------------------------------------------------------

test('describeLibraryError: the structured code drives the sentence, not the raw message', () => {
  const inFlight = Object.assign(new Error('400 Bad Request'), { detail: 'send_in_flight' });
  assert.match(describeLibraryError(inFlight, 'Deleting'), /being sent right now/);

  const gone = Object.assign(new Error('nope'), { detail: 'not_found' });
  assert.match(describeLibraryError(gone, 'Deleting'), /no longer in your Library/);

  const write = Object.assign(new Error('nope'), { detail: 'write_failed' });
  assert.match(describeLibraryError(write, 'Pinning'), /Nothing was changed/);
});

test('describeLibraryError: an unrecognised failure still names the action and the cause', () => {
  const message = describeLibraryError(new Error('socket hang up'), 'Loading your Library');
  assert.match(message, /Loading your Library failed: socket hang up/);
});

// --- Gate 4 parity rule ---------------------------------------------------------

test('GATE 4: every Library placement entry is wired, or an intentional cut with a rationale', () => {
  // The Gate 4 rule: no entry may end this wave as a bare `false` with a
  // TODO/blocked note. Either it works, or it is a declared cut that says why
  // and what seam would un-cut it.
  const offenders = [];
  for (const [key, entry] of Object.entries(LIBRARY_PLACEMENT_MAP)) {
    if (entry.wired === true) {
      if (entry.intentional_cut) offenders.push(`${key}: wired AND marked an intentional cut`);
      continue;
    }
    if (entry.intentional_cut !== true) {
      offenders.push(`${key}: unwired and not declared an intentional cut`);
      continue;
    }
    if (typeof entry.note !== 'string' || entry.note.length < 40) {
      offenders.push(`${key}: intentional cut with no substantive rationale`);
    }
  }
  assert.deepEqual(offenders, []);
});

test('GATE 4: no Library entry hides behind a TODO / blocked / "not wired up yet" note', () => {
  const offenders = Object.entries(LIBRARY_PLACEMENT_MAP)
    .filter(([, entry]) => /\bTODO\b|\bblocked\b|not wired up yet|isn.t wired/i.test(entry.note || ''))
    .map(([key]) => key);
  assert.deepEqual(offenders, []);
});

test('GATE 4: the two cuts are the ones the director actually ruled on', () => {
  const cuts = Object.entries(LIBRARY_PLACEMENT_MAP)
    .filter(([, entry]) => entry.intentional_cut)
    .map(([key]) => key)
    .sort();
  assert.deepEqual(cuts, ['search.statusGroups', 'timeline.waveformThumb']);
});

test('the waveform thumbnail stays cut, and the note still cites why it is undrawable', () => {
  const entry = LIBRARY_PLACEMENT_MAP['timeline.waveformThumb'];
  assert.equal(entry.wired, false);
  assert.equal(entry.intentional_cut, true);
  assert.match(entry.note, /amplitude/i);
});

// --- feature orchestration ------------------------------------------------------

/**
 * A stub element set. Only the handful the orchestration actually consults
 * without a document: the live region (so announcements are observable) and
 * the confirm dialog (whose mere PRESENCE is what lets requestConfirmation
 * open -- with no dialog in the document it refuses rather than proceeding
 * with a destructive call, which is itself asserted below).
 */
function stubElements() {
  return {
    liveRegion: { textContent: '' },
    confirmDialog: { hidden: true, addEventListener() {} },
    loadMoreButton: { hidden: true, disabled: false },
  };
}

function draftRecord(overrides = {}) {
  return {
    id: 1,
    raw_text: 'hey can we push standup',
    final_text: 'Hey, can we push standup back?',
    status: 'pending',
    preset: 'True Janitor',
    pinned: false,
    created_at: '2026-07-24T10:32:00Z',
    metadata: { duration_seconds: 6 },
    ...overrides,
  };
}

/** Records every api call so a test can assert what was NOT called too. */
function recordingApi(overrides = {}) {
  const calls = [];
  const track = (name, result) => (...args) => {
    calls.push({ name, args });
    return Promise.resolve(typeof result === 'function' ? result(...args) : result);
  };
  const api = {
    calls,
    names: () => calls.map((c) => c.name),
    librarySearch: track('librarySearch', { ok: true, results: [], total: 0 }),
    fetchRecordings: track('fetchRecordings', { ok: true, recordings: [] }),
    setLibraryDraftPinned: track('setLibraryDraftPinned', { ok: true, draft: draftRecord({ pinned: true, pinned_at: 'x' }) }),
    deleteLibraryDraft: track('deleteLibraryDraft', { ok: true, removed: true }),
    deleteLibraryHistoryEntry: track('deleteLibraryHistoryEntry', { ok: true, removed: true }),
    deleteLibraryRecording: track('deleteLibraryRecording', { ok: true, removed: true }),
    duplicateLibraryDraft: track('duplicateLibraryDraft', { ok: true, draft: draftRecord({ id: 2, duplicated_from_id: 1 }) }),
    fetchLibraryReopen: track('fetchLibraryReopen', { ok: true, reopen: { source_id: 1, editable: true, requires_new_record: false } }),
    commitLibraryReopenEdit: track('commitLibraryReopenEdit', { ok: true, draft: draftRecord({ id: 3, reopened_from_id: 1 }) }),
    resendLibraryDraft: track('resendLibraryDraft', { ok: true, resend: { allowed: true, reason: '', next_action: 'reopen_for_review' }, reopen: {} }),
    restoreLibraryRecording: track('restoreLibraryRecording', { ok: true, draft: draftRecord({ id: 4, restored_from_recording_id: 'rec-1' }) }),
    restoreLibraryDraft: track('restoreLibraryDraft', { ok: true, draft: draftRecord({ id: 5, restored_from_draft_id: 1 }) }),
    clearLibrary: track('clearLibrary', { ok: true }),
  };
  return Object.assign(api, overrides);
}

function makeFeature({ api = recordingApi(), hooks = {}, elements = stubElements() } = {}) {
  const feature = createLibraryWorkspaceFeature({ elements, hooks, api });
  return { feature, api, elements };
}

/** Answers the pending confirmation dialog once it opens. */
async function answerNextConfirm(feature, accepted) {
  await Promise.resolve();
  assert.ok(feature.getPendingConfirmation(), 'no confirmation was requested');
  feature.answerConfirmation(accepted);
}

test('the module exports the whole /library/* surface as its default api', () => {
  // A missing wrapper here is a silently dead button, so the default surface
  // is asserted rather than assumed.
  for (const name of [
    'librarySearch', 'setLibraryDraftPinned', 'deleteLibraryDraft', 'deleteLibraryHistoryEntry',
    'deleteLibraryRecording', 'duplicateLibraryDraft', 'fetchLibraryReopen', 'commitLibraryReopenEdit',
    'resendLibraryDraft', 'restoreLibraryRecording', 'restoreLibraryDraft', 'clearLibrary', 'fetchRecordings',
  ]) {
    assert.equal(typeof DEFAULT_LIBRARY_API[name], 'function', `${name} is missing from the api surface`);
  }
});

test('loadPage asks the backend to do the filtering, and trusts its total', () => {
  const api = recordingApi({
    librarySearch: (query) => {
      assert.deepEqual(query, { limit: 25, offset: 0, status: 'sent', persona: 'True Janitor' });
      return Promise.resolve({ ok: true, results: [draftRecord({ status: 'sent' })], total: 137 });
    },
  });
  const { feature } = makeFeature({ api });
  return feature.applyFilters({ status: 'sent', persona: 'True Janitor' }).then(() => {
    assert.equal(feature.getTotal(), 137, 'the footer total must be the archive total, not the page size');
    assert.equal(feature.getVisibleItems().length, 1);
  });
});

test('load more appends at the next offset instead of refetching page one', async () => {
  const seen = [];
  const api = recordingApi({
    librarySearch: (query) => {
      seen.push(query.offset);
      return Promise.resolve({
        ok: true,
        results: [draftRecord({ id: query.offset + 1 })],
        total: 3,
      });
    },
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  await feature.loadMore();
  assert.deepEqual(seen, [0, 1]);
  assert.equal(feature.getVisibleItems().length, 2);
});

test('load more stops asking once every item is loaded', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord()], total: 1 }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  const before = api.calls.length;
  await feature.loadMore();
  assert.equal(api.calls.length, before, 'requested a page past the end');
});

test('a failed load reports the failure — it never renders as an empty Library', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.reject(Object.assign(new Error('socket hang up'), { status: 0 })),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  const said = feature.getLastAnnouncement();
  assert.match(said, /Loading your Library failed/);
  assert.equal(/nothing in your library/i.test(said), false, 'an unreachable backend was reported as an empty archive');
});

// --- QA-LIB-001: the true-empty state gets exactly one primary action -------
// (the error and filtered-empty branches already had one -- Try again /
// Clear filters -- this is the branch a first-time user actually hits).

test('the genuine-empty Library state offers exactly one primary action: Go to Talk', async () => {
  const doc = makeDocument(['sdLibraryTimeline']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  try {
    const api = recordingApi({ librarySearch: () => Promise.resolve({ ok: true, results: [], total: 0 }) });
    const elements = { ...stubElements(), timelineContainer: doc.getElementById('sdLibraryTimeline') };
    const { feature } = makeFeature({ api, elements });
    await feature.loadPage();

    const container = elements.timelineContainer;
    const actions = container.querySelectorAll('.sd-timeline__empty-action');
    assert.equal(actions.length, 1, '§5.4 requires exactly one primary action on an empty state');
    assert.equal(actions[0].id, 'sdLibraryGoToTalkButton');
    assert.match(container.textContent, /Nothing in your Library yet\. Messages you capture in Talk land here\./);
  } finally {
    restore();
  }
});

test('the Go to Talk action on the genuine-empty state really navigates to Talk', async () => {
  const doc = makeDocument(['sdLibraryTimeline']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  try {
    const api = recordingApi({ librarySearch: () => Promise.resolve({ ok: true, results: [], total: 0 }) });
    const elements = { ...stubElements(), timelineContainer: doc.getElementById('sdLibraryTimeline') };
    const goTo = [];
    const { feature } = makeFeature({ api, elements, hooks: { shell: { goTo: (where) => goTo.push(where) } } });
    await feature.loadPage();

    const button = elements.timelineContainer.querySelector('#sdLibraryGoToTalkButton');
    assert.ok(button, 'Go to Talk button not found in the rendered empty state');
    button.click();

    assert.deepEqual(goTo, ['talk']);
  } finally {
    restore();
  }
});

test('the error and filtered-empty branches are unaffected: still exactly their own one action, not two', async () => {
  const doc = makeDocument(['sdLibraryTimeline']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  try {
    const api = recordingApi({ librarySearch: () => Promise.reject(new Error('socket hang up')) });
    const elements = { ...stubElements(), timelineContainer: doc.getElementById('sdLibraryTimeline') };
    const { feature } = makeFeature({ api, elements });
    await feature.loadPage();

    const actions = elements.timelineContainer.querySelectorAll('.sd-timeline__empty-action');
    assert.equal(actions.length, 1);
    assert.equal(actions[0].id, 'sdLibraryRetryButton');
  } finally {
    restore();
  }
});

test('recordings failing does not blank the timeline, and does not claim "none retained"', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord()], total: 1 }),
    fetchRecordings: () => Promise.reject(new Error('down')),
  });
  const { feature } = makeFeature({ api });
  await feature.refresh();
  assert.equal(feature.getVisibleItems().length, 1);
});

// --- Wave 12 collab task B: a repopulate must not discard a staged, --------
// unapplied contact-picker choice on the item the user is still looking at.

test('the contact picker keeps a staged, unapplied choice when the same item repopulates mid-session', async () => {
  const doc = makeDocument(['selectedContactPicker']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  try {
    const api = recordingApi({
      librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 9, contact_id: 'c1' })], total: 1 }),
    });
    const elements = { ...stubElements(), selectedContactPicker: doc.getElementById('selectedContactPicker') };
    const { feature } = makeFeature({ api, elements });
    feature.setContacts([{ id: 'c1', name: 'Alex' }, { id: 'c2', name: 'Sam' }]);
    await feature.loadPage();
    feature.selectItem('draft-9');

    const picker = elements.selectedContactPicker;
    assert.equal(picker.value, 'c1', 'sanity: rebuilt to the persisted contact');

    // The user opens the dropdown and picks someone else, but has not clicked
    // Apply yet -- nothing has been sent to the backend.
    picker.value = 'c2';

    // A cold-start/health-poll repopulate re-fetches and re-renders the SAME
    // item (bootstrap/signalDeskApp.js re-calls libraryWorkspace.refresh() on
    // every backend down->up transition).
    await feature.loadPage();

    assert.equal(picker.value, 'c2', 'an unapplied dropdown change must survive a repopulate of the same item');
  } finally {
    restore();
  }
});

test('the contact picker resets normally once a genuinely different item is selected', async () => {
  const doc = makeDocument(['selectedContactPicker']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  try {
    const api = recordingApi({
      librarySearch: () => Promise.resolve({
        ok: true,
        results: [draftRecord({ id: 9, contact_id: 'c1' }), draftRecord({ id: 10, contact_id: '' })],
        total: 2,
      }),
    });
    const elements = { ...stubElements(), selectedContactPicker: doc.getElementById('selectedContactPicker') };
    const { feature } = makeFeature({ api, elements });
    feature.setContacts([{ id: 'c1', name: 'Alex' }, { id: 'c2', name: 'Sam' }]);
    await feature.loadPage();
    feature.selectItem('draft-9');
    elements.selectedContactPicker.value = 'c2'; // staged, unapplied on item 9

    feature.selectItem('draft-10');
    assert.equal(
      elements.selectedContactPicker.value, '',
      "switching to a different item must not carry over the previous item's staged value",
    );
  } finally {
    restore();
  }
});

// --- Wave 12 collab task A: retry-once + keep-last-good on a real failure ---

test('loadPage retries once before giving up on a slow/failed first response', async () => {
  let attempts = 0;
  const api = recordingApi({
    librarySearch: () => {
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new Error('socket hang up'))
        : Promise.resolve({ ok: true, results: [draftRecord()], total: 1 });
    },
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  assert.equal(attempts, 2, 'a slow first response must be retried once, not surfaced as a permanent failure');
  assert.equal(feature.getVisibleItems().length, 1);
});

test('a refresh that fails AFTER a good page was already showing keeps that page on screen', async () => {
  let call = 0;
  const api = recordingApi({
    librarySearch: () => {
      call += 1;
      if (call <= 1) return Promise.resolve({ ok: true, results: [draftRecord()], total: 1 });
      // Every attempt from here on fails -- exhausts the retry too.
      return Promise.reject(new Error('socket hang up'));
    },
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  assert.equal(feature.getVisibleItems().length, 1, 'sanity: the first load succeeded');

  await feature.loadPage();
  assert.equal(
    feature.getVisibleItems().length, 1,
    'a later failed refresh must not blank a timeline that was already showing real items',
  );
  assert.match(feature.getLastAnnouncement(), /Loading your Library failed/);
});

test('loadRecordings retries once before giving up', async () => {
  let attempts = 0;
  const api = recordingApi({
    fetchRecordings: () => {
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new Error('down'))
        : Promise.resolve({ ok: true, recordings: [{ id: 'rec-1', created_at: 1785000000 }] });
    },
  });
  const { feature } = makeFeature({ api });
  const result = await feature.loadRecordings();
  assert.equal(attempts, 2, 'a slow first response must be retried once');
  assert.equal(result.length, 1);
});

test('a recordings refresh that fails AFTER a good list was already showing keeps that list', async () => {
  let call = 0;
  const api = recordingApi({
    fetchRecordings: () => {
      call += 1;
      if (call <= 1) return Promise.resolve({ ok: true, recordings: [{ id: 'rec-1', created_at: 1785000000 }] });
      return Promise.reject(new Error('down'));
    },
  });
  const { feature } = makeFeature({ api });
  const first = await feature.loadRecordings();
  assert.equal(first.length, 1, 'sanity: the first load succeeded');

  const second = await feature.loadRecordings();
  assert.equal(
    second.length, 1,
    'a later failed recordings refresh must not wipe a list that was already showing real items',
  );
  assert.match(feature.getLastAnnouncement(), /Loading saved recordings failed/);
});

test('pin persists through the backend, not a session Set', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  await feature.handlePinToggle();
  const call = api.calls.find((c) => c.name === 'setLibraryDraftPinned');
  assert.deepEqual(call.args, [7, true]);
  assert.equal(feature.getSelectedItem().pinned, true);
  assert.match(feature.getLastAnnouncement(), /after a restart/);
});

test('an unpinned/pin failure is reported and does not flip the UI state', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
    setLibraryDraftPinned: () => Promise.reject(Object.assign(new Error('x'), { detail: 'write_failed' })),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  await feature.handlePinToggle();
  assert.equal(feature.getSelectedItem().pinned, false, 'the UI claimed a pin the backend refused');
  assert.match(feature.getLastAnnouncement(), /could not be saved/);
});

// --- delete -----------------------------------------------------------------------

test('cancelling the confirmation performs NO delete call at all', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  const pending = feature.handleDeleteItem();
  await answerNextConfirm(feature, false);
  assert.equal(await pending, false);
  assert.equal(api.names().includes('deleteLibraryDraft'), false);
});

test('confirming sends confirm:true — the backend refuses an unconfirmed delete anyway', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  const pending = feature.handleDeleteItem();
  await answerNextConfirm(feature, true);
  assert.equal(await pending, true);
  const call = api.calls.find((c) => c.name === 'deleteLibraryDraft');
  assert.deepEqual(call.args, [7, { confirm: true }]);
});

test('an already-absent target reports "already gone", not "deleted"', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
    deleteLibraryDraft: () => Promise.resolve({ ok: true, removed: false, already_absent: true }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  const pending = feature.handleDeleteItem();
  await answerNextConfirm(feature, true);
  await pending;
  // Saying "Deleted" here would teach the user the app removed data it never
  // had -- the idempotent path is a distinct outcome, not a success message.
  assert.match(feature.getLastAnnouncement(), /already gone/);
});

test('a send-in-flight refusal is explained in the user\'s terms', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
    deleteLibraryDraft: () => Promise.reject(Object.assign(new Error('409'), { status: 409, detail: 'send_in_flight' })),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  const pending = feature.handleDeleteItem();
  await answerNextConfirm(feature, true);
  assert.equal(await pending, false);
  assert.match(feature.getLastAnnouncement(), /being sent right now/);
});

test('deletion routes to the endpoint matching where the item actually lives', () => {
  const { feature } = makeFeature();
  assert.equal(feature.deleteKindFor({ sourceType: 'recording' }), 'recording');
  assert.equal(feature.deleteKindFor({ sourceType: 'draft', rawStatus: 'pending' }), 'draft');
  assert.equal(feature.deleteKindFor({ sourceType: 'draft', rawStatus: 'blocked' }), 'draft');
  assert.equal(feature.deleteKindFor({ sourceType: 'draft', rawStatus: 'sent' }), 'history_entry');
});

test('a recording deletes through the recordings endpoint, with confirmation', async () => {
  const api = recordingApi({
    fetchRecordings: () => Promise.resolve({ ok: true, recordings: [{ id: 'rec-1', created_at: 1785000000, duration_seconds: 4 }] }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadRecordings();
  feature.selectItem('recording-rec-1');
  const pending = feature.handleDeleteItem();
  await answerNextConfirm(feature, true);
  await pending;
  assert.deepEqual(api.calls.find((c) => c.name === 'deleteLibraryRecording').args, ['rec-1', { confirm: true }]);
});

test('with no confirmation dialog present, a destructive call is refused rather than run', async () => {
  // A missing dialog must fail closed. Proceeding "because there was nothing
  // to confirm with" is the one failure mode a confirmation gate cannot have.
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api, elements: { liveRegion: { textContent: '' } } });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleDeleteItem(), false);
  assert.equal(api.names().includes('deleteLibraryDraft'), false);
});

// --- duplicate ---------------------------------------------------------------------

test('duplicate creates a new pending draft and says the original is unchanged', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  const created = await feature.handleDuplicate();
  assert.deepEqual(api.calls.find((c) => c.name === 'duplicateLibraryDraft').args, [7]);
  assert.equal(created.duplicated_from_id, 1);
  assert.match(feature.getLastAnnouncement(), /original is unchanged/);
});

test('duplicate is refused for a recording — there is no draft to copy', async () => {
  const api = recordingApi({
    fetchRecordings: () => Promise.resolve({ ok: true, recordings: [{ id: 'rec-1', created_at: 1785000000 }] }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadRecordings();
  feature.selectItem('recording-rec-1');
  assert.equal(await feature.handleDuplicate(), null);
  assert.equal(api.names().includes('duplicateLibraryDraft'), false);
});

// --- reopen ---------------------------------------------------------------------

test('reopening a SENT message forks first, so Talk can never rewrite history', async () => {
  const rendered = [];
  const navigated = [];
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7, status: 'sent' })], total: 1 }),
    fetchLibraryReopen: () => Promise.resolve({ ok: true, reopen: { source_id: 7, editable: true, requires_new_record: true } }),
  });
  const { feature } = makeFeature({
    api,
    hooks: {
      drafts: { renderDraft: (d) => rendered.push(d) },
      talkWorkspace: { refresh: () => Promise.resolve() },
      shell: { goTo: (id) => navigated.push(id) },
    },
  });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleReopen(), true);

  assert.ok(api.names().includes('commitLibraryReopenEdit'), 'sent history was handed to Talk unforked');
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].id, 3, 'Talk received the original record instead of the fork');
  assert.equal(rendered[0].reopened_from_id, 1, 'the fork carries its provenance');
  assert.deepEqual(navigated, ['talk']);
  assert.match(feature.getLastAnnouncement(), /original stays in your Library untouched/);
});

test('reopening a PENDING draft edits it in place — no spurious fork is created', async () => {
  const rendered = [];
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
    fetchLibraryReopen: () => Promise.resolve({ ok: true, reopen: { source_id: 7, editable: true, requires_new_record: false } }),
  });
  const { feature } = makeFeature({
    api,
    hooks: { drafts: { renderDraft: (d) => rendered.push(d) }, shell: { goTo() {} } },
  });
  await feature.loadPage();
  feature.selectItem('draft-7');
  await feature.handleReopen();
  assert.equal(api.names().includes('commitLibraryReopenEdit'), false, 'forked a draft that did not need forking');
  assert.equal(rendered[0].id, 7);
});

test('reopening a message that is mid-send is refused, and does not navigate away', async () => {
  const navigated = [];
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7, status: 'sending' })], total: 1 }),
    fetchLibraryReopen: () => Promise.resolve({ ok: true, reopen: { source_id: 7, editable: false, requires_new_record: false } }),
  });
  const { feature } = makeFeature({
    api,
    hooks: { drafts: { renderDraft() {} }, shell: { goTo: (id) => navigated.push(id) } },
  });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleReopen(), false);
  assert.deepEqual(navigated, [], 'navigated to Talk without loading anything into it');
  assert.match(feature.getLastAnnouncement(), /being sent right now/);
});

test('reopen with no draft editor available says so instead of navigating to an empty Talk', async () => {
  const navigated = [];
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api, hooks: { shell: { goTo: (id) => navigated.push(id) } } });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleReopen(), false);
  assert.deepEqual(navigated, []);
  assert.match(feature.getLastAnnouncement(), /could not reach the draft editor/);
});

test('reopen is refused for a raw recording, which points at Restore instead', async () => {
  const api = recordingApi({
    fetchRecordings: () => Promise.resolve({ ok: true, recordings: [{ id: 'rec-1', created_at: 1785000000 }] }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadRecordings();
  feature.selectItem('recording-rec-1');
  assert.equal(await feature.handleReopen(), false);
  assert.equal(api.names().includes('fetchLibraryReopen'), false);
  assert.match(feature.getLastAnnouncement(), /Restore/);
});

// --- resend ---------------------------------------------------------------------

test('resend routes through reopen -> review and reaches NO delivery call', async () => {
  const rendered = [];
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7, status: 'sent' })], total: 1 }),
    fetchLibraryReopen: () => Promise.resolve({ ok: true, reopen: { source_id: 7, editable: true, requires_new_record: true } }),
  });
  const { feature } = makeFeature({
    api,
    hooks: { drafts: { renderDraft: (d) => rendered.push(d) }, shell: { goTo() {} } },
  });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleResend(), true);

  assert.ok(api.names().includes('resendLibraryDraft'));
  assert.ok(api.names().includes('commitLibraryReopenEdit'));
  // The whole point of the contract's resend_plan: there is no branch that
  // sends. Nothing send-shaped may appear in the call log.
  assert.equal(api.names().some((n) => /send(?!Policy)/i.test(n) && n !== 'resendLibraryDraft'), false);
  assert.equal(rendered.length, 1);
});

test('resend on an in-flight message is refused with the backend\'s own reason', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7, status: 'sending' })], total: 1 }),
    resendLibraryDraft: () => Promise.resolve({ ok: true, resend: { allowed: false, reason: 'send_in_flight', next_action: 'reopen_for_review' } }),
  });
  const { feature } = makeFeature({ api, hooks: { drafts: { renderDraft() {} } } });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleResend(), false);
  assert.equal(api.names().includes('fetchLibraryReopen'), false);
  assert.match(feature.getLastAnnouncement(), /already being sent/);
});

test('a resend plan naming an action this build does not perform sends nothing', async () => {
  // Defensive read of the contract rather than an assumption about it: if
  // next_action ever changed, refusing is the safe failure, sending is not.
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
    resendLibraryDraft: () => Promise.resolve({ ok: true, resend: { allowed: true, reason: '', next_action: 'send_now' } }),
  });
  const { feature } = makeFeature({ api, hooks: { drafts: { renderDraft() {} } } });
  await feature.loadPage();
  feature.selectItem('draft-7');
  assert.equal(await feature.handleResend(), false);
  assert.equal(api.names().includes('fetchLibraryReopen'), false);
  assert.match(feature.getLastAnnouncement(), /Nothing was sent/);
});

// --- restore ---------------------------------------------------------------------

test('restoring a recording re-transcribes it and labels the result a raw transcript', async () => {
  const api = recordingApi({
    fetchRecordings: () => Promise.resolve({ ok: true, recordings: [{ id: 'rec-1', created_at: 1785000000, duration_seconds: 4 }] }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadRecordings();
  const created = await feature.handleRestore({ sourceType: 'recording', backendId: 'rec-1' });
  assert.deepEqual(api.calls.find((c) => c.name === 'restoreLibraryRecording').args, ['rec-1']);
  assert.equal(created.restored_from_recording_id, 'rec-1');
  // D-0020: the UI must say the restored draft is the raw transcript.
  assert.match(feature.getLastAnnouncement(), /raw transcript/);
});

test('restoring a recoverable DRAFT leaves the original in place and says so', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7, status: 'blocked' })], total: 1 }),
  });
  const { feature } = makeFeature({ api });
  await feature.loadPage();
  feature.selectItem('draft-7');
  await feature.handleRestore();
  assert.deepEqual(api.calls.find((c) => c.name === 'restoreLibraryDraft').args, [7]);
  assert.equal(api.names().includes('restoreLibraryRecording'), false);
  assert.match(feature.getLastAnnouncement(), /still in your Library/);
});

// --- clear scopes -------------------------------------------------------------------

test('each clear scope requires its OWN confirmation and calls only itself', async () => {
  for (const scope of CLEAR_SCOPES) {
    const api = recordingApi();
    const { feature } = makeFeature({ api });
    const pending = feature.handleClear(scope);
    await answerNextConfirm(feature, true);
    assert.equal(await pending, true);
    const clears = api.calls.filter((c) => c.name === 'clearLibrary');
    assert.equal(clears.length, 1, `${scope} issued ${clears.length} clear calls`);
    assert.deepEqual(clears[0].args, [scope, { confirm: true }]);
  }
});

test('cancelling a clear performs no clear call', async () => {
  const api = recordingApi();
  const { feature } = makeFeature({ api });
  const pending = feature.handleClear('all_conversation_data');
  await answerNextConfirm(feature, false);
  assert.equal(await pending, false);
  assert.equal(api.names().includes('clearLibrary'), false);
});

test('an unknown clear scope is refused before any network call', async () => {
  const api = recordingApi();
  const { feature } = makeFeature({ api });
  assert.equal(await feature.handleClear('everything_everywhere'), false);
  assert.equal(api.names().includes('clearLibrary'), false);
});

test('the clear dialog only quotes counts the client has actually observed', async () => {
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord()], total: 42 }),
    fetchRecordings: () => Promise.resolve({ ok: true, recordings: [{ id: 'r1', created_at: 1785000000 }] }),
  });
  const { feature } = makeFeature({ api });
  await feature.refresh();
  const pending = feature.handleClear('all_conversation_data');
  await Promise.resolve();
  const spec = feature.getPendingConfirmation();
  assert.deepEqual(spec.details, ['42 archived messages', '1 saved recording']);
  // Never the draft-queue count: the client has no honest number for it.
  assert.equal(spec.details.some((d) => /\bdrafts?\b/.test(d)), false);
  feature.answerConfirmation(false);
  await pending;
});

test('under an active filter the clear dialog drops the history count rather than misdescribing it', async () => {
  // `total` describes the FILTERED set. Quoting it as "what will be cleared"
  // would understate the damage by however much the filter hid.
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [], total: 3 }),
  });
  const { feature } = makeFeature({ api });
  await feature.applyFilters({ status: 'sent' });
  const pending = feature.handleClear('drafts_and_history');
  await Promise.resolve();
  assert.deepEqual(feature.getPendingConfirmation().details, []);
  feature.answerConfirmation(false);
  await pending;
});

// --- announcements --------------------------------------------------------------------

test('every async outcome reaches the aria-live region, not only the toast', async () => {
  const toasts = [];
  const elements = stubElements();
  const api = recordingApi({
    librarySearch: () => Promise.resolve({ ok: true, results: [draftRecord({ id: 7 })], total: 1 }),
  });
  const { feature } = makeFeature({ api, elements, hooks: { showToast: (m) => toasts.push(m) } });
  await feature.loadPage();
  feature.selectItem('draft-7');
  await feature.handlePinToggle();
  assert.ok(elements.liveRegion.textContent.length > 0, 'nothing was announced to assistive tech');
  assert.equal(elements.liveRegion.textContent, feature.getLastAnnouncement());
  assert.equal(toasts.length > 0, true, 'and the sighted user still gets the toast');
});

test('an identical repeat announcement is re-read rather than silently swallowed', async () => {
  const writes = [];
  const elements = stubElements();
  Object.defineProperty(elements.liveRegion, 'textContent', {
    get: () => writes[writes.length - 1] ?? '',
    set: (v) => writes.push(v),
  });
  const { feature } = makeFeature({ elements });
  feature.announce('Deleted.', 'silent');
  feature.announce('Deleted.', 'silent');
  // A live region whose text does not change is not re-announced, so the
  // clear-then-set pair is load-bearing: two real deletes are two events.
  assert.deepEqual(writes, ['', 'Deleted.', '', 'Deleted.']);
});
