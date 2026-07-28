// libraryWorkspace.js — thin wiring adapter for the Library workspace (Phase 3
// of the Signal Desk redesign, docs/ui/SIGNAL_DESK_SPEC.md section 5).
//
// Like talkWorkspace.js (Phase 2), this module does NOT reimplement draft/
// recording persistence -- it binds the new Library markup (signal-desk.css /
// signal-desk-preview.html) to the EXISTING data sources:
//   - features/drafts.js (draft state: fetchDrafts/searchHistory, plus the
//     accept/decline/retry/edit/rewrite/copy/send/read action set, reused via
//     a live drafts-feature instance passed in as `hooks.drafts`, exactly the
//     way talkWorkspace.js reuses it for Listen/Send)
//   - api/backend.js's fetchRecordings/retranscribeRecording/deleteRecording/
//     clearRecordings, imported directly here (the same pattern drafts.js
//     itself uses -- feature modules call backend.js directly for their own
//     data, and only use `hooks` for CROSS-feature calls)
//
// index.html/main.js are NOT touched this phase -- see the phase plan.
//
// ---------------------------------------------------------------------------
// INVENTORY PRESERVATION MAP (docs/ui/CURRENT_UI_INVENTORY.md) -- for the
// director's no-orphan gate. Every item below is required to "land somewhere"
// per SPEC section 8; this column says where it lands in Library and whether
// it's wired for real this phase or stubbed pending main.js composition.
//
//   Inventory item                              Lands in Library as...                         Status this phase
//   -------------------------------------------  -----------------------------------------------  -------------------------------
//   6.3 draft history (#draftHistoryListEl data)  the day-grouped timeline (renderTimeline())        WIRED (fetchDrafts, via hooks.drafts.refreshDrafts() or a direct fetchDrafts() fallback)
//   6.3 #historySearchInput -> searchHistory()    #sdLibrarySearchInput -> handleSearchInput()        WIRED (calls searchHistory()/fetchDrafts() directly, renders into the NEW timeline -- NOT the old #draftHistoryList, see note below)
//   6.3 Accept/Decline/Retry/Edit/Rewrite/Copy/   SELECTED ITEM panel's Reopen action:                WIRED for Reopen+Listen (delegates to hooks.drafts.renderDraft()/runDraftTts()
//       Send/Read (the whole Review-Draft set)    loads the selected item back into hooks.drafts      so the EXISTING review surface -- wherever main.js mounts it -- picks it up)
//                                                  (renderDraft), Listen plays it (runDraftTts).        Edit/Rewrite/Accept/Decline/Send/Copy/Read remain on the existing Review-
//                                                                                                       Draft panel itself (SPEC doesn't move that editor surface into Library;
//                                                                                                       it stays reachable via Reopen). See hooks.drafts contract below.
//   9 Recovery "saved recordings" (#recordingsList,  merged into the SAME timeline as recording-        WIRED: fetchRecordings() populates timeline rows with sourceType:'recording';
//     retranscribe/discard/clear)                    sourced rows (status derived as 'unsent' until    Reopen on a recording row calls retranscribeRecording(); Delete on a
//                                                     retranscribed); clearRecordings() exposed as an   recording row calls deleteRecording(); clearRecordings()/clearDraftHistory()
//                                                     adapter method (handleClearRecordings())          are exposed as adapter methods but have no bound button in this phase's
//                                                                                                       mockup (mockup 02 shows no "clear all" control) -- flagged for the director.
//   6.4/6.6/6.7 the THREE Message Rescue surfaces  NOT collapsed into one. See "Message Rescue          TODO(phase-integration): SPEC's mockups don't show Message Rescue UI
//   (draft-bound live / static preview / text        surfaces" note below.                             inside Library at all -- director needs to decide where each of the
//   playground) -- must stay distinct                                                                  three lands (dashboard vs a Library sub-panel vs Utilities) before
//                                                                                                       this adapter can bind them. Not fabricated here.
//   review-overlay's restore/resend semantics      SELECTED ITEM panel's RESTORE / RESEND buttons      STUBBED (hooks.onRestoreRequested / hooks.onResendRequested) -- SPEC 5
//                                                                                                       explicitly calls these out as needing main.js composition (which
//                                                                                                       backing action -- retryDraft? sendDraft? a real restore/resend route
//                                                                                                       that doesn't exist yet? -- is a director decision, not guessable here)
//   Pin (no backend field exists for it yet)       header pin toggle + ACTIONS grid "Pin" button        WIRED as LOCAL-ONLY state (a Set of pinned ids) -- honestly partial:
//                                                                                                       persists only for this session, not the backend, since no pin/
//                                                                                                       favorite field exists on drafts or recordings yet.
//   Duplicate (no backend field/endpoint exists)   ACTIONS grid "Duplicate" button                      STUBBED (hooks.onDuplicateRequested)
//   Delete (no per-draft delete endpoint exists;    ACTIONS grid "Delete" button                        WIRED for recording-sourced rows (deleteRecording()); STUBBED
//   only clearDrafts() wipes ALL history)                                                               (hooks.onDeleteRequested) for draft-sourced rows -- no safe 1:1
//                                                                                                       existing endpoint to call without risking the wrong destructive op.
//
// Message Rescue surfaces note: SPEC section 5's mockup and prose ("This
// whole workspace = the existing draft history + recordings + Message
// Rescue/recovery, unified") name Message Rescue as something Library must
// preserve, but mockup 02 has no dedicated Message Rescue region drawn in it
// -- there is no "capture context / rescue this message / variant picker" UI
// in the pixels. Rather than invent placement (and risk colliding with
// whatever the director actually wants for #draftRescuePanel / the flag-
// gated #messageRescuePanel / #textPlaygroundSection), this phase leaves all
// three untouched and unwired from Library. They still exist wherever
// main.js currently mounts them; nothing is deleted. Flagged for the
// director as an open gap, not silently dropped.
//
// ---------------------------------------------------------------------------
// hooks contract (all optional; every call is optional-chained so a missing
// hook is a safe no-op, never a throw):
//
//   hooks.drafts                The object createDraftsFeature({...}) returns
//                               in main.js (same live instance talkWorkspace.js
//                               uses) -- renderDraft, getDraftHistory,
//                               refreshDrafts, runDraftTts, handleSendClick,
//                               handleAcceptClick, handleDeclineClick,
//                               handleRetryClick, ... Used here for:
//                                 - Reopen  -> hooks.drafts.renderDraft(draft)
//                                 - Listen  -> renderDraft(draft) then runDraftTts(false)
//                               TODO(phase-integration): once main.js decides
//                               where the Review-Draft editor itself lives in
//                               Signal Desk, Reopen's "load it back" behavior
//                               should point AT that surface.
//   hooks.showToast(msg, tone, duration)   Optional user feedback (same shared
//                               helper signature as ui.showToast elsewhere).
//   hooks.writeClipboardText(text)         Defaults to
//                               window.betterFingers?.writeClipboardText.
//   hooks.onDeleteRequested(item)          TODO(phase-integration): draft-
//                               sourced rows have no safe existing delete-by-id
//                               endpoint (see table above).
//   hooks.onDuplicateRequested(item)       TODO(phase-integration): no
//                               existing duplicate concept for a draft/recording.
//   hooks.onRestoreRequested(item)         TODO(phase-integration): SPEC 5's
//                               "Restore" button -- director needs to decide
//                               the backing action (retryDraft? a real
//                               recovery route?).
//   hooks.onResendRequested(item)          TODO(phase-integration): SPEC 5's
//                               "Resend" button -- closest existing analog is
//                               hooks.drafts.handleSendClick() after
//                               renderDraft(item), but SPEC explicitly flags
//                               restore/resend routing as a main.js
//                               composition decision, so this stays stubbed
//                               rather than guessing.
//
// To mount for real (a later phase): pass `elements` from
// collectLibraryElements() (or an equivalent object) plus `hooks.drafts` =
// the live drafts feature instance, call `init()`.
// ---------------------------------------------------------------------------

