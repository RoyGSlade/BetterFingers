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
  deriveLibraryItemFromRecording,
  LIBRARY_ELEMENT_IDS,
  collectLibraryElements,
  createLibraryWorkspaceFeature,
} from '../src/renderer/features/libraryWorkspace.js';

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
  { id: 'a', status: 'sent', pinned: true, persona: 'Natural', destination: 'Discord', preview: 'I should be there around six' },
  { id: 'b', status: 'sent', pinned: false, persona: 'Professional', destination: 'Slack', preview: 'Can we push the meeting back?' },
  { id: 'c', status: 'recoverable', pinned: false, persona: 'Natural', destination: 'Discord', preview: 'I wasn’t trying to be rude' },
  { id: 'd', status: 'unsent', pinned: false, persona: 'Creative', destination: 'Slack', preview: 'I have a few ideas to share' },
];

test('itemMatchesFilters: chip=all with no query/persona/destination matches everything', () => {
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

test('itemMatchesFilters: persona/destination filters narrow further', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', persona: 'Natural' }).map((i) => i.id), ['a', 'c']);
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', destination: 'Slack' }).map((i) => i.id), ['b', 'd']);
});

test('itemMatchesFilters: query does a case-insensitive substring match across preview/persona/destination', () => {
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', query: 'MEETING' }).map((i) => i.id), ['b']);
  assert.deepEqual(filterItems(SAMPLE_ITEMS, { chip: 'all', query: 'discord' }).map((i) => i.id), ['a', 'c']);
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
  const feature = createLibraryWorkspaceFeature({});
  assert.doesNotThrow(() => feature.handleReopenClick());
  assert.doesNotThrow(() => feature.handleDuplicateClick());
  assert.doesNotThrow(() => feature.handlePinClick());
  assert.doesNotThrow(() => feature.handleRestoreClick());
  assert.doesNotThrow(() => feature.handleResendClick());
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
