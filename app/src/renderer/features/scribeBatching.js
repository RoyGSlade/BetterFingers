export const LONG_INPUT_THRESHOLD_WORDS = 500;
export const BATCH_CHOICES = Object.freeze([
  { id: '250', label: '250 words per batch', words: 250, recommended: false },
  { id: '500', label: '500 words per batch', words: 500, recommended: true },
  { id: 'full', label: 'Process as one request', words: null, recommended: false },
]);

export function countWords(text) {
  return String(text || '').trim().split(/\s+/u).filter(Boolean).length;
}

export function needsLongInputChoice(text, thresholdWords = LONG_INPUT_THRESHOLD_WORDS) {
  return countWords(text) > Math.max(1, Number(thresholdWords) || LONG_INPUT_THRESHOLD_WORDS);
}

function blockRanges(text) {
  const ranges = [];
  const regex = /```[\s\S]*?```|(?:^|\n)(?:[^\n]+\n?)+?(?=\n\s*\n|$)/g;
  let match;
  while ((match = regex.exec(text))) {
    const value = match[0].replace(/^\n/, '');
    if (value.trim()) ranges.push(value);
  }
  return ranges.length ? ranges : [text];
}

function splitOversizeBlock(block, targetWords) {
  if (countWords(block) <= targetWords) return [block];
  const sentences = block.match(/[^.!?\n]+(?:[.!?]+["')\]]*|$)\s*/g)?.filter((part) => part.trim()) || [];
  if (sentences.length <= 1) {
    const words = block.match(/\S+\s*/g) || [];
    const chunks = [];
    for (let index = 0; index < words.length; index += targetWords) {
      chunks.push(words.slice(index, index + targetWords).join('').trimEnd());
    }
    return chunks;
  }
  return packUnits(sentences, targetWords);
}

function packUnits(units, targetWords) {
  const chunks = [];
  let current = [];
  let currentWords = 0;
  for (const unit of units) {
    const words = countWords(unit);
    if (current.length && currentWords + words > targetWords) {
      chunks.push(current.join('').trim());
      current = [];
      currentWords = 0;
    }
    if (words > targetWords) {
      if (current.length) chunks.push(current.join('').trim());
      chunks.push(...splitOversizeBlock(unit, targetWords));
      current = [];
      currentWords = 0;
    } else {
      current.push(unit);
      currentWords += words;
    }
  }
  if (current.length) chunks.push(current.join('').trim());
  return chunks.filter(Boolean);
}

export function effectiveBatchWords(requestedWords, { contextTokens, reservedOutputTokens = 1100 } = {}) {
  const requested = Math.max(50, Number(requestedWords) || 500);
  const tokens = Number(contextTokens);
  if (!Number.isFinite(tokens) || tokens <= 0) return requested;
  // Conservative English estimate plus room for persona/preset/system text.
  const availableInputTokens = Math.max(256, tokens - Math.max(256, Number(reservedOutputTokens) || 1100) - 900);
  const contextWordLimit = Math.max(50, Math.floor(availableInputTokens * 0.7));
  return Math.min(requested, contextWordLimit);
}

export function splitLongInput(text, requestedWords = 500, limits = {}) {
  const source = String(text || '').trim();
  if (!source) return [];
  const targetWords = effectiveBatchWords(requestedWords, limits);
  const blocks = blockRanges(source).flatMap((block) => splitOversizeBlock(block, targetWords));
  return packUnits(blocks.map((block, index) => `${index ? '\n\n' : ''}${block}`), targetWords);
}

export function createBatchOperation(chunks) {
  return {
    chunks: Array.isArray(chunks) ? chunks.slice() : [],
    completed: [],
    index: 0,
    state: 'preparing',
    failedIndex: null,
    error: '',
  };
}

export function recordBatchSuccess(operation, result) {
  const completed = operation.completed.slice();
  completed[operation.index] = result;
  const nextIndex = operation.index + 1;
  return {
    ...operation,
    completed,
    index: nextIndex,
    state: nextIndex >= operation.chunks.length ? 'completed' : 'processing',
    failedIndex: null,
    error: '',
  };
}

export function recordBatchFailure(operation, error) {
  return { ...operation, state: 'paused', failedIndex: operation.index, error: String(error || 'Chunk failed.') };
}

export function resumeBatch(operation) {
  if (operation.state !== 'paused') return operation;
  return { ...operation, state: 'retrying', index: operation.failedIndex ?? operation.index, error: '' };
}

export function cancelBatch(operation) {
  return { ...operation, state: 'cancelled' };
}

const COMBINED_PROTECTED_PATTERNS = Object.freeze([
  ['numbers', /\b\d+(?:[.:/-]\d+)*\b/gu, true],
  ['urls', /\bhttps?:\/\/[^\s<>{}\[\]]+/giu, true],
  ['negation', /\b(?:not|never|none|nobody|nothing|nowhere|neither|nor|without|no|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't|wouldn't|shouldn't|couldn't)\b/giu, false],
  ['modality', /\b(?:can|could|may|might|must|shall|should|will|would|won't|can't|couldn't|shouldn't|wouldn't)\b/giu, false],
  ['commands', /\b(?:sudo\s+)?(?:systemctl|docker|git|npm|python\d*|pip\d*|kubectl)\s+[^\n.!?]+/giu, true],
]);

function uniqueMatches(text, pattern) {
  pattern.lastIndex = 0;
  return Array.from(new Set(Array.from(String(text || '').matchAll(pattern), (match) => match[0])));
}

export function validateCombinedProtectedValues(sourceText, candidateText, label = 'combined') {
  const candidate = String(candidateText || '');
  const checks = [];
  for (const [category, pattern, caseSensitive] of COMBINED_PROTECTED_PATTERNS) {
    const required = uniqueMatches(sourceText, pattern);
    if (!required.length) continue;
    const haystack = caseSensitive ? candidate : candidate.toLocaleLowerCase();
    const missing = required.filter((token) => !haystack.includes(caseSensitive ? token : token.toLocaleLowerCase()));
    checks.push({
      name: `${label}/${category}`,
      passed: missing.length === 0,
      detail: missing.length ? `missing after assembly: ${missing.slice(0, 5).join(', ')}` : 'preserved',
    });
  }
  return checks;
}

export function assembleBatchResults(results, sourceText = '') {
  const clean = (Array.isArray(results) ? results : []).filter(Boolean);
  const keys = ['faithful', 'clearer', 'alternate'];
  const variants = Object.fromEntries(keys.map((key) => [
    key,
    clean.map((result) => String(result?.variants?.[key] || '').trim()).filter(Boolean).join('\n\n'),
  ]));
  const combinedChecks = [];
  const warnings = clean.flatMap((result) => result?.warnings || []);
  if (String(sourceText || '').trim()) {
    for (const key of keys) {
      if (!variants[key]) continue;
      const checks = validateCombinedProtectedValues(sourceText, variants[key], `combined/${key}`);
      combinedChecks.push(...checks);
      if (checks.some((check) => !check.passed)) {
        if (key === 'faithful') variants[key] = String(sourceText).trim();
        else variants[key] = '';
        warnings.push(`${key} assembled output failed combined preservation validation`);
      }
    }
  }
  return {
    ...(clean[clean.length - 1] || {}),
    variants,
    preservation_checks: clean.flatMap((result) => result?.preservation_checks || []).concat(combinedChecks),
    warnings,
    batch: { completed_chunks: clean.length, complete: true },
  };
}