import {
  fetchDrafts,
  searchHistory,
  fetchRecordings,
  retranscribeRecording,
  deleteRecording,
  clearRecordings,
} from '../api/backend.js';

// Reuse the shared confidence-band/color logic from Talk (SPEC 2's
// confidence-color rule is universal, not Talk-specific) rather than
// re-deriving it.
import { formatConfidencePercent, mapConfidenceBand, confidenceBandToCssVar } from './talkWorkspace.js';

// --- Pure helpers (no DOM) ---------------------------------------------------

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** 'Today' / 'Yesterday' / 'Jul 20' for a timestamp, relative to `now` (defaults to `new Date()`). Never throws on a bad timestamp -- returns 'Unknown'. */
// --- Inventory -> Library placement map (machine-readable parity gate) ------
//
// Same contract as talkWorkspace.js's TALK_PLACEMENT_MAP and utilities'
// INVENTORY_PLACEMENT_MAP: every entry names a section, describes a control,
// and any `wired: false` explains itself. Seeded before the work so it measures
// the gap rather than certifying it.
//
// Keys cover the history / recovery / recordings surfaces Library replaces
// (CURRENT_UI_INVENTORY.md §6.3 draft history, plus the recovery bin).
export const LIBRARY_SECTIONS = ['search', 'timeline', 'selected', 'recovery'];

export function isValidLibrarySection(id) {
  return LIBRARY_SECTIONS.includes(id);
}

