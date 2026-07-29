// libraryWorkspace.js — the Library workspace (Wave 4, Gate 4).
//
// Wave 3 shipped the backend: docs/release/WAVE3_LIBRARY_CONTRACT.md is the
// ratified spec and `/library/*` is live. This module is the UI that finally
// uses it, replacing the Phase-3 adapter that could only read `/drafts` +
// `/history` and had to stub every mutation.
//
// WHAT CHANGED FROM THE PHASE-3 ADAPTER, and why it matters:
//
//   * The timeline is now BACKEND-driven. `GET /library/search` does the
//     filtering, ordering (pinned first, then newest) and pagination in SQL.
//     The old module fetched every draft and filtered in JS, which meant the
//     footer count described the fetched slice, not the archive, and "Pinned"
//     could only ever find pins made in the current session.
//   * Pin is `POST /library/drafts/{id}/pin`, so it survives a restart. The
//     old `pinnedIds` Set died with the page.
//   * Delete, duplicate, reopen, resend, restore and the three clear scopes
//     are real calls, not `hooks.on*Requested` stubs. Every destructive one
//     goes through the in-page confirmation dialog first, and the dialog
//     describes what will be removed WITHOUT quoting any message text
//     (contract §7: previews are content-free -- `char_count`, never the
//     characters).
//   * Reopen/resend never mutate the entry they came from. For an item the
//     backend says `requires_new_record` (i.e. it is already sent), Reopen
//     FORKS via `POST .../reopen` and loads the fork into Talk, so Talk's
//     ordinary save path can never rewrite history. See handleReopenClick().
//   * Restored recordings are labelled. D-0020 accepted "a restored recording
//     yields a draft whose final_text is the raw transcript" on the condition
//     that Wave 4's UI say so; `provenanceLabel()` is that labelling, and it
//     is rendered on the timeline card AND in the Selected Item panel.
//
// SEAMS THIS MODULE DOES NOT REACH THROUGH. Talk and the drafts feature are
// owned elsewhere. Reopen uses exactly three public entry points --
// `hooks.drafts.renderDraft(record)`, `hooks.talkWorkspace.refresh()` and
// `hooks.shell.goTo('talk')` -- and nothing else. Where a seam is missing it
// is reported in the handoff rather than worked around here.
//
// ---------------------------------------------------------------------------

import {
  librarySearch,
  setLibraryDraftPinned,
  deleteLibraryDraft,
  deleteLibraryHistoryEntry,
  deleteLibraryRecording,
  duplicateLibraryDraft,
  fetchLibraryReopen,
  commitLibraryReopenEdit,
  resendLibraryDraft,
  restoreLibraryRecording,
  restoreLibraryDraft,
  clearLibrary,
  fetchRecordings,
  setDraftContact,
} from '../api/backend.js';

// Reuse the shared confidence-band/color logic from Talk (SPEC 2's
// confidence-color rule is universal, not Talk-specific) rather than
// re-deriving it.
import { formatConfidencePercent, mapConfidenceBand, confidenceBandToCssVar } from './talkWorkspace.js';

/**
 * The default network surface. Injectable via `deps.api` so the orchestration
 * below (which decision leads to which call, in which order, with which
 * confirm flag) is unit-testable without a DOM or a backend -- the same
 * reason server-side services take their stores by injection.
 */
export const DEFAULT_LIBRARY_API = {
  librarySearch,
  setLibraryDraftPinned,
  deleteLibraryDraft,
  deleteLibraryHistoryEntry,
  deleteLibraryRecording,
  duplicateLibraryDraft,
  fetchLibraryReopen,
  commitLibraryReopenEdit,
  resendLibraryDraft,
  restoreLibraryRecording,
  restoreLibraryDraft,
  clearLibrary,
  fetchRecordings,
  setDraftContact,
};

// --- Status vocabulary --------------------------------------------------------
//
// Mirrors backend/domain/library.py's five status sets EXACTLY. If the two
// ever disagree the UI offers a filter the backend rejects with 400
// `invalid_status`, so this list is a contract copy, not a convenience.
//
// The groups are optgroup LABELS, not selectable values: `GET /library/search`
// declares `status: Optional[str]`, so exactly one status can be sent per
// request and a "show me everything unsent" group filter is not expressible.
// See LIBRARY_PLACEMENT_MAP['search.statusGroups'] -- that capability is an
// intentional cut this wave, not an oversight.

export const LIBRARY_STATUS_GROUPS = [
  { label: 'Unsent', statuses: ['pending', 'accepted', 'send_interrupted', 'failed', 'declined'] },
  { label: 'Sent', statuses: ['sent'] },
  { label: 'Sending', statuses: ['sending'] },
  { label: 'Needs attention', statuses: ['send_error', 'error', 'blocked'] },
  { label: 'Scratch', statuses: ['scratch'] },
];

export const KNOWN_STATUSES = LIBRARY_STATUS_GROUPS.flatMap((group) => group.statuses);

const STATUS_LABEL = {
  pending: 'Pending review',
  accepted: 'Accepted',
  send_interrupted: 'Send interrupted',
  failed: 'Failed',
  declined: 'Declined',
  sent: 'Sent',
  sending: 'Sending…',
  send_error: 'Send error',
  error: 'Error',
  blocked: 'Blocked',
  scratch: 'Scratch',
};

/** Human label for a backend status. Unknown statuses show verbatim rather than as a blank. */
export function statusLabel(status) {
  return STATUS_LABEL[status] || String(status || '—');
}

// --- Pure helpers (no DOM) -----------------------------------------------------

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/**
 * Normalizes the two timestamp shapes this workspace has to unify.
 *
 * Drafts carry an ISO-8601 `created_at` string (contract §1). Retained
 * recordings carry `time.time()` -- epoch SECONDS as a float
 * (recordings.py:96). Feeding the latter straight to `new Date()` dates every
 * recording to January 1970, which is what the previous version of this file
 * did: `recording?.created_at || Date.now()`. Anything numeric below the
 * year-2001 millisecond mark is therefore read as seconds.
 */
export function toEpochMs(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value < 1e12 ? Math.round(value * 1000) : Math.round(value);
  }
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

/** 'Today' / 'Yesterday' / 'Jul 20' for a timestamp, relative to `now` (defaults to `new Date()`). Never throws on a bad timestamp -- returns 'Unknown'. */
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
 * Library's status vocabulary is simpler than the raw backend status field:
 * 'sent' | 'failed' | 'recoverable' | 'unsent'. The RAW status is kept
 * alongside it on the item (`item.rawStatus`) and is what the status filter
 * and the delete preview quote -- this derived value only drives the glyph,
 * the pipeline label and the colour band.
 */
