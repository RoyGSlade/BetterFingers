// Pure helper for the review overlay's draft word/length summary (Phase 8).
// Kept dependency-free and in its own module so it can be unit-tested with
// `node --test` (see app/tests/draft-summary.test.mjs) and imported by the
// overlay without pulling in any DOM.

/**
 * Build the one-line summary shown under a review draft, e.g. "5 words" or
 * "1 word" or "1400 words · long draft (over 1200 words)".
 *
 * @param {string} text          the draft's final text
 * @param {number} [warningWords] word count above which the draft is "long"
 * @returns {string}
 */
export function formatDraftSummary(text, warningWords) {
  const trimmed = typeof text === 'string' ? text.trim() : '';
  const words = trimmed ? trimmed.split(/\s+/).length : 0;
  let summary = `${words} word${words === 1 ? '' : 's'}`;
  const limit = Number(warningWords);
  if (Number.isFinite(limit) && limit > 0 && words > limit) {
    summary += ` · long draft (over ${limit} words)`;
  }
  return summary;
}