export const LIBRARY_PLACEMENT_MAP = {
  'search.fullText': { section: 'search', control: 'Full-text history search', wired: true },
  'search.filterChips': { section: 'search', control: 'All / Pinned / Unsent / Recoverable / Sent chips', wired: true },
  'search.personaFilter': { section: 'search', control: 'Persona filter dropdown', wired: false, note: 'Chip renders but opens no menu: no persona-filter data source is wired yet' },
  'search.contactFilter': { section: 'search', control: 'Contact filter dropdown', wired: true },
  'search.dateFilter': { section: 'search', control: 'Date filter dropdown', wired: false, note: 'Chip renders but opens no menu; GET /history/search takes no date range yet' },
  'search.clearHistory': { section: 'search', control: 'Clear History', wired: false, note: 'DELETE /drafts exists (clearDrafts) but no Library control is bound to it' },

  'timeline.dayGrouping': { section: 'timeline', control: 'Today / Yesterday day grouping', wired: true },
  'timeline.cards': { section: 'timeline', control: 'Message cards (raw -> refined -> status)', wired: true },
  'timeline.statusGlyphs': { section: 'timeline', control: 'Per-item status glyph (sent/failed/draft/pinned)', wired: true },
  'timeline.confidence': { section: 'timeline', control: 'Per-item confidence bar', wired: true },
  'timeline.duration': { section: 'timeline', control: 'Per-item recording duration', wired: true },
  'timeline.waveformThumb': { section: 'timeline', control: 'Per-item waveform thumbnail', wired: false, note: 'Not drawable from available data: items carry aggregate rms/peak only, never a per-time amplitude series, so any thumbnail would be decoration implying it depicts that specific recording. Needs the backend to persist an amplitude envelope per draft' },
  'timeline.loadMore': { section: 'timeline', control: 'Load more / pagination', wired: true },

  'selected.detail': { section: 'selected', control: 'Selected item detail panel', wired: true },
  'selected.playAudio': { section: 'selected', control: 'Replay captured audio', wired: true },
  'selected.reopen': { section: 'selected', control: 'Reopen in Talk', wired: false, note: 'Falls back to a "not wired up yet" toast: needs the SPEC 6 draft editor to reopen into' },
  'selected.resend': { section: 'selected', control: 'Resend', wired: false, note: 'hooks.onResendRequested is a documented stub; no resend endpoint exists' },
  'selected.restore': { section: 'selected', control: 'Restore from recovery', wired: false, note: 'hooks.onRestoreRequested is a documented stub' },
  'selected.duplicate': { section: 'selected', control: 'Duplicate', wired: false, note: 'hooks.onDuplicateRequested is a documented stub; no duplicate concept exists for a draft' },
  'selected.delete': { section: 'selected', control: 'Delete item', wired: false, note: 'hooks.onDeleteRequested is a documented stub; no per-draft delete endpoint exists (only DELETE /drafts for all)' },
  'selected.pin': { section: 'selected', control: 'Pin / unpin', wired: false, note: 'Pinned state renders but nothing sets it: no pin endpoint or local store' },

  'recovery.recordings': { section: 'recovery', control: 'Retained recordings list', wired: false, note: 'Owned by Utilities (diagnostics.recordings) today; SPEC 5 places recovery in Library -- ownership needs a director call before wiring' },
  'recovery.retranscribe': { section: 'recovery', control: 'Retranscribe a retained recording', wired: false, note: 'Same ownership question as recovery.recordings' },
};

export function dayLabelFor(timestamp, now = new Date()) {
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return 'Unknown';
  const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  return `${MONTH_ABBR[d.getMonth()]} ${d.getDate()}`;
}