export function deriveLibraryStatusFromDraft(draft) {
  if (!draft) return 'unsent';
  if (draft.send_result) {
    return draft.send_result.ok === false ? 'failed' : 'sent';
  }
  if (draft.status === 'sent') return 'sent';
  if (draft.status === 'send_error' || draft.status === 'error' || draft.status === 'blocked') {
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
 * is known, else the capture timestamp.
 */
export function resolvedStatusTimestamp(item) {
  if (item?.status === 'sent' && item?.sentAtTimestamp) return item.sentAtTimestamp;
  return item?.timestamp;
}

/**
 * Bottom-right status line text, matching SPEC 5's three exact variants.
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
 * 'draft'/blue); 60-69 mid(amber); <60 low(red).
 */
export function mapLibraryConfidenceBand(score, status) {
  const isDraftLike = status === 'unsent' || status === 'draft' || !status;
  return mapConfidenceBand(score, isDraftLike ? 'pending' : 'sent');
}

// --- Provenance (contract §1, D-0020's labelling requirement) -----------------

/**
 * How a record came to exist, when it did not come from a fresh capture.
 *
 * `restored_from_recording_id` is the D-0020 case and the only one the ruling
 * made mandatory: that draft's `final_text` IS the raw transcript -- the
 * restore path deliberately skips persona cleanup so it cannot double-create
 * a draft -- so the UI must not present it as a cleaned-up message. The other
 * four are the same idea applied to the rest of contract §1's provenance
 * fields: a duplicate, a fork of sent history, a revision of a pending draft
 * and a restored draft are all things a user can otherwise mistake for the
 * original.
 *
 * Order matters: a restore is checked before a duplicate because a record
 * can only ever carry one of these, and the restore fields are the ones with
 * a correctness requirement attached.
 *
 * @returns {{key: string, label: string, detail: string, tone: 'warn'|'info'}|null}
 */
export function provenanceLabel(record) {
  if (!record) return null;
  const rec = record.raw && typeof record.raw === 'object' ? record.raw : record;

  if (rec.restored_from_recording_id !== null && rec.restored_from_recording_id !== undefined) {
    return {
      key: 'raw-transcript',
      label: 'Raw transcript',
      detail: 'Restored from a saved recording. This is the transcript exactly as heard — it has not been through persona cleanup yet.',
      tone: 'warn',
    };
  }
  if (rec.restored_from_draft_id !== null && rec.restored_from_draft_id !== undefined) {
    return {
      key: 'restored',
      label: 'Restored copy',
      detail: `Restored from draft #${rec.restored_from_draft_id}, which is still in your Library.`,
      tone: 'info',
    };
  }
  if (rec.duplicated_from_id !== null && rec.duplicated_from_id !== undefined) {
    return {
      key: 'duplicate',
      label: 'Duplicate',
      detail: `Duplicated from draft #${rec.duplicated_from_id}, which is unchanged.`,
      tone: 'info',
    };
  }
  if (rec.reopened_from_id !== null && rec.reopened_from_id !== undefined) {
    return {
      key: 'reopened',
      label: 'Reopened',
      detail: `A new draft forked from sent message #${rec.reopened_from_id}. The original send is untouched.`,
      tone: 'info',
    };
  }
  if (rec.revision_of_id !== null && rec.revision_of_id !== undefined) {
    return {
      key: 'revision',
      label: 'Revision',
      detail: `A revision of draft #${rec.revision_of_id}, which is unchanged.`,
      tone: 'info',
    };
  }
  return null;
}

/** True when this record's text is an unrefined transcript (D-0020). */
export function isRawTranscriptRestore(record) {
  return provenanceLabel(record)?.key === 'raw-transcript';
}

// --- Filters ------------------------------------------------------------------

export const DEFAULT_LIBRARY_FILTERS = Object.freeze({
  chip: 'all',
  persona: '',
  status: '',
  dateFrom: '',
  dateTo: '',
  contact: '',
  query: '',
});

/**
 * Turns the UI filter state into the exact query object `librarySearch()`
 * sends. Empty values are OMITTED rather than sent blank: `parse_filters`
 * treats a present-but-empty key as absent anyway, but omitting keeps the URL
 * (and therefore the QA request assertions) honest about what was actually
 * asked for.
 *
 * `contact` is deliberately NOT in the output -- contract §2 states there is
 * no contact filter until Wave 5, and sending one would be silently dropped
 * server-side while the UI implied it had been applied. It is applied as a
 * declared client-side narrowing instead (see narrowByContact()).
 */
export function buildSearchQuery(filters = {}, { limit = 25, offset = 0 } = {}) {
  const query = { limit, offset };
  if (filters.persona) query.persona = filters.persona;
  if (filters.status) query.status = filters.status;
  if (filters.dateFrom) query.date_from = filters.dateFrom;
  if (filters.dateTo) query.date_to = filters.dateTo;
  const q = String(filters.query || '').trim();
  if (q) query.q = q;
  if (filters.chip === 'pinned') query.pinned = true;
  return query;
}

/** True when any filter is narrowing the archive (drives the empty-state copy). */
export function hasActiveFilters(filters = {}) {
  return Boolean(
    filters.persona ||
      filters.status ||
      filters.dateFrom ||
      filters.dateTo ||
      filters.contact ||
      String(filters.query || '').trim() ||
      (filters.chip && filters.chip !== 'all'),
  );
}

/**
 * The one filter the backend cannot do. Applied to the LOADED page only, and
 * the footer says so in words -- see renderFooter(). Anything else here would
 * be a lie: a server-side total cannot describe a client-side narrowing.
 */
export function narrowByContact(items, contactId) {
  if (!contactId) return items || [];
  return (items || []).filter((item) => item?.contactId === contactId);
}

/**
 * Legacy in-memory predicate. Kept because it is the readable definition of
 * what each chip MEANS, and because filterItems() below is still the right
 * tool for the contact narrowing. The timeline itself no longer filters in
 * JS -- `GET /library/search` does.
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

// --- Record -> view model ------------------------------------------------------

/**
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
  const rawText = draft?.raw_text || '';
  const finalText = draft?.final_text || '';
  return {
    id: `draft-${draft?.id}`,
    backendId: draft?.id ?? null,
    sourceType: 'draft',
    preview: finalText || rawText || '(empty transcript)',
    rawText,
    refinedText: finalText,
    // Content-free size, for the delete confirmation. Never the text itself.
    charCount: (finalText || rawText || '').length,
    status,
    // The exact backend status, kept distinct from the derived four-value
    // vocabulary above: the status FILTER and the delete preview must quote
    // what the store really holds, not a UI simplification of it.
    rawStatus: draft?.status || null,
    // Wave 4: pinned is a persisted field (contract §1), not a session Set.
    pinned: Boolean(draft?.pinned),
    pinnedAt: draft?.pinned_at || null,
    persona: draft?.preset || draft?.persona_name || draft?.persona?.name || null,
    contactId: draft?.contact_id || null,
    contact: contactNameFor(draft?.contact_id, contactsById),
    confidencePct,
    confidenceBand: confidencePct === null ? null : mapLibraryConfidenceBand(score, status),
    durationSeconds: Number(draft?.metadata?.duration_seconds || 0),
    timestamp: toEpochMs(draft?.created_at ?? draft?.updated_at) ?? Date.now(),
    sentAtTimestamp: toEpochMs(draft?.send_result?.sent_at),
    hasRecording: Boolean(draft?.metadata?.has_recording ?? draft?.has_recording),
    provenance: provenanceLabel(draft),
    raw: draft,
  };
}

/** Maps a fetchRecordings()-shaped recording row into the same Library item view model. */
export function deriveLibraryItemFromRecording(recording) {
  const rawText = recording?.raw_text || '';
  return {
    id: `recording-${recording?.id}`,
    backendId: recording?.id ?? null,
    sourceType: 'recording',
    preview: rawText || recording?.filename || `Recording ${recording?.id ?? ''}`.trim(),
    rawText,
    refinedText: '',
    charCount: rawText.length,
    status: 'unsent',
    rawStatus: null,
    pinned: false,
    pinnedAt: null,
    persona: null,
    // A recording has not been through cleanup yet, so no contact was applied.
    contactId: null,
    contact: null,
    confidencePct: null,
    confidenceBand: null,
    durationSeconds: Number(recording?.duration_seconds || 0),
    timestamp: toEpochMs(recording?.created_at) ?? Date.now(),
    sentAtTimestamp: null,
    hasRecording: recording?.has_audio !== false,
    provenance: null,
    raw: recording,
  };
}

// --- Destructive-action copy ---------------------------------------------------
//
// Contract §7: previews are content-free. Everything below quotes a COUNT of
// characters, a status, a date -- never a character of the message. The delete
// dialog is built from the record the client already holds because the route
// layer drops the backend's `preview` when it refuses an unconfirmed delete
// (HTTPException carries `detail` only) -- see the handoff's "missing seams".

const DELETE_KIND_META = {
  draft: { noun: 'draft', where: 'the draft queue' },
  history_entry: { noun: 'history entry', where: 'your message history' },
  recording: { noun: 'saved recording', where: 'saved recordings' },
};

export const DELETE_KINDS = Object.keys(DELETE_KIND_META);

/**
 * Confirmation copy for a per-item delete.
 * @param {string} kind 'draft' | 'history_entry' | 'recording'
 * @param {object} preview `{ id, created_at, status, char_count, has_recording }`
 */
export function describeDeletePreview(kind, preview = {}) {
  const meta = DELETE_KIND_META[kind];
  if (!meta) {
    return { title: 'Delete', body: 'This item cannot be deleted.', details: [], confirmLabel: 'Delete' };
  }
  const details = [];
  const created = toEpochMs(preview.created_at);
  if (created !== null) {
    details.push(`Captured ${dayLabelFor(created)}, ${formatClockTime(created)}`);
  }
  if (preview.status) details.push(`Status: ${statusLabel(preview.status)}`);
  if (Number.isFinite(Number(preview.char_count))) {
    details.push(`${Number(preview.char_count)} characters of message text`);
  }
  if (preview.has_recording) {
    details.push(
      kind === 'recording'
        ? 'Its audio file and metadata sidecar are removed from disk.'
        : 'Its saved audio recording is removed too.',
    );
  }
  return {
    title: `Delete this ${meta.noun}?`,
    body: `This removes it from ${meta.where} permanently. It cannot be undone.`,
    details,
    confirmLabel: `Delete ${meta.noun}`,
  };
}

// Each scope says what it removes AND what it deliberately leaves alone.
// "Leaves alone" is not padding: contract §7 requires drafts_and_history to
// never touch recordings and recordings to never touch drafts, and a user
// cannot verify that from a dialog that only lists casualties.
const CLEAR_SCOPE_META = {
  drafts_and_history: {
    title: 'Clear drafts and message history?',
    removes: ['Every draft waiting in the queue', 'Every archived message in your history'],
    keeps: ['Saved audio recordings', 'Personas, voices, models and profile settings'],
    confirmLabel: 'Clear drafts and history',
    countKeys: ['drafts', 'history_entries'],
  },
  recordings: {
    title: 'Clear saved recordings?',
    removes: ['Every retained audio recording, with its metadata sidecar, deleted from disk'],
    keeps: ['Drafts and message history', 'Personas, voices, models and profile settings'],
    confirmLabel: 'Clear recordings',
    countKeys: ['recordings'],
  },
  all_conversation_data: {
    title: 'Clear all conversation data?',
    removes: [
      'Every draft waiting in the queue',
      'Every archived message in your history',
      'Every retained audio recording, deleted from disk',
    ],
    keeps: ['Personas, voices, models and profile settings — this scope never touches them'],
    confirmLabel: 'Clear all conversation data',
    countKeys: ['drafts', 'history_entries', 'recordings'],
  },
};

export const CLEAR_SCOPES = Object.keys(CLEAR_SCOPE_META);

const COUNT_NOUN = {
  drafts: ['draft', 'drafts'],
  history_entries: ['archived message', 'archived messages'],
  recordings: ['saved recording', 'saved recordings'],
};

/**
 * Confirmation copy for one clear scope.
 *
 * `counts` holds only what the client can actually observe, and a category
 * with no observed count is described WITHOUT a number rather than with a
 * guessed zero -- "0 recordings" when we simply have not looked would be a
 * lie that talks a user into a destructive click.
 */
export function describeClearPreview(scope, counts = {}) {
  const meta = CLEAR_SCOPE_META[scope];
  if (!meta) {
    return { title: 'Clear', body: 'Unknown scope.', removes: [], keeps: [], details: [], confirmLabel: 'Clear' };
  }
  const details = [];
  for (const key of meta.countKeys) {
    const value = counts?.[key];
    if (Number.isFinite(Number(value))) {
      const [one, many] = COUNT_NOUN[key];
      const n = Number(value);
      details.push(`${n} ${n === 1 ? one : many}`);
    }
  }
  return {
    title: meta.title,
    body: 'This cannot be undone. Each scope is confirmed on its own — confirming this one says nothing about the others.',
    removes: meta.removes,
    keeps: meta.keeps,
    details,
    confirmLabel: meta.confirmLabel,
  };
}

/**
 * Turns a thrown backend error into the sentence the user sees and the
 * screen reader announces. The structured `detail` code is the authority --
 * the raw message is a fallback, never a guess.
 */
export function describeLibraryError(error, action = 'That action') {
  const code = error?.detail || error?.body?.detail;
  switch (code) {
    case 'send_in_flight':
      return `${action} is unavailable: this message is being sent right now. Try again once the send finishes.`;
    case 'not_found':
      return `${action} failed: that item is no longer in your Library.`;
    case 'confirmation_required':
      return `${action} needs confirmation before it can run.`;
    case 'invalid_id':
      return `${action} failed: that item has an unusable identifier.`;
    case 'invalid_status':
      return 'That status filter is not one the Library recognises.';
    case 'invalid_date':
      return 'That date range could not be read. Use a calendar date.';
    case 'write_failed':
    case 'partial_write':
      return `${action} could not be saved. Nothing was changed — check the app logs.`;
    default:
      return `${action} failed: ${error?.message || 'unknown error'}`;
  }
}

// --- Inventory -> Library placement map (machine-readable parity gate) --------
//
// Gate 4's rule: every entry ends `wired: true` or carries
// `intentional_cut: true` with a rationale. No entry may remain a bare
// unexplained gap. parityGates.test.mjs enforces the shape; the Gate 4 rule
// itself is enforced in libraryWorkspace.test.mjs.

export const LIBRARY_SECTIONS = ['search', 'timeline', 'selected', 'recovery', 'clear'];

export function isValidLibrarySection(id) {
  return LIBRARY_SECTIONS.includes(id);
}

export const LIBRARY_PLACEMENT_MAP = {
  'search.fullText': { section: 'search', control: 'Full-text history search', wired: true, note: 'Wave 4: GET /library/search ?q= -- FTS5 in SQL, debounced, resets pagination' },
  'search.filterChips': { section: 'search', control: 'All / Pinned chips', wired: true, note: 'Wave 4: both are exactly expressible against the route (no filter / pinned=true). The three lossy status chips were replaced by the real status filter below' },
  'search.personaFilter': { section: 'search', control: 'Persona filter', wired: true, note: 'Wave 4: ?persona= -> the preset column (contract Amendment A1). Options come from the live persona list via setPersonaOptions()' },
  'search.statusFilter': { section: 'search', control: 'Status filter (single status)', wired: true, note: 'Wave 4: ?status= against the backend KNOWN_STATUSES vocabulary' },
  'search.statusGroups': {
    section: 'search',
    control: 'Multi-status group filter ("everything unsent")',
    wired: false,
    intentional_cut: true,
    note: 'CUT for Wave 4. GET /library/search declares status as a single Optional[str], so a group of statuses cannot be expressed in one request. Issuing one request per status and merging would make "Load more" incoherent: each stream paginates independently, so a page boundary in one status can hide items newer than the last item shown from another. The status filter offers every individual status instead, grouped under the same labels. Seam needed to un-cut: accept a repeated or comma-separated status parameter',
  },
  'search.contactFilter': {
    section: 'search',
    control: 'Contact filter',
    wired: true,
    note: 'Wave 4: applied CLIENT-SIDE over the loaded page, because contract §2 states there is deliberately no contact filter until Wave 5 (contacts are not qualified before then). The footer says so in words when the filter is active -- it reports the narrowed count and the unnarrowed backend total separately rather than presenting a client-side count as an archive total',
  },
  'search.dateFilter': { section: 'search', control: 'Date range filter', wired: true, note: 'Wave 4: ?date_from / ?date_to, inclusive; the backend widens a date-only date_to to end-of-day (contract Amendment A1)' },
  'search.clearHistory': { section: 'search', control: 'Clear History', wired: true, note: 'Wave 4: the three POST /library/clear scopes, each with its own confirmation describing exactly what it removes and what it leaves' },

  'timeline.dayGrouping': { section: 'timeline', control: 'Today / Yesterday day grouping', wired: true },
  'timeline.cards': { section: 'timeline', control: 'Message cards (raw -> refined -> status)', wired: true },
  'timeline.statusGlyphs': { section: 'timeline', control: 'Per-item status glyph (sent/failed/draft/pinned)', wired: true },
  'timeline.confidence': { section: 'timeline', control: 'Per-item confidence bar', wired: true },
  'timeline.duration': { section: 'timeline', control: 'Per-item recording duration', wired: true },
  'timeline.provenance': { section: 'timeline', control: 'Provenance badge (raw transcript / duplicate / reopened / revision / restored)', wired: true, note: 'Wave 4: D-0020 requires a restored recording to be labelled a raw transcript; the other four contract §1 provenance fields are labelled the same way' },
  'timeline.waveformThumb': {
    section: 'timeline',
    control: 'Per-item waveform thumbnail',
    wired: false,
    intentional_cut: true,
    note: 'CUT by director ruling, reaffirmed in D-0020 and WAVE3_LIBRARY_CONTRACT §6: no amplitude-envelope field is persisted, and items carry aggregate rms/peak only. Any squiggle drawn here would be decoration implying it depicts that specific recording',
  },
  'timeline.loadMore': { section: 'timeline', control: 'Load more / pagination', wired: true, note: 'Wave 4: limit/offset against GET /library/search; the footer reports loaded-vs-total from the backend total, not from the fetched slice' },
  'timeline.emptyState': { section: 'timeline', control: 'Empty and error states', wired: true, note: 'Wave 4: distinguishes an empty archive, a filter that matched nothing, and a failed request (which offers Retry and never renders as "no messages")' },
  'timeline.liveRegion': { section: 'timeline', control: 'Screen-reader status announcements', wired: true, note: 'Wave 4: #sdLibraryStatus is role=status aria-live=polite; every async outcome (pin, delete, duplicate, restore, resend, clear, search, load-more, failure) announces there' },

  'selected.detail': { section: 'selected', control: 'Selected item detail panel', wired: true },
  'selected.playAudio': { section: 'selected', control: 'Replay captured audio', wired: true },
  'selected.reopen': { section: 'selected', control: 'Reopen in Talk', wired: true, note: 'Wave 4: GET /library/drafts/{id}/reopen decides. requires_new_record forks via POST .../reopen so Talk can never rewrite history; otherwise the live pending draft itself is loaded. Then drafts.renderDraft -> talkWorkspace.refresh() -> shell.goTo("talk"), all public entry points' },
  'selected.resend': { section: 'selected', control: 'Resend', wired: true, note: 'Wave 4: POST /library/drafts/{id}/resend returns a plan whose only next_action is reopen_for_review. Resend routes through reopen -> review; it never sends' },
  'selected.restore': { section: 'selected', control: 'Restore from recovery', wired: true, note: 'Wave 4: POST /library/recordings/{id}/restore (retranscribe) for recordings and POST /library/drafts/{id}/restore for recoverable drafts. Restored recordings are labelled raw transcripts per D-0020' },
  'selected.duplicate': { section: 'selected', control: 'Duplicate', wired: true, note: 'Wave 4: POST /library/drafts/{id}/duplicate; the copy is always pending and carries duplicated_from_id, shown as a provenance badge' },
  'selected.delete': { section: 'selected', control: 'Delete item', wired: true, note: 'Wave 4: DELETE /library/{drafts|history|recordings}/{id}?confirm=true behind a content-free confirmation dialog; an already-absent target reports "already gone" rather than an error' },
  'selected.pin': { section: 'selected', control: 'Pin / unpin', wired: true, note: 'Wave 4: POST /library/drafts/{id}/pin -- persisted in both the queue and the archive, so it survives a restart' },
  'selected.setContact': { section: 'selected', control: 'Attach this message to a contact (retroactive)', wired: true, note: 'Wave 6 (D-0023 deferral): calls api.setDraftContact. The Contact row only displayed the capture-time contact, so a draft dictated before that person existed as a contact could never be attributed; the route shipped in Wave 5 with no caller. Drafts only -- history entries and recordings have no contact_id, so the control is disabled rather than failing at the network. An empty value detaches' },

  'recovery.recordings': { section: 'recovery', control: 'Retained recordings list', wired: true, note: 'Wave 4: its own section in Library, from GET /recordings, with per-row Restore and Delete' },
  'recovery.retranscribe': { section: 'recovery', control: 'Retranscribe a retained recording', wired: true, note: 'Wave 4: POST /library/recordings/{id}/restore re-transcribes and creates a pending draft labelled a raw transcript' },
  'recovery.restoreDraft': { section: 'recovery', control: 'Restore a recoverable draft', wired: true, note: 'Wave 4: POST /library/drafts/{id}/restore clones a refused or errored draft into a fresh pending one, leaving the original in place' },

  'clear.draftsAndHistory': { section: 'clear', control: 'Clear drafts + history', wired: true },
  'clear.recordings': { section: 'clear', control: 'Clear saved recordings', wired: true },
  'clear.allConversationData': { section: 'clear', control: 'Clear all conversation data', wired: true },
};

// --- Reusable element lookup ---------------------------------------------------

export const LIBRARY_ELEMENT_IDS = {
  searchInput: 'sdLibrarySearchInput',
  filterButton: 'sdLibraryFilterButton',
  filterPanel: 'sdLibraryFilterPanel',
  personaFilter: 'sdLibraryPersonaFilter',
  statusFilter: 'sdLibraryStatusFilter',
  contactFilter: 'sdLibraryContactFilter',
  dateFromInput: 'sdLibraryDateFrom',
  dateToInput: 'sdLibraryDateTo',
  filterResetButton: 'sdLibraryFilterReset',
  filterChipAll: 'sdFilterAll',
  filterChipPinned: 'sdFilterPinned',
  timelineContainer: 'sdLibraryTimeline',
  liveRegion: 'sdLibraryStatus',
  itemsCount: 'sdLibraryItemsCount',
  loadMoreButton: 'sdLibraryLoadMoreButton',

  recordingsSection: 'sdLibraryRecordingsSection',
  recordingsList: 'sdLibraryRecordingsList',
  recordingsCount: 'sdLibraryRecordingsCount',

  clearDraftsButton: 'sdLibraryClearDraftsButton',
  clearRecordingsButton: 'sdLibraryClearRecordingsButton',
  clearAllButton: 'sdLibraryClearAllButton',

  confirmDialog: 'sdLibraryConfirm',
  confirmTitle: 'sdLibraryConfirmTitle',
  confirmBody: 'sdLibraryConfirmBody',
  confirmDetails: 'sdLibraryConfirmDetails',
  confirmCancelButton: 'sdLibraryConfirmCancel',
  confirmAcceptButton: 'sdLibraryConfirmAccept',

  selectedPinButton: 'sdSelectedItemPinButton',
  selectedProvenance: 'sdSelectedProvenance',
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
  // Retroactive contact attachment (D-0023).
  selectedContactPicker: 'sdSelectedContactPicker',
  selectedContactApplyButton: 'sdSelectedContactApply',
  selectedContactMessage: 'sdSelectedContactMessage',
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

// --- DOM-wiring feature ---------------------------------------------------------

const PAGE_SIZE = 25;

/**
 * @param {object} deps
 * @param {object} deps.elements Library workspace DOM refs -- see
 *   LIBRARY_ELEMENT_IDS (use collectLibraryElements() for the common case).
 *   Every access is optional-chained.
 * @param {object} [deps.api] Network surface; defaults to DEFAULT_LIBRARY_API.
 * @param {object} deps.hooks
 *   hooks.showToast(msg, tone, duration)
 *   hooks.drafts            the live drafts feature (renderDraft / runDraftTts)
 *   hooks.talkWorkspace     the live Talk feature (refresh)
 *   hooks.shell             the shell feature (goTo)
 *   hooks.writeClipboardText
 *   hooks.now()             injectable clock, for deterministic tests
 */
export function createLibraryWorkspaceFeature({ elements, hooks, api } = {}) {
  const els = elements || {};
  const hks = hooks || {};
  const net = api || DEFAULT_LIBRARY_API;
  const doc = () => (typeof document !== 'undefined' ? document : null);

  let items = [];
  let contactsById = new Map();
  let recordingItems = [];
  let total = 0;
  let filters = { ...DEFAULT_LIBRARY_FILTERS };
  let selectedId = null;
  // The item id the contact picker was last rebuilt for, so renderSelectedItem()
  // can tell "the user changed the dropdown but hasn't hit Apply yet" apart
  // from "a different item is selected now" -- a cold-start/health-poll
  // repopulate re-rendering the SAME item must not silently discard a staged,
  // uncommitted contact choice back to whatever is actually persisted.
  let contactPickerRenderedForId = null;
  let searchTimer = null;
  let loadError = null;
  let recordingsError = null;
  let busy = false;
  let pendingConfirm = null;
  let lastAnnouncement = '';

  // --- feedback -----------------------------------------------------------------

  /**
   * The single place an async outcome is reported. Every caller goes through
   * here so a sighted user (toast) and a screen-reader user (live region) are
   * told the same thing at the same time -- previously the toast was the only
   * channel, which made every Library outcome silent to assistive tech.
   */
  function announce(message, tone = 'info') {
    lastAnnouncement = message;
    if (els.liveRegion) {
      // Re-announce an identical message by clearing first: a live region
      // whose text does not change is not re-read, and "Deleted" twice in a
      // row is two real events.
      els.liveRegion.textContent = '';
      els.liveRegion.textContent = message;
    }
    if (tone !== 'silent') hks.showToast?.(message, tone === 'info' ? 'info' : tone, 3000);
  }

  function getLastAnnouncement() {
    return lastAnnouncement;
  }

  function reportError(error, action) {
    const message = describeLibraryError(error, action);
    announce(message, 'danger');
    return message;
  }

  function writeClipboard(text) {
    const fn = hks.writeClipboardText || (typeof window !== 'undefined' ? window.betterFingers?.writeClipboardText : null);
    return fn ? fn(text) : Promise.resolve();
  }

  // --- selection ------------------------------------------------------------------

  function allItems() {
    return [...items, ...recordingItems];
  }

  function getVisibleItems() {
    return narrowByContact(items, filters.contact);
  }

  function getSelectedItem() {
    return allItems().find((item) => item.id === selectedId) || null;
  }

  /**
   * Seeds the item list directly (no network call) and re-renders. Used by
   * tests; `refresh()` is the real, backend-backed way to populate.
   */
  function setItems(newItems) {
    items = Array.isArray(newItems) ? newItems : [];
    total = items.length;
    if (!selectedId && items.length) selectedId = items[0].id;
    renderAll();
    return items;
  }

  function setContacts(contacts) {
    const list = Array.isArray(contacts) ? contacts : [];
    contactsById = new Map(list.map((c) => [c.id, c]));
    renderContactOptions(list);
    renderAll();
  }

  function setPersonaOptions(names) {
    renderSelectOptions(els.personaFilter, 'Any persona', (names || []).map((n) => ({ value: n, label: n })));
    if (els.personaFilter) els.personaFilter.value = filters.persona || '';
  }

  // --- data loading ------------------------------------------------------------------

  /**
   * Loads a page of the archive. `append` is the Load-more path: it keeps the
   * items already on screen and asks for the next offset. Anything that
   * changes the query (a filter, the search box, a chip) resets to offset 0,
   * because a page-2 request under a different filter describes a different
   * result set.
   */
  async function loadPage({ append = false } = {}) {
    const offset = append ? items.length : 0;
    const query = buildSearchQuery(filters, { limit: PAGE_SIZE, offset });
    setBusy(true);
    // Retried once before giving up: the field failure is a slow first
    // response against api/backend.js's timeout budget, not a dead endpoint
    // (mirrors bootstrap/signalDeskApp.js's loadPersonaList).
    let payload = null;
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        payload = await net.librarySearch(query);
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) {
      // A failed request must never render as "No messages yet" -- an empty
      // archive and an unreachable backend are different facts, and only one
      // of them means the user has lost nothing. `items` is left untouched
      // (there is nothing to preserve on the very first, cold-start load, so
      // that case still falls through to buildEmptyState's honest error+retry).
      loadError = describeLibraryError(lastError, 'Loading your Library');
      announce(loadError, 'danger');
    } else {
      const page = (payload?.results || []).map((record) => deriveLibraryItemFromDraft(record, contactsById));
      items = append ? [...items, ...page] : page;
      total = Number(payload?.total ?? items.length);
      loadError = null;
      if (!selectedId || !allItems().some((item) => item.id === selectedId)) {
        selectedId = items[0]?.id || recordingItems[0]?.id || null;
      }
      if (append) {
        announce(`Loaded ${page.length} more. Showing ${items.length} of ${total}.`, 'silent');
      }
    }
    setBusy(false);
    renderAll();
    return items;
  }

  async function loadRecordings() {
    let payload = null;
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        payload = await net.fetchRecordings();
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) {
      // Kept separate from loadError: recordings failing must not blank the
      // timeline, and the recordings section must not claim "none retained"
      // when the truth is "we could not ask". Retried once already; on total
      // failure keep whatever was already listed (renderRecordings() only
      // falls back to the full error state when there is nothing to keep).
      recordingsError = describeLibraryError(lastError, 'Loading saved recordings');
      announce(recordingsError, 'danger');
    } else {
      recordingItems = (payload?.recordings || []).map(deriveLibraryItemFromRecording);
      recordingsError = null;
    }
    renderRecordings();
    return recordingItems;
  }

  async function refresh({ append = false } = {}) {
    const [loaded] = await Promise.all([loadPage({ append }), loadRecordings()]);
    return loaded;
  }

  function setBusy(next) {
    busy = Boolean(next);
    if (els.loadMoreButton) els.loadMoreButton.disabled = busy;
  }

  // --- search + filters ---------------------------------------------------------------

  function applyFilters(patch, { immediate = true } = {}) {
    filters = { ...filters, ...patch };
    renderFilterControls();
    if (immediate) return loadPage({ append: false });
    return Promise.resolve(items);
  }

  function handleSearchInput(query) {
    filters = { ...filters, query: String(query || '') };
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchTimer = null;
      loadPage({ append: false }).then(() => {
        if (String(filters.query || '').trim()) {
          announce(`${total} result${total === 1 ? '' : 's'} for “${filters.query.trim()}”.`, 'silent');
        }
      });
    }, 250);
  }

  function setChipFilter(chip) {
    return applyFilters({ chip });
  }

  function resetFilters() {
    filters = { ...DEFAULT_LIBRARY_FILTERS };
    if (els.searchInput) els.searchInput.value = '';
    announce('Filters cleared.', 'silent');
    return applyFilters({});
  }

  function toggleFilterPanel(force) {
    const panel = els.filterPanel;
    if (!panel) return;
    const open = force === undefined ? panel.hidden : force;
    panel.hidden = !open;
    els.filterButton?.setAttribute?.('aria-expanded', String(open));
  }

  function loadMore() {
    if (items.length >= total) return Promise.resolve(items);
    return loadPage({ append: true });
  }

  // --- rendering: filter controls -----------------------------------------------------

  function renderSelectOptions(select, placeholder, options) {
    const document_ = doc();
    if (!select || !document_ || typeof select.replaceChildren !== 'function') return;
    const nodes = [];
    const blank = document_.createElement('option');
    blank.value = '';
    blank.textContent = placeholder;
    nodes.push(blank);
    for (const option of options) {
      if (option.group) {
        const group = document_.createElement('optgroup');
        group.label = option.group;
        for (const child of option.options) {
          const el = document_.createElement('option');
          el.value = child.value;
          el.textContent = child.label;
          group.append(el);
        }
        nodes.push(group);
      } else {
        const el = document_.createElement('option');
        el.value = option.value;
        el.textContent = option.label;
        nodes.push(el);
      }
    }
    select.replaceChildren(...nodes);
  }

  function renderStatusOptions() {
    renderSelectOptions(
      els.statusFilter,
      'Any status',
      LIBRARY_STATUS_GROUPS.map((group) => ({
        group: group.label,
        options: group.statuses.map((status) => ({ value: status, label: statusLabel(status) })),
      })),
    );
    if (els.statusFilter) els.statusFilter.value = filters.status || '';
  }

  function renderContactOptions(list) {
    renderSelectOptions(
      els.contactFilter,
      'Any contact',
      (list || []).map((c) => ({ value: c.id, label: c.name || c.id })),
    );
    if (els.contactFilter) els.contactFilter.value = filters.contact || '';
  }

  function renderFilterControls() {
    const setActive = (btn, active) => {
      if (!btn) return;
      btn.classList?.toggle?.('is-active', active);
      btn.setAttribute?.('aria-pressed', String(active));
    };
    setActive(els.filterChipAll, filters.chip === 'all');
    setActive(els.filterChipPinned, filters.chip === 'pinned');
    if (els.personaFilter) els.personaFilter.value = filters.persona || '';
    if (els.statusFilter) els.statusFilter.value = filters.status || '';
    if (els.contactFilter) els.contactFilter.value = filters.contact || '';
    if (els.dateFromInput) els.dateFromInput.value = filters.dateFrom || '';
    if (els.dateToInput) els.dateToInput.value = filters.dateTo || '';
  }

  // --- rendering: timeline -------------------------------------------------------------

  function buildEmptyState(container) {
    const document_ = doc();
    const wrap = document_.createElement('div');
    wrap.className = 'sd-timeline__empty';

    const message = document_.createElement('p');
    message.className = 'sd-timeline__empty-text';

    if (loadError) {
      wrap.classList.add('sd-timeline__empty--error');
      message.textContent = loadError;
      wrap.append(message);
      const retry = document_.createElement('button');
      retry.type = 'button';
      retry.className = 'sd-timeline__empty-action';
      retry.id = 'sdLibraryRetryButton';
      retry.textContent = 'Try again';
      retry.addEventListener('click', () => loadPage({ append: false }));
      wrap.append(retry);
    } else if (hasActiveFilters(filters)) {
      message.textContent = 'No messages match these filters.';
      wrap.append(message);
      const reset = document_.createElement('button');
      reset.type = 'button';
      reset.className = 'sd-timeline__empty-action';
      reset.id = 'sdLibraryEmptyResetButton';
      reset.textContent = 'Clear filters';
      reset.addEventListener('click', () => resetFilters());
      wrap.append(reset);
    } else {
      message.textContent = 'Nothing in your Library yet. Messages you capture in Talk land here.';
      wrap.append(message);
    }
    container.append(wrap);
  }

  function renderTimeline() {
    const container = els.timelineContainer;
    const document_ = doc();
    if (!container || !document_ || typeof container.replaceChildren !== 'function') return;

    const visible = getVisibleItems();
    container.replaceChildren();

    if (!visible.length) {
      buildEmptyState(container);
      renderFooter(visible);
      return;
    }

    for (const group of groupByDay(visible)) {
      const dayEl = document_.createElement('div');
      dayEl.className = 'sd-timeline__day';

      const label = document_.createElement('div');
      label.className = 'sd-timeline__day-label';
      label.textContent = group.label;
      dayEl.append(label);

      const rows = document_.createElement('div');
      rows.className = 'sd-timeline__rows';
      group.items.forEach((item) => rows.append(buildTimelineRow(item)));

      dayEl.append(rows);
      container.append(dayEl);
    }
    renderFooter(visible);
  }

  function renderFooter(visible) {
    if (els.itemsCount) {
      if (loadError) {
        els.itemsCount.textContent = 'Count unavailable';
      } else if (filters.contact) {
        // Two numbers, said plainly, because they measure different things:
        // the narrowing is client-side over the loaded page, the total is the
        // backend's answer for everything EXCEPT the contact filter.
        els.itemsCount.textContent =
          `${visible.length} of ${items.length} loaded match this contact · ${total} match the other filters`;
      } else {
        els.itemsCount.textContent = `Showing ${items.length} of ${total} item${total === 1 ? '' : 's'}`;
      }
    }
    if (els.loadMoreButton) {
      const more = !loadError && items.length < total;
      els.loadMoreButton.hidden = !more;
      els.loadMoreButton.disabled = busy || !more;
    }
  }

  function buildProvenanceBadge(provenance) {
    const document_ = doc();
    const badge = document_.createElement('span');
    badge.className = `sd-provenance sd-provenance--${provenance.key}`;
    badge.dataset.provenance = provenance.key;
    badge.textContent = provenance.label;
    badge.title = provenance.detail;
    return badge;
  }

  function buildTimelineRow(item) {
    const document_ = doc();
    const glyph = statusToGlyph(item);
    const dayLabel = dayLabelFor(item.timestamp);
    const timeLabel = formatClockTime(item.timestamp);
    const statusTimestamp = resolvedStatusTimestamp(item);
    const statusDayLabel = dayLabelFor(statusTimestamp);
    const statusTimeLabel = formatClockTime(statusTimestamp);

    const row = document_.createElement('div');
    row.className = 'sd-timeline__row';

    const gutter = document_.createElement('div');
    gutter.className = 'sd-timeline__gutter';
    const timeEl = document_.createElement('span');
    timeEl.className = 'sd-timeline__time';
    timeEl.textContent = timeLabel;
    const glyphEl = document_.createElement('span');
    glyphEl.className = `sd-timeline__glyph sd-timeline__glyph--${glyph}`;
    glyphEl.setAttribute('aria-hidden', 'true');
    gutter.append(timeEl, glyphEl);

    const card = document_.createElement('button');
    card.type = 'button';
    card.className = `sd-message-card${item.id === selectedId ? ' is-selected' : ''}`;
    card.dataset.itemId = item.id;
    card.dataset.status = item.rawStatus || item.status;
    if (item.pinned) card.dataset.pinned = 'true';
    // The accessible name has to carry what the glyph carries visually --
    // pinned state and provenance are otherwise invisible to a screen reader.
    card.setAttribute(
      'aria-label',
      [
        item.pinned ? 'Pinned.' : '',
        item.provenance ? `${item.provenance.label}.` : '',
        `${dayLabel} ${timeLabel}.`,
        `Status ${statusLabel(item.rawStatus || item.status)}.`,
      ].filter(Boolean).join(' '),
    );

    const main = document_.createElement('div');
    main.className = 'sd-message-card__main';
    const title = document_.createElement('p');
    title.className = 'sd-message-card__title';
    title.textContent = item.preview;
    const pipeline = document_.createElement('div');
    pipeline.className = 'sd-message-card__pipeline';
    pipeline.dataset.status = item.status;
    const rawStage = document_.createElement('span');
    rawStage.className = 'sd-message-card__pipeline-stage';
    rawStage.textContent = 'Raw';
    const refinedStage = document_.createElement('span');
    refinedStage.className = 'sd-message-card__pipeline-stage';
    refinedStage.textContent = 'Refined';
    const statusStage = document_.createElement('span');
    statusStage.className = 'sd-message-card__pipeline-status';
    statusStage.textContent = pipelineStatusLabel(item.status);
    pipeline.append(rawStage, document_.createTextNode(' → '), refinedStage, document_.createTextNode(' → '), statusStage);
    main.append(title, pipeline);

    if (item.persona || item.contact || item.provenance) {
      const chips = document_.createElement('div');
      chips.className = 'sd-message-card__chips';
      if (item.provenance) chips.append(buildProvenanceBadge(item.provenance));
      if (item.persona) {
        const personaChip = document_.createElement('span');
        personaChip.className = 'sd-chip sd-chip--persona';
        personaChip.textContent = item.persona;
        chips.append(personaChip);
      }
      if (item.contact) {
        const contactChip = document_.createElement('span');
        contactChip.className = 'sd-chip sd-chip--contact';
        contactChip.textContent = item.contact;
        chips.append(contactChip);
      }
      main.append(chips);
    }

    const meta = document_.createElement('div');
    meta.className = 'sd-message-card__meta';
    if (item.confidencePct !== null) {
      meta.style?.setProperty?.('--sd-confidence-color', confidenceBandToCssVar(item.confidenceBand));
      const confWrap = document_.createElement('div');
      confWrap.className = 'sd-message-card__confidence';
      const confLabel = document_.createElement('span');
      confLabel.className = 'sd-message-card__confidence-label';
      confLabel.textContent = 'Confidence';
      const confValue = document_.createElement('span');
      confValue.className = 'sd-message-card__confidence-value';
      confValue.textContent = `${item.confidencePct}%`;
      const bar = document_.createElement('span');
      bar.className = 'sd-confidence-bar';
      const fill = document_.createElement('span');
      fill.className = 'sd-confidence-bar__fill';
      fill.style.width = `${item.confidencePct}%`;
      bar.append(fill);
      confWrap.append(confLabel, confValue, bar);
      meta.append(confWrap);
    }
    // No waveform thumbnail: cut by D-0020 / contract §6. The item model
    // carries aggregate rms/peak only, never a per-time amplitude series.
    if (item.durationSeconds > 0) {
      const duration = document_.createElement('span');
      duration.className = 'sd-message-card__duration';
      duration.textContent = formatDuration(item.durationSeconds);
      meta.append(duration);
    }

    const statusLine = document_.createElement('div');
    const variant = item.status === 'sent' ? 'sent' : item.status === 'failed' || item.status === 'recoverable' ? 'failed' : 'draft';
    statusLine.className = `sd-message-card__status sd-message-card__status--${variant}`;
    statusLine.textContent = statusLineText({ status: item.status, dayLabel: statusDayLabel, timeLabel: statusTimeLabel });
    meta.append(statusLine);

    card.append(main, meta);
    card.addEventListener('click', () => selectItem(item.id));

    row.append(gutter, card);
    return row;
  }

  // --- rendering: retained recordings ---------------------------------------------------

  function renderRecordings() {
    const list = els.recordingsList;
    const document_ = doc();
    if (!list || !document_ || typeof list.replaceChildren !== 'function') return;
    list.replaceChildren();

    // A refresh failure with nothing already loaded has nothing to fall back
    // to and gets the full error state below; a failure that struck AFTER a
    // good list was already on screen keeps showing that list (with a toast
    // already fired from loadRecordings()) rather than replacing known-good
    // rows with an error paragraph.
    const showErrorState = Boolean(recordingsError) && !recordingItems.length;

    if (els.recordingsCount) {
      els.recordingsCount.textContent = showErrorState
        ? 'Unavailable'
        : `${recordingItems.length} retained`;
    }
    if (els.clearRecordingsButton) {
      els.clearRecordingsButton.disabled = showErrorState || recordingItems.length === 0;
    }

    if (showErrorState) {
      const error = document_.createElement('p');
      error.className = 'sd-recordings__empty sd-recordings__empty--error';
      error.textContent = recordingsError;
      list.append(error);
      return;
    }
    if (!recordingItems.length) {
      const empty = document_.createElement('p');
      empty.className = 'sd-recordings__empty';
      empty.textContent = 'No audio is being retained. Recording retention is a Settings choice.';
      list.append(empty);
      return;
    }

    for (const item of recordingItems) {
      const row = document_.createElement('div');
      row.className = 'sd-recordings__row';
      row.dataset.itemId = item.id;
      row.dataset.recordingId = String(item.backendId ?? '');

      const info = document_.createElement('button');
      info.type = 'button';
      info.className = `sd-recordings__info${item.id === selectedId ? ' is-selected' : ''}`;
      const when = document_.createElement('span');
      when.className = 'sd-recordings__when';
      when.textContent = `${dayLabelFor(item.timestamp)}, ${formatClockTime(item.timestamp)}`;
      const length = document_.createElement('span');
      length.className = 'sd-recordings__duration';
      length.textContent = formatDuration(item.durationSeconds);
      info.append(when, length);
      if (!item.hasRecording) {
        const missing = document_.createElement('span');
        missing.className = 'sd-recordings__missing';
        missing.textContent = 'Audio file missing';
        info.append(missing);
      }
      info.addEventListener('click', () => selectItem(item.id));

      const restore = document_.createElement('button');
      restore.type = 'button';
      restore.className = 'sd-recordings__action';
      restore.dataset.action = 'restore';
      restore.textContent = 'Restore';
      restore.title = 'Re-transcribe this recording into a new pending draft';
      restore.disabled = !item.hasRecording;
      restore.addEventListener('click', () => handleRestoreRecording(item));

      const remove = document_.createElement('button');
      remove.type = 'button';
      remove.className = 'sd-recordings__action sd-recordings__action--danger';
      remove.dataset.action = 'delete';
      remove.textContent = 'Delete';
      remove.addEventListener('click', () => handleDeleteItem(item));

      row.append(info, restore, remove);
      list.append(row);
    }
  }

  // --- rendering: SELECTED ITEM context panel ---------------------------------------------

  function renderSelectedItem() {
    const item = getSelectedItem();

    if (els.selectedProvenance) {
      const provenance = item?.provenance || null;
      els.selectedProvenance.hidden = !provenance;
      els.selectedProvenance.textContent = provenance ? `${provenance.label} — ${provenance.detail}` : '';
      if (provenance) els.selectedProvenance.dataset.provenance = provenance.key;
      else delete els.selectedProvenance.dataset?.provenance;
    }

    if (!item) {
      if (els.selectedRawText) els.selectedRawText.textContent = 'No item selected.';
      if (els.selectedRefinedText) els.selectedRefinedText.textContent = '';
      setSelectedActionsEnabled(false);
      return;
    }

    const pinnable = item.sourceType === 'draft';
    // Retroactive contact picker (D-0023). Rebuilt from the same contactsById
    // map the display name resolves through, so the option list and the label
    // can never disagree. Only drafts carry a contact_id.
    if (els.selectedContactPicker) {
      const picker = els.selectedContactPicker;
      const current = item.contactId || '';
      // A staged-but-not-yet-Applied choice on the SAME item survives a
      // repopulate; a genuinely different item (or a value that already
      // matches what's persisted) rebuilds normally.
      const staged = contactPickerRenderedForId === item.id && picker.value !== current
        ? picker.value
        : null;
      picker.innerHTML = '';
      const none = doc()?.createElement('option');
      if (none) {
        none.value = '';
        none.textContent = 'No one in particular';
        picker.appendChild(none);
      }
      for (const contact of contactsById.values()) {
        const option = doc()?.createElement('option');
        if (!option) continue;
        option.value = contact.id;
        // textContent, never innerHTML: a contact name is user-authored.
        option.textContent = contact.name || contact.id;
        picker.appendChild(option);
      }
      picker.value = staged ?? current;
      picker.disabled = !pinnable;
      contactPickerRenderedForId = item.id;
    }
    if (els.selectedContactApplyButton) {
      els.selectedContactApplyButton.disabled = !pinnable;
    }
    if (els.selectedContactMessage) {
      els.selectedContactMessage.textContent = pinnable
        ? ''
        : 'Only drafts can be attached to a contact.';
    }
    if (els.selectedPinButton) {
      els.selectedPinButton.setAttribute('aria-pressed', String(Boolean(item.pinned)));
      els.selectedPinButton.disabled = !pinnable;
    }
    if (els.pinActionButton) {
      els.pinActionButton.setAttribute('aria-pressed', String(Boolean(item.pinned)));
      els.pinActionButton.disabled = !pinnable;
    }

    if (els.selectedRawText) els.selectedRawText.textContent = item.rawText || '(empty transcript)';
    if (els.selectedRawMeta) {
      els.selectedRawMeta.textContent = `${formatDuration(item.durationSeconds)} · ${dayLabelFor(item.timestamp)}, ${formatClockTime(item.timestamp)}`;
    }

    if (els.selectedRefinedText) {
      els.selectedRefinedText.textContent = item.refinedText
        || (isRawTranscriptRestore(item) ? item.rawText : '')
        || '(no refined text yet)';
    }
    if (els.selectedRefinedMeta) {
      const confText = item.confidencePct === null ? '—' : `${item.confidencePct}%`;
      els.selectedRefinedMeta.textContent = `${formatDuration(item.durationSeconds)} · Confidence ${confText}`;
    }

    if (els.selectedStatusCard) {
      els.selectedStatusCard.classList?.remove?.('sd-status-card--failed', 'sd-status-card--draft');
      const variant = item.status === 'sent' ? null : item.status === 'failed' || item.status === 'recoverable' ? 'failed' : 'draft';
      if (variant) els.selectedStatusCard.classList?.add?.(`sd-status-card--${variant}`);
    }
    if (els.selectedStatusTitle) {
      els.selectedStatusTitle.textContent = item.sourceType === 'recording'
        ? 'Retained recording'
        : statusLabel(item.rawStatus || item.status);
    }
    if (els.selectedStatusTime) {
      const statusTimestamp = resolvedStatusTimestamp(item);
      els.selectedStatusTime.textContent = `${dayLabelFor(statusTimestamp)}, ${formatClockTime(statusTimestamp)}`;
    }

    if (els.selectedPersonaName) els.selectedPersonaName.textContent = item.persona || '—';
    if (els.selectedContactName) els.selectedContactName.textContent = item.contact || '—';
    if (els.selectedAudioDuration) els.selectedAudioDuration.textContent = formatDuration(item.durationSeconds);

    setSelectedActionsEnabled(true, item);
  }

  /**
   * Enablement is per-action, not all-or-nothing: a recording has no draft to
   * duplicate or resend, and a still-sending draft may not be deleted (the
   * backend refuses with 409 -- the button reflects that rather than letting
   * the user discover it through an error).
   */
  function setSelectedActionsEnabled(enabled, item = null) {
    const isDraft = enabled && item?.sourceType === 'draft';
    const inFlight = item?.rawStatus === 'sending';
    const set = (btn, on) => { if (btn) btn.disabled = !on; };
    set(els.reopenButton, isDraft && !inFlight);
    set(els.listenButton, enabled);
    set(els.duplicateButton, isDraft);
    set(els.pinActionButton, isDraft);
    set(els.deleteButton, enabled && !inFlight);
    set(els.restoreButton, enabled && (item?.sourceType === 'recording' || isDraft));
    set(els.resendButton, isDraft && !inFlight);
  }

  function renderAll() {
    renderFilterControls();
    renderTimeline();
    renderRecordings();
    renderSelectedItem();
  }

  function selectItem(id) {
    selectedId = id;
    renderAll();
  }

  // --- confirmation dialog -----------------------------------------------------------
  //
  // In-page rather than window.confirm() because the copy has to be a
  // STRUCTURED description (what is removed, what is kept, how many of each)
  // and a native confirm collapses that to one string with no way to mark up
  // the "this is kept" half. It is also the only version a screen reader gets
  // a proper dialog role for.

  function renderConfirm() {
    const dialog = els.confirmDialog;
    const document_ = doc();
    if (!dialog || !document_) return;
    if (!pendingConfirm) {
      dialog.hidden = true;
      return;
    }
    dialog.hidden = false;
    if (els.confirmTitle) els.confirmTitle.textContent = pendingConfirm.title;
    if (els.confirmBody) els.confirmBody.textContent = pendingConfirm.body;
    if (els.confirmAcceptButton) els.confirmAcceptButton.textContent = pendingConfirm.confirmLabel || 'Confirm';

    const details = els.confirmDetails;
    if (details && typeof details.replaceChildren === 'function') {
      details.replaceChildren();
      const section = (label, entries, modifier) => {
        if (!entries?.length) return;
        const wrap = document_.createElement('div');
        wrap.className = `sd-confirm__group sd-confirm__group--${modifier}`;
        const heading = document_.createElement('span');
        heading.className = 'sd-confirm__group-label';
        heading.textContent = label;
        const list = document_.createElement('ul');
        list.className = 'sd-confirm__list';
        for (const entry of entries) {
          const li = document_.createElement('li');
          li.textContent = entry;
          list.append(li);
        }
        wrap.append(heading, list);
        details.append(wrap);
      };
      section('This removes', pendingConfirm.removes, 'removes');
      section('Right now that is', pendingConfirm.details, 'counts');
      section('This keeps', pendingConfirm.keeps, 'keeps');
    }
    els.confirmAcceptButton?.focus?.();
  }

  /** Opens the dialog and resolves true/false when the user answers. */
  function requestConfirmation(spec) {
    return new Promise((resolve) => {
      pendingConfirm = { ...spec, resolve };
      renderConfirm();
      // With no dialog in the document there is nothing to answer with, so
      // refuse rather than silently proceeding with a destructive call.
      if (!els.confirmDialog) {
        pendingConfirm = null;
        resolve(false);
      }
    });
  }

  function answerConfirmation(accepted) {
    const current = pendingConfirm;
    pendingConfirm = null;
    renderConfirm();
    current?.resolve?.(Boolean(accepted));
  }

  // --- actions ----------------------------------------------------------------------

  /**
   * Attach (or detach) a contact on an already-captured draft — the D-0023
   * deferral.
   *
   * The Contact row in the selected-item panel has only ever DISPLAYED the
   * contact a draft was captured against. A message dictated before that
   * person existed as a contact therefore stayed unattributed permanently,
   * with the route to fix it (`api.setDraftContact`) shipped and unreachable.
   *
   * Only drafts carry a contact_id, so the control is disabled for history
   * entries and recordings rather than failing at the network. An empty value
   * detaches, which is why "" is a real option and not a placeholder.
   */
  async function handleSetContact(contactId, item = getSelectedItem()) {
    if (!item || item.sourceType !== 'draft') return null;
    const next = typeof contactId === 'string' ? contactId : '';
    try {
      const result = await net.setDraftContact(item.backendId, next);
      const record = result?.draft || null;
      // Update in place, like the pin toggle: re-running the search would
      // reshuffle the list under the user mid-interaction.
      item.contactId = record ? (record.contact_id || '') : next;
      item.contact = contactNameFor(item.contactId, contactsById);
      if (item.raw) item.raw.contact_id = item.contactId;
      announce(item.contactId
        ? `Attached to ${item.contact || 'that contact'}.`
        : 'Detached from any contact.', 'success');
      renderAll();
      return item;
    } catch (error) {
      reportError(error, 'Attaching a contact');
      return null;
    }
  }

  async function handlePinToggle(item = getSelectedItem()) {
    if (!item || item.sourceType !== 'draft') return null;
    const next = !item.pinned;
    try {
      const result = await net.setLibraryDraftPinned(item.backendId, next);
      // Update in place rather than refetching: a pin must not reshuffle the
      // page under the user's cursor mid-interaction. The next load applies
      // the pinned-first ordering.
      const record = result?.draft || null;
      item.pinned = record ? Boolean(record.pinned) : next;
      item.pinnedAt = record?.pinned_at ?? item.pinnedAt;
      if (item.raw) {
        item.raw.pinned = item.pinned;
        item.raw.pinned_at = item.pinnedAt;
      }
      announce(item.pinned ? 'Pinned. It stays pinned after a restart.' : 'Unpinned.', 'success');
      renderAll();
      return item;
    } catch (error) {
      reportError(error, item.pinned ? 'Unpinning' : 'Pinning');
      return null;
    }
  }

  function deleteKindFor(item) {
    if (item.sourceType === 'recording') return 'recording';
    // A draft still in the live queue is deleted as a draft (which also drops
    // its in-memory recording binding); one that has aged out of the bounded
    // queue exists only as an archive row. `pending`-family statuses are the
    // ones the queue holds, so they route to the draft endpoint and the rest
    // to the history endpoint -- an already-absent target is idempotent
    // either way, so a wrong guess degrades to "already gone", never to
    // deleting something else.
    const pendingLike = ['pending', 'accepted', 'send_interrupted', 'failed', 'declined', 'scratch', 'blocked', 'error', 'send_error'];
    return pendingLike.includes(item.rawStatus) ? 'draft' : 'history_entry';
  }

  async function handleDeleteItem(item = getSelectedItem()) {
    if (!item) return false;
    const kind = deleteKindFor(item);
    const spec = describeDeletePreview(kind, {
      id: item.backendId,
      created_at: item.timestamp,
      status: item.rawStatus,
      char_count: item.charCount,
      has_recording: item.hasRecording,
    });
    const accepted = await requestConfirmation(spec);
    if (!accepted) {
      announce('Nothing was deleted.', 'silent');
      return false;
    }

    const call =
      kind === 'recording' ? net.deleteLibraryRecording
        : kind === 'draft' ? net.deleteLibraryDraft
          : net.deleteLibraryHistoryEntry;
    try {
      const result = await call(item.backendId, { confirm: true });
      // Idempotency surfaced honestly: "already gone" is a success, and
      // saying "Deleted" for something that was not there would teach the
      // user the app removed data it never had.
      if (result?.already_absent) {
        announce('That item was already gone. Nothing else changed.', 'info');
      } else {
        announce(`Deleted. ${spec.confirmLabel.replace(/^Delete /, 'The ')} is gone for good.`, 'success');
      }
      selectedId = null;
      await refresh();
      return true;
    } catch (error) {
      reportError(error, 'Deleting');
      return false;
    }
  }

  async function handleDuplicate(item = getSelectedItem()) {
    if (!item || item.sourceType !== 'draft') {
      announce('Only a draft can be duplicated.', 'warning');
      return null;
    }
    try {
      const result = await net.duplicateLibraryDraft(item.backendId);
      const created = result?.draft || null;
      announce(
        `Duplicated as a new pending draft (#${created?.id ?? '?'}). The original is unchanged.`,
        'success',
      );
      await refresh();
      if (created?.id !== undefined) selectItem(`draft-${created.id}`);
      return created;
    } catch (error) {
      reportError(error, 'Duplicating');
      return null;
    }
  }

  /**
   * Hands a record to Talk through public entry points only.
   * Returns false when a seam is missing, so the caller can say so out loud
   * instead of navigating to a workspace that did not receive the draft.
   */
  function loadIntoTalk(record) {
    if (!hks.drafts?.renderDraft) {
      announce('Reopen could not reach the draft editor. The Talk workspace is not wired up in this build.', 'danger');
      return false;
    }
    hks.drafts.renderDraft(record);
    hks.talkWorkspace?.refresh?.()?.catch?.(() => {});
    hks.shell?.goTo?.('talk');
    return true;
  }

  /**
   * Reopen. The backend decides whether editing this item may touch it:
   *
   *   editable === false        -> it is mid-send; refuse, do not navigate.
   *   requires_new_record       -> it is already sent. FORK first (POST
   *                                .../reopen with no text overrides, which
   *                                copies the source) and hand Talk the fork.
   *                                Talk's ordinary save path then edits the
   *                                fork, so the sent entry can never be
   *                                rewritten by editing it here.
   *   otherwise                 -> it is a live pending draft; Talk editing it
   *                                in place is the normal path.
   */
  async function handleReopen(item = getSelectedItem(), { announceAs = 'Reopen' } = {}) {
    if (!item) return false;
    if (item.sourceType === 'recording') {
      announce('A raw recording has no draft to reopen. Use Restore to re-transcribe it first.', 'warning');
      return false;
    }
    let payload;
    try {
      payload = (await net.fetchLibraryReopen(item.backendId))?.reopen || null;
    } catch (error) {
      reportError(error, announceAs);
      return false;
    }
    if (!payload) {
      announce(`${announceAs} failed: the Library returned no draft to open.`, 'danger');
      return false;
    }
    if (payload.editable === false) {
      announce('This message is being sent right now, so it cannot be reopened for editing yet.', 'warning');
      return false;
    }

    if (payload.requires_new_record) {
      try {
        const result = await net.commitLibraryReopenEdit(item.backendId, {});
        const created = result?.draft || null;
        if (!created) {
          announce(`${announceAs} failed: no new draft was created.`, 'danger');
          return false;
        }
        if (!loadIntoTalk(created)) return false;
        announce(
          `Opened a new draft in Talk, forked from the sent message. The original stays in your Library untouched.`,
          'success',
        );
        await refresh();
        return true;
      } catch (error) {
        reportError(error, announceAs);
        return false;
      }
    }

    if (!loadIntoTalk(item.raw)) return false;
    announce('Opened in Talk for review.', 'success');
    return true;
  }

  /**
   * Resend routes through reopen -> review and NEVER sends. The backend's
   * plan says the same thing (its only next_action is reopen_for_review);
   * this reads that plan rather than assuming it, so if the contract ever
   * changed the UI would not quietly start sending.
   */
  async function handleResend(item = getSelectedItem()) {
    if (!item || item.sourceType !== 'draft') {
      announce('Only a draft can be resent.', 'warning');
      return false;
    }
    let plan;
    try {
      const result = await net.resendLibraryDraft(item.backendId);
      plan = result?.resend || null;
    } catch (error) {
      reportError(error, 'Resend');
      return false;
    }
    if (!plan?.allowed) {
      announce(
        plan?.reason === 'send_in_flight'
          ? 'This message is already being sent. Wait for that send to finish.'
          : `Resend is not available: ${plan?.reason || 'unknown reason'}.`,
        'warning',
      );
      return false;
    }
    if (plan.next_action !== 'reopen_for_review') {
      // Defensive: nothing in the contract emits another action, and if
      // something ever does, refusing is the safe read -- silently sending
      // would be the dangerous one.
      announce(`Resend returned an action this build does not perform (${plan.next_action}). Nothing was sent.`, 'danger');
      return false;
    }
    announce('Resend opens the message for review first — nothing has been sent.', 'info');
    return handleReopen(item, { announceAs: 'Resend' });
  }

  async function handleRestoreRecording(item) {
    if (!item) return null;
    try {
      const result = await net.restoreLibraryRecording(item.backendId);
      const created = result?.draft || null;
      announce(
        `Re-transcribed into a new pending draft (#${created?.id ?? '?'}). It is the raw transcript — open it in Talk to clean it up.`,
        'success',
      );
      await refresh();
      if (created?.id !== undefined) selectItem(`draft-${created.id}`);
      return created;
    } catch (error) {
      reportError(error, 'Restoring the recording');
      return null;
    }
  }

  async function handleRestoreDraft(item) {
    if (!item) return null;
    try {
      const result = await net.restoreLibraryDraft(item.backendId);
      const created = result?.draft || null;
      announce(
        `Restored as a new pending draft (#${created?.id ?? '?'}). The item you restored from is still in your Library.`,
        'success',
      );
      await refresh();
      if (created?.id !== undefined) selectItem(`draft-${created.id}`);
      return created;
    } catch (error) {
      reportError(error, 'Restoring the draft');
      return null;
    }
  }

  function handleRestore(item = getSelectedItem()) {
    if (!item) return Promise.resolve(null);
    return item.sourceType === 'recording' ? handleRestoreRecording(item) : handleRestoreDraft(item);
  }

  async function handleClear(scope) {
    if (!CLEAR_SCOPES.includes(scope)) {
      announce('Unknown clear scope.', 'danger');
      return false;
    }
    // Only counts the client has actually observed. `history_entries` is the
    // backend's unfiltered total when no filter is active; under an active
    // filter it describes the filtered set, not the archive, so it is omitted
    // rather than quoted as if it covered everything.
    const counts = {};
    if (!hasActiveFilters(filters) && !loadError) counts.history_entries = total;
    if (!recordingsError) counts.recordings = recordingItems.length;

    const accepted = await requestConfirmation(describeClearPreview(scope, counts));
    if (!accepted) {
      announce('Nothing was cleared.', 'silent');
      return false;
    }
    try {
      await net.clearLibrary(scope, { confirm: true });
      announce(`${describeClearPreview(scope, counts).title.replace(/\?$/, '')} — done.`, 'success');
      selectedId = null;
      await refresh();
      return true;
    } catch (error) {
      reportError(error, 'Clearing');
      return false;
    }
  }

  async function handleListenClick() {
    const item = getSelectedItem();
    if (!item) return;
    if (!hks.drafts?.runDraftTts) {
      announce('Listen is unavailable: the speech engine is not wired up in this build.', 'warning');
      return;
    }
    if (item.sourceType === 'draft' && hks.drafts.renderDraft) {
      hks.drafts.renderDraft(item.raw);
    }
    try {
      await hks.drafts.runDraftTts(false);
    } catch (error) {
      reportError(error, 'Playback');
    }
  }

  async function handleRawTranscriptCopy() {
    const item = getSelectedItem();
    const text = item?.rawText || '';
    if (!text.trim()) {
      announce('There is no raw transcript to copy.', 'warning');
      return;
    }
    try {
      await writeClipboard(text);
      announce('Raw transcript copied to the clipboard.', 'success');
    } catch (error) {
      reportError(error, 'Copying');
    }
  }

  // --- lifecycle ---------------------------------------------------------------------

  function bindOnce() {
    els.searchInput?.addEventListener?.('input', (event) => handleSearchInput(event.target?.value));
    els.filterButton?.addEventListener?.('click', () => toggleFilterPanel());
    els.filterChipAll?.addEventListener?.('click', () => setChipFilter('all'));
    els.filterChipPinned?.addEventListener?.('click', () => setChipFilter('pinned'));
    els.personaFilter?.addEventListener?.('change', (e) => applyFilters({ persona: e.target?.value || '' }));
    els.statusFilter?.addEventListener?.('change', (e) => applyFilters({ status: e.target?.value || '' }));
    // Contact is the one filter that does not re-query -- it narrows what is
    // already loaded, so re-fetching would be a request that changes nothing.
    els.contactFilter?.addEventListener?.('change', (e) => {
      applyFilters({ contact: e.target?.value || '' }, { immediate: false });
      renderAll();
    });
    els.dateFromInput?.addEventListener?.('change', (e) => applyFilters({ dateFrom: e.target?.value || '' }));
    els.dateToInput?.addEventListener?.('change', (e) => applyFilters({ dateTo: e.target?.value || '' }));
    els.filterResetButton?.addEventListener?.('click', () => resetFilters());
    els.loadMoreButton?.addEventListener?.('click', () => loadMore());

    els.clearDraftsButton?.addEventListener?.('click', () => handleClear('drafts_and_history'));
    els.clearRecordingsButton?.addEventListener?.('click', () => handleClear('recordings'));
    els.clearAllButton?.addEventListener?.('click', () => handleClear('all_conversation_data'));

    els.confirmCancelButton?.addEventListener?.('click', () => answerConfirmation(false));
    els.confirmAcceptButton?.addEventListener?.('click', () => answerConfirmation(true));
    els.confirmDialog?.addEventListener?.('keydown', (event) => {
      if (event.key === 'Escape') answerConfirmation(false);
    });

    els.selectedPinButton?.addEventListener?.('click', () => handlePinToggle());
    els.selectedContactApplyButton?.addEventListener?.('click', () => {
      handleSetContact(els.selectedContactPicker?.value ?? '');
    });
    els.pinActionButton?.addEventListener?.('click', () => handlePinToggle());
    els.reopenButton?.addEventListener?.('click', () => handleReopen());
    els.listenButton?.addEventListener?.('click', () => handleListenClick());
    els.duplicateButton?.addEventListener?.('click', () => handleDuplicate());
    els.deleteButton?.addEventListener?.('click', () => handleDeleteItem());
    els.restoreButton?.addEventListener?.('click', () => handleRestore());
    els.resendButton?.addEventListener?.('click', () => handleResend());
    els.selectedAudioPlayButton?.addEventListener?.('click', () => handleListenClick());
  }

  function init() {
    bindOnce();
    renderStatusOptions();
    toggleFilterPanel(false);
    renderConfirm();
    renderAll();
    return { getSelectedItem };
  }

  return {
    init,
    refresh,
    loadPage,
    loadRecordings,
    loadMore,
    setItems,
    setContacts,
    setPersonaOptions,
    renderAll,
    renderTimeline,
    renderRecordings,
    renderSelectedItem,
    selectItem,
    getSelectedItem,
    getVisibleItems,
    getFilters: () => ({ ...filters }),
    getTotal: () => total,
    getLastAnnouncement,
    announce,
    handleSearchInput,
    setChipFilter,
    applyFilters,
    resetFilters,
    toggleFilterPanel,
    requestConfirmation,
    answerConfirmation,
    getPendingConfirmation: () => (pendingConfirm ? { ...pendingConfirm, resolve: undefined } : null),
    handlePinToggle,
    handleDeleteItem,
    handleDuplicate,
    handleReopen,
    handleResend,
    handleRestore,
    handleRestoreRecording,
    handleRestoreDraft,
    handleClear,
    handleListenClick,
    handleRawTranscriptCopy,
    deleteKindFor,
  };
}