/** 12-hour clock time, e.g. '10:32 AM'. Empty string on a bad timestamp. */
export function formatClockTime(timestamp) {
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return '';
  let hours = d.getHours();
  const minutes = d.getMinutes();
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${hours}:${String(minutes).padStart(2, '0')} ${ampm}`;
}

/** seconds -> 'm:ss' (e.g. 6 -> '0:06'). Negative/NaN input clamps to 0. */
export function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.round(Number(totalSeconds) || 0));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

/**
 * Groups a list of `{ timestamp, ... }` items into day buckets, preserving
 * the order days are first encountered (callers should pass items already
 * sorted most-recent-first so 'Today' comes before 'Yesterday'). Pure --
 * `now` is injectable so tests are deterministic.
 * @returns {{label: string, items: object[]}[]}
 */
export function groupByDay(items, now = new Date()) {
  const buckets = new Map();
  const order = [];
  for (const item of items || []) {
    const label = dayLabelFor(item?.timestamp, now);
    if (!buckets.has(label)) {
      buckets.set(label, []);
      order.push(label);
    }
    buckets.get(label).push(item);
  }
  return order.map((label) => ({ label, items: buckets.get(label) }));
}

/**
 * Library's status vocabulary is simpler than drafts.js's raw status field:
 * 'sent' | 'failed' | 'recoverable' | 'unsent'. Derives it from a
 * drafts.js-shaped draft (status/send_result) per the mapping documented in
 * this file's header table.
 */
export function deriveLibraryStatusFromDraft(draft) {
  if (!draft) return 'unsent';
  if (draft.send_result) {
    return draft.send_result.ok === false ? 'failed' : 'sent';
  }
  if (draft.status === 'blocked' || draft.status === 'error') {
    return 'recoverable';
  }
  return 'unsent';
}

/**
 * Gutter status glyph key ('pin' | 'sent' | 'warn' | 'draft'). Pinned always
 * wins (matches the mockup: a pinned-but-sent item still shows the pin, not
 * the paper-plane).
 */
export function statusToGlyph({ status, pinned } = {}) {
  if (pinned) return 'pin';
  if (status === 'sent') return 'sent';
  if (status === 'failed' || status === 'recoverable') return 'warn';
  return 'draft';
}

const GLYPH_COLOR_VAR = {
  pin: 'var(--sd-amber)',
  sent: 'var(--sd-blue-light)',
  warn: 'var(--sd-amber)',
  draft: 'var(--sd-text-muted)',
};

/** glyph key -> the signal-desk.css var() string for its color. */
export function glyphColorVar(glyph) {
  return GLYPH_COLOR_VAR[glyph] || GLYPH_COLOR_VAR.draft;
}

const PIPELINE_STATUS_LABEL = {
  sent: 'Sent',
  failed: 'Recoverable',
  recoverable: 'Recoverable',
  unsent: 'Unsent',
  draft: 'Unsent',
};

/** status -> the third pipeline-stage label ('Sent' | 'Recoverable' | 'Unsent'). */
export function pipelineStatusLabel(status) {
  return PIPELINE_STATUS_LABEL[status] || 'Unsent';
}

/**
 * The timestamp a "Sent" status line/card should quote: the send-completion
 * time (item.sentAtTimestamp) when the item is actually sent and that time
 * is known, else the capture timestamp. Capture and send-completion times
 * commonly differ by a minute or so (see the mockup: captured 10:32 AM,
 * "Sent • Today, 10:33 AM") -- this keeps that distinction instead of
 * quoting the capture time for both.
 */
export function resolvedStatusTimestamp(item) {
  if (item?.status === 'sent' && item?.sentAtTimestamp) return item.sentAtTimestamp;
  return item?.timestamp;
}

/**
 * Bottom-right status line text, matching SPEC 5's three exact variants
 * ('✓ Sent • Today, 10:33 AM' / '● Failed to send ●' / '● Unsent • Draft').
 * Icons/bullets are added at render time, not baked into this string.
 */
export function statusLineText({ status, dayLabel, timeLabel } = {}) {
  if (status === 'sent') {
    return `Sent • ${dayLabel || ''}, ${timeLabel || ''}`.replace(/ • ,\s*/, ' • ');
  }
  if (status === 'failed' || status === 'recoverable') {
    return 'Failed to send';
  }
  return 'Unsent • Draft';
}

/**
 * SPEC 2's confidence-color rule, reused from talkWorkspace.js: >=85 always
 * high(green); 70-84 is high UNLESS the item is still unsent/draft (then
 * 'draft'/blue); 60-69 mid(amber); <60 low(red). Library's status vocabulary
 * differs from Talk's ('unsent'/'draft' vs 'pending'), so this just adapts
 * the vocabulary before delegating to the shared function.
 */
export function mapLibraryConfidenceBand(score, status) {
  const isDraftLike = status === 'unsent' || status === 'draft' || !status;
  return mapConfidenceBand(score, isDraftLike ? 'pending' : 'sent');
}

/**
 * True if `item` matches the current filter/search state.
 * @param {object} item { status, pinned, persona, contact, preview }
 * @param {object} filters { chip: 'all'|'pinned'|'unsent'|'recoverable'|'sent', persona, contact, query }
 */
export function itemMatchesFilters(item, filters = {}) {
  const { chip = 'all', persona = null, contact = null, query = '' } = filters;
  if (chip && chip !== 'all') {
    if (chip === 'pinned' && !item?.pinned) return false;
    if (chip === 'unsent' && !(item?.status === 'unsent' || item?.status === 'draft')) return false;
    if (chip === 'recoverable' && !(item?.status === 'recoverable' || item?.status === 'failed')) return false;
    if (chip === 'sent' && item?.status !== 'sent') return false;
  }
  if (persona && item?.persona !== persona) return false;
  if (contact && item?.contact !== contact) return false;
  const q = String(query || '').trim().toLowerCase();
  if (q) {
    const haystack = `${item?.preview || ''} ${item?.persona || ''} ${item?.contact || ''}`.toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  return true;
}

/** Filters a full item list down to what should currently render. */
export function filterItems(items, filters = {}) {
  return (items || []).filter((item) => itemMatchesFilters(item, filters));
}

/**
 * Maps a drafts.js-shaped draft object into the plain Library item view
 * model this module renders. No DOM involved. `raw` keeps the original
 * draft around so action handlers (Reopen/Listen) can hand it straight back
 * to hooks.drafts.
 *
 * `contactsById` resolves a draft's contact_id to a display name. Passed in
 * rather than fetched here so this stays DOM-free and synchronous, and so a
 * draft written before contacts existed (or one whose contact was since
 * deleted) simply shows none.
 */
export function contactNameFor(contactId, contactsById) {
  if (!contactId || !contactsById) return null;
  const contact = typeof contactsById.get === 'function'
    ? contactsById.get(contactId)
    : contactsById[contactId];
  return contact?.name || null;
}

export function deriveLibraryItemFromDraft(draft, contactsById = null) {
  const status = deriveLibraryStatusFromDraft(draft);
  const score = draft?.confidence?.score;
  const confidencePct = formatConfidencePercent(score);
  return {
    id: `draft-${draft?.id}`,
    sourceType: 'draft',
    preview: draft?.final_text || draft?.raw_text || '(empty transcript)',
    rawText: draft?.raw_text || '',
    refinedText: draft?.final_text || '',
    status,
    pinned: false,
    persona: draft?.persona_name || draft?.persona?.name || null,
    // Was `draft.destination_name || draft.destination?.name` -- neither field
    // has ever existed, so this was always null and the filter above it always
    // matched everything. contact_id is real (Stage 11); the NAME needs the
    // contact list, which the caller supplies, so an unresolved id shows as no
    // contact rather than as a raw id nobody can read.
    contactId: draft?.contact_id || null,
    contact: contactNameFor(draft?.contact_id, contactsById),
    confidencePct,
    confidenceBand: confidencePct === null ? null : mapLibraryConfidenceBand(score, status),
    durationSeconds: Number(draft?.metadata?.duration_seconds || 0),
    timestamp: draft?.created_at || draft?.updated_at || Date.now(),
    sentAtTimestamp: draft?.send_result?.sent_at || null,
    raw: draft,
  };
}

/** Maps a fetchRecordings()-shaped recording row into the same Library item view model. */
export function deriveLibraryItemFromRecording(recording) {
  return {
    id: `recording-${recording?.id}`,
    sourceType: 'recording',
    preview: recording?.raw_text || recording?.filename || `Recording #${recording?.id ?? ''}`,
    rawText: recording?.raw_text || '',
    refinedText: '',
    status: 'unsent',
    pinned: false,
    persona: null,
    // A recording has not been through cleanup yet, so no contact was applied.
    contactId: null,
    contact: null,
    confidencePct: null,
    confidenceBand: null,
    durationSeconds: Number(recording?.duration_seconds || 0),
    timestamp: recording?.created_at || Date.now(),
    sentAtTimestamp: null,
    raw: recording,
  };
}

// --- Reusable element lookup -------------------------------------------------

export const LIBRARY_ELEMENT_IDS = {
  searchInput: 'sdLibrarySearchInput',
  filterButton: 'sdLibraryFilterButton',
  filterChipAll: 'sdFilterAll',
  filterChipPinned: 'sdFilterPinned',
  filterChipUnsent: 'sdFilterUnsent',
  filterChipRecoverable: 'sdFilterRecoverable',
  filterChipSent: 'sdFilterSent',
  timelineContainer: 'sdLibraryTimeline',
  itemsCount: 'sdLibraryItemsCount',
  loadMoreButton: 'sdLibraryLoadMoreButton',

  selectedPinButton: 'sdSelectedItemPinButton',
  selectedRawBox: 'sdSelectedRawTranscript',
  selectedRawText: 'sdSelectedRawTranscriptText',
  selectedRawMeta: 'sdSelectedRawMeta',
  selectedRefinedBox: 'sdSelectedRefinedMessage',
  selectedRefinedText: 'sdSelectedRefinedMessageText',
  selectedRefinedMeta: 'sdSelectedRefinedMeta',
  selectedStatusCard: 'sdSelectedStatusCard',
  selectedStatusTitle: 'sdSelectedStatusTitle',
  selectedStatusTime: 'sdSelectedStatusTime',
  selectedPersonaName: 'sdSelectedPersonaName',
  selectedContactName: 'sdSelectedContactName',
  selectedAudioDuration: 'sdSelectedAudioDuration',
  selectedAudioPlayButton: 'sdSelectedAudioPlayButton',
  reopenButton: 'sdSelectedReopenButton',
  listenButton: 'sdSelectedListenButton',
  duplicateButton: 'sdSelectedDuplicateButton',
  pinActionButton: 'sdSelectedPinActionButton',
  deleteButton: 'sdSelectedDeleteButton',
  restoreButton: 'sdSelectedRestoreButton',
  resendButton: 'sdSelectedResendButton',
};

/** Looks up every LIBRARY_ELEMENT_IDS entry by id from `root` (defaults to `document`). Missing ids resolve to null, never throw. */
export function collectLibraryElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const els = {};
  for (const [key, id] of Object.entries(LIBRARY_ELEMENT_IDS)) {
    els[key] = doc && typeof doc.getElementById === 'function' ? doc.getElementById(id) || null : null;
  }
  return els;
}

// --- DOM-wiring feature -------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} deps.elements Library workspace DOM refs -- see
 *   LIBRARY_ELEMENT_IDS (use collectLibraryElements() for the common case).
 *   Every access is optional-chained.
 * @param {object} deps.hooks See the file-header contract above.
 */
export function createLibraryWorkspaceFeature({ elements, hooks } = {}) {
  const els = elements || {};
  const hks = hooks || {};

  let items = [];
  let filters = { chip: 'all', persona: null, contact: null, query: '' };
  let selectedId = null;
  const pinnedIds = new Set();
  let searchTimer = null;

  function writeClipboard(text) {
    const fn = hks.writeClipboardText || (typeof window !== 'undefined' ? window.betterFingers?.writeClipboardText : null);
    return fn ? fn(text) : Promise.resolve();
  }

  function withPinState(item) {
    return { ...item, pinned: pinnedIds.has(item.id) };
  }

  function getVisibleItems() {
    return filterItems(items.map(withPinState), filters);
  }

  function getSelectedItem() {
    return items.map(withPinState).find((item) => item.id === selectedId) || null;
  }

  /**
   * Sets the item list directly (no network call) and re-renders. Meant for
   * tests, storybook-style demos, and signal-desk-preview.html's QA mount --
   * `refresh()` is the real, network-backed way to populate the timeline.
   * Any item carrying `pinned: true` seeds the local pinnedIds set once
   * (see the file-header note: pin has no backend field yet, so this is the
   * only persistence a "pinned" item gets).
   */
  function setItems(newItems) {
    items = Array.isArray(newItems) ? newItems : [];
    items.forEach((item) => {
      if (item?.pinned && item?.id) pinnedIds.add(item.id);
    });
    if (!selectedId && items.length) {
      selectedId = withPinState(items[0]).id;
    }
    renderAll();
    return items;
  }

  // --- data loading -----------------------------------------------------------

  /**
   * Loads drafts (+ recordings, unified per SPEC 5) into the timeline. Prefers
   * hooks.drafts.refreshDrafts() (the same live drafts-feature instance Talk
   * uses, so its side-effect of also refreshing the OLD draft-history list
   * elsewhere in the app stays consistent) and falls back to calling
   * fetchDrafts() directly if no drafts hook was supplied (e.g. this preview
   * page, or a unit test).
   */
  async function refresh() {
    let draftList = [];
    try {
      draftList = hks.drafts?.refreshDrafts
        ? await hks.drafts.refreshDrafts()
        : (await fetchDrafts())?.drafts || [];
    } catch (error) {
      hks.showToast?.(`Failed to load drafts: ${error.message}`, 'danger');
    }

    let recordingList = [];
    try {
      recordingList = (await fetchRecordings())?.recordings || [];
    } catch {
      // Recordings are a bonus surface this phase -- a failure here shouldn't
      // block the draft timeline from rendering.
    }

    items = [
      ...(draftList || []).map(deriveLibraryItemFromDraft),
      ...(recordingList || []).map(deriveLibraryItemFromRecording),
    ].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    if (!selectedId && items.length) {
      selectedId = withPinState(items[0]).id;
    }

    renderAll();
    return items;
  }

  // --- search + filters ---------------------------------------------------------

  function handleSearchInput(query) {
    filters = { ...filters, query: String(query || '') };
    const q = filters.query.trim();
    if (searchTimer) clearTimeout(searchTimer);
    if (!q) {
      renderAll();
      return;
    }
    searchTimer = setTimeout(async () => {
      try {
        const payload = await searchHistory(q, 50);
        const results = (payload?.results || []).map(deriveLibraryItemFromDraft);
        items = results;
        renderAll();
      } catch (error) {
        hks.showToast?.(`Search failed: ${error.message}`, 'danger');
      }
    }, 250);
  }

  function setChipFilter(chip) {
    filters = { ...filters, chip };
    renderAll();
  }

  function bindFilterChips() {
    const chipMap = [
      [els.filterChipAll, 'all'],
      [els.filterChipPinned, 'pinned'],
      [els.filterChipUnsent, 'unsent'],
      [els.filterChipRecoverable, 'recoverable'],
      [els.filterChipSent, 'sent'],
    ];
    chipMap.forEach(([btn, chip]) => {
      btn?.addEventListener?.('click', () => setChipFilter(chip));
    });
    els.searchInput?.addEventListener?.('input', (event) => handleSearchInput(event.target?.value));
  }

  // --- rendering: timeline ------------------------------------------------------

  function renderTimeline() {
    const container = els.timelineContainer;
    if (!container || typeof container.replaceChildren !== 'function') return;

    const visible = getVisibleItems();
    const groups = groupByDay(visible);
    container.replaceChildren();

    if (!groups.length) {
      const empty = document.createElement('p');
      empty.className = 'sd-timeline__empty';
      empty.style.color = 'var(--sd-text-muted)';
      empty.style.fontSize = 'var(--sd-font-body)';
      empty.textContent = items.length ? 'No items match the current filters.' : 'No messages yet.';
      container.append(empty);
    }

    for (const group of groups) {
      const dayEl = document.createElement('div');
      dayEl.className = 'sd-timeline__day';

      const label = document.createElement('div');
      label.className = 'sd-timeline__day-label';
      label.textContent = group.label;
      dayEl.append(label);

      const rows = document.createElement('div');
      rows.className = 'sd-timeline__rows';

      group.items.forEach((item) => {
        rows.append(buildTimelineRow(item));
      });

      dayEl.append(rows);
      container.append(dayEl);
    }

    if (els.itemsCount) {
      els.itemsCount.textContent = `1–${visible.length} of ${visible.length} items`;
    }
  }

  function buildTimelineRow(item) {
    const glyph = statusToGlyph(item);
    // The gutter's time/day always reflect capture (when the row sits in the
    // timeline is "when it happened"); the status line below can quote a
    // later send-completion time -- see resolvedStatusTimestamp().
    const dayLabel = dayLabelFor(item.timestamp);
    const timeLabel = formatClockTime(item.timestamp);
    const statusTimestamp = resolvedStatusTimestamp(item);
    const statusDayLabel = dayLabelFor(statusTimestamp);
    const statusTimeLabel = formatClockTime(statusTimestamp);

    const row = document.createElement('div');
    row.className = 'sd-timeline__row';

    const gutter = document.createElement('div');
    gutter.className = 'sd-timeline__gutter';
    const timeEl = document.createElement('span');
    timeEl.className = 'sd-timeline__time';
    timeEl.textContent = timeLabel;
    const glyphEl = document.createElement('span');
    glyphEl.className = `sd-timeline__glyph sd-timeline__glyph--${glyph}`;
    glyphEl.setAttribute('aria-hidden', 'true');
    gutter.append(timeEl, glyphEl);

    const card = document.createElement('button');
    card.type = 'button';
    card.className = `sd-message-card${item.id === selectedId ? ' is-selected' : ''}`;
    card.dataset.itemId = item.id;

    const main = document.createElement('div');
    main.className = 'sd-message-card__main';
    const title = document.createElement('p');
    title.className = 'sd-message-card__title';
    title.textContent = item.preview;
    const pipeline = document.createElement('div');
    pipeline.className = 'sd-message-card__pipeline';
    pipeline.dataset.status = item.status;
    pipeline.innerHTML = `<span class="sd-message-card__pipeline-stage">Raw</span> → <span class="sd-message-card__pipeline-stage">Refined</span> → <span class="sd-message-card__pipeline-status">${pipelineStatusLabel(item.status)}</span>`;
    main.append(title, pipeline);

    if (item.persona || item.contact) {
      const chips = document.createElement('div');
      chips.className = 'sd-message-card__chips';
      if (item.persona) {
        const personaChip = document.createElement('span');
        personaChip.className = 'sd-chip sd-chip--persona';
        personaChip.textContent = item.persona;
        chips.append(personaChip);
      }
      if (item.contact) {
        const destChip = document.createElement('span');
        destChip.className = 'sd-chip sd-chip--contact';
        destChip.textContent = item.contact;
        chips.append(destChip);
      }
      main.append(chips);
    }

    const meta = document.createElement('div');
    meta.className = 'sd-message-card__meta';
    // --sd-confidence-color is set on `meta` (the shared ancestor of both the
    // confidence readout AND the waveform) rather than on the confidence
    // wrapper alone -- custom properties only inherit to descendants, and
    // the waveform is a sibling of the confidence wrapper, not its child.
    if (item.confidencePct !== null) {
      meta.style.setProperty('--sd-confidence-color', confidenceBandToCssVar(item.confidenceBand));
      const confWrap = document.createElement('div');
      confWrap.className = 'sd-message-card__confidence';
      confWrap.innerHTML = `<span class="sd-message-card__confidence-label">Confidence</span><span class="sd-message-card__confidence-value">${item.confidencePct}%</span><span class="sd-confidence-bar"><span class="sd-confidence-bar__fill" style="width:${item.confidencePct}%"></span></span>`;
      meta.append(confWrap);
    }
    // Duration was in the static markup and the mockup but never emitted here,
    // so it vanished the moment live data rendered. It is real data
    // (metadata.duration_seconds) and it is the main thing that distinguishes
    // one card from another at a glance.
    //
    // The mockup pairs it with a waveform thumbnail. That is NOT drawn: the
    // item model carries aggregate rms/peak only, never a per-time amplitude
    // series, so any squiggle here would be decoration implying it depicts
    // this specific recording. See LIBRARY_PLACEMENT_MAP timeline.waveformThumb.
    if (item.durationSeconds > 0) {
      const duration = document.createElement('span');
      duration.className = 'sd-message-card__duration';
      duration.textContent = formatDuration(item.durationSeconds);
      meta.append(duration);
    }

    const statusLine = document.createElement('div');
    statusLine.className = `sd-message-card__status sd-message-card__status--${item.status === 'sent' ? 'sent' : item.status === 'failed' || item.status === 'recoverable' ? 'failed' : 'draft'}`;
    statusLine.textContent = statusLineText({ status: item.status, dayLabel: statusDayLabel, timeLabel: statusTimeLabel });
    meta.append(statusLine);

    card.append(main, meta);
    card.addEventListener('click', () => selectItem(item.id));

    row.append(gutter, card);
    return row;
  }

  // --- rendering: SELECTED ITEM context panel ------------------------------------

  function renderSelectedItem() {
    const item = getSelectedItem();
    if (!item) return;

    if (els.selectedPinButton) {
      els.selectedPinButton.setAttribute('aria-pressed', String(Boolean(item.pinned)));
    }
    if (els.pinActionButton) {
      els.pinActionButton.setAttribute('aria-pressed', String(Boolean(item.pinned)));
    }

    if (els.selectedRawText) els.selectedRawText.textContent = item.rawText || '(empty transcript)';
    if (els.selectedRawMeta) {
      els.selectedRawMeta.textContent = `${formatDuration(item.durationSeconds)} · ${dayLabelFor(item.timestamp)}, ${formatClockTime(item.timestamp)}`;
    }

    if (els.selectedRefinedText) els.selectedRefinedText.textContent = item.refinedText || '(no refined text yet)';
    if (els.selectedRefinedMeta) {
      const confText = item.confidencePct === null ? '—' : `${item.confidencePct}%`;
      els.selectedRefinedMeta.innerHTML = `${formatDuration(item.durationSeconds)} · Confidence <strong>${confText}</strong>`;
    }

    if (els.selectedStatusCard) {
      els.selectedStatusCard.classList.remove('sd-status-card--failed', 'sd-status-card--draft');
      const variant = item.status === 'sent' ? null : item.status === 'failed' || item.status === 'recoverable' ? 'failed' : 'draft';
      if (variant) els.selectedStatusCard.classList.add(`sd-status-card--${variant}`);
    }
    if (els.selectedStatusTitle) {
      els.selectedStatusTitle.textContent = item.status === 'sent' ? 'Sent successfully' : item.status === 'failed' || item.status === 'recoverable' ? 'Failed to send' : 'Unsent draft';
    }
    if (els.selectedStatusTime) {
      const statusTimestamp = resolvedStatusTimestamp(item);
      els.selectedStatusTime.textContent = `${dayLabelFor(statusTimestamp)}, ${formatClockTime(statusTimestamp)}`;
    }

    if (els.selectedPersonaName) els.selectedPersonaName.textContent = item.persona || '—';
    if (els.selectedContactName) els.selectedContactName.textContent = item.contact || '—';
    if (els.selectedAudioDuration) els.selectedAudioDuration.textContent = formatDuration(item.durationSeconds);

    setSelectedActionsEnabled(true);
  }

  function setSelectedActionsEnabled(enabled) {
    for (const btn of [els.reopenButton, els.listenButton, els.duplicateButton, els.pinActionButton, els.deleteButton, els.restoreButton, els.resendButton]) {
      if (btn) btn.disabled = !enabled;
    }
  }

  function renderAll() {
    renderTimeline();
    renderSelectedItem();
  }

  function selectItem(id) {
    selectedId = id;
    renderAll();
  }

  // --- SELECTED ITEM actions ------------------------------------------------------

  function togglePin(id) {
    const targetId = id || selectedId;
    if (!targetId) return;
    if (pinnedIds.has(targetId)) pinnedIds.delete(targetId);
    else pinnedIds.add(targetId);
    renderAll();
  }

  function handleReopenClick() {
    const item = getSelectedItem();
    if (!item) return;
    if (item.sourceType === 'recording') {
      hks.showToast?.('Reopen isn’t available for a raw recording yet -- try Listen, or Restore to re-transcribe it.', 'warning');
      return;
    }
    if (hks.drafts?.renderDraft) {
      hks.drafts.renderDraft(item.raw);
      hks.showToast?.('Reopened in the draft editor.', 'success', 2000);
    } else {
      hks.showToast?.('Reopen isn’t wired up yet.', 'warning');
    }
  }

  async function handleListenClick() {
    const item = getSelectedItem();
    if (!item) return;
    if (!hks.drafts?.runDraftTts) {
      hks.showToast?.('Listen is not wired up yet.', 'warning');
      return;
    }
    if (item.sourceType === 'draft' && hks.drafts.renderDraft) {
      hks.drafts.renderDraft(item.raw);
    }
    await hks.drafts.runDraftTts(false);
  }

  // TODO(phase-integration): no existing duplicate concept for a draft or
  // recording -- see file header table.
  function handleDuplicateClick() {
    const item = getSelectedItem();
    if (hks.onDuplicateRequested) {
      hks.onDuplicateRequested(item);
      return;
    }
    hks.showToast?.('Duplicate isn’t wired up yet.', 'warning');
    if (typeof console !== 'undefined') console.warn('[libraryWorkspace] Duplicate clicked with no hooks.onDuplicateRequested handler.');
  }

  function handlePinClick() {
    const item = getSelectedItem();
    if (item) togglePin(item.id);
  }

  async function handleDeleteClick() {
    const item = getSelectedItem();
    if (!item) return;
    if (item.sourceType === 'recording') {
      const recId = item.raw?.id;
      try {
        await deleteRecording(recId);
        hks.showToast?.('Recording discarded.', 'success', 2000);
        await refresh();
      } catch (error) {
        hks.showToast?.(`Discard failed: ${error.message}`, 'danger');
      }
      return;
    }
    // TODO(phase-integration): no per-draft delete endpoint exists (only
    // clearDrafts(), which wipes ALL history) -- see file header table.
    if (hks.onDeleteRequested) {
      hks.onDeleteRequested(item);
      return;
    }
    hks.showToast?.('Delete isn’t wired up yet for saved drafts.', 'warning');
    if (typeof console !== 'undefined') console.warn('[libraryWorkspace] Delete clicked on a draft item with no hooks.onDeleteRequested handler.');
  }

  // TODO(phase-integration): SPEC 5 explicitly calls out restore/resend
  // routing as needing main.js composition -- see file header table.
  function handleRestoreClick() {
    const item = getSelectedItem();
    if (hks.onRestoreRequested) {
      hks.onRestoreRequested(item);
      return;
    }
    hks.showToast?.('Restore isn’t wired up yet.', 'warning');
    if (typeof console !== 'undefined') console.warn('[libraryWorkspace] Restore clicked with no hooks.onRestoreRequested handler.');
  }

  function handleResendClick() {
    const item = getSelectedItem();
    if (hks.onResendRequested) {
      hks.onResendRequested(item);
      return;
    }
    hks.showToast?.('Resend isn’t wired up yet.', 'warning');
    if (typeof console !== 'undefined') console.warn('[libraryWorkspace] Resend clicked with no hooks.onResendRequested handler.');
  }

  async function handleClearRecordings() {
    try {
      await clearRecordings();
      hks.showToast?.('All saved recordings cleared.', 'success', 2000);
      await refresh();
    } catch (error) {
      hks.showToast?.(`Clear recordings failed: ${error.message}`, 'danger');
    }
  }

  async function handleRetranscribeSelected() {
    const item = getSelectedItem();
    if (!item || item.sourceType !== 'recording') return;
    try {
      await retranscribeRecording(item.raw?.id);
      hks.showToast?.('Re-transcribe queued.', 'success', 2000);
      await refresh();
    } catch (error) {
      hks.showToast?.(`Re-transcribe failed: ${error.message}`, 'danger');
    }
  }

  async function handleRawTranscriptCopy() {
    const item = getSelectedItem();
    const text = item?.rawText || '';
    if (!text.trim()) {
      hks.showToast?.('No raw transcript to copy yet.', 'warning');
      return;
    }
    try {
      await writeClipboard(text);
      hks.showToast?.('Raw transcript copied to clipboard.', 'success', 2000);
    } catch (error) {
      hks.showToast?.(`Copy failed: ${error.message}`, 'danger');
    }
  }

  // --- lifecycle -----------------------------------------------------------------

  function bindOnce() {
    bindFilterChips();
    els.selectedPinButton?.addEventListener?.('click', handlePinClick);
    els.reopenButton?.addEventListener?.('click', () => handleReopenClick());
    els.listenButton?.addEventListener?.('click', () => handleListenClick());
    els.duplicateButton?.addEventListener?.('click', () => handleDuplicateClick());
    els.pinActionButton?.addEventListener?.('click', handlePinClick);
    els.deleteButton?.addEventListener?.('click', () => handleDeleteClick());
    els.restoreButton?.addEventListener?.('click', () => handleRestoreClick());
    els.resendButton?.addEventListener?.('click', () => handleResendClick());
    els.selectedAudioPlayButton?.addEventListener?.('click', () => handleListenClick());
  }

  function init() {
    bindOnce();
    renderAll();
    return { getSelectedItem };
  }

  return {
    init,
    refresh,
    setItems,
    renderAll,
    renderTimeline,
    renderSelectedItem,
    selectItem,
    getSelectedItem,
    getVisibleItems,
    handleSearchInput,
    setChipFilter,
    togglePin,
    handleReopenClick,
    handleListenClick,
    handleDuplicateClick,
    handlePinClick,
    handleDeleteClick,
    handleRestoreClick,
    handleResendClick,
    handleClearRecordings,
    handleRetranscribeSelected,
    handleRawTranscriptCopy,
  };
}
