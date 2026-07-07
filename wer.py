"""
Word Error Rate (WER) — pure, dependency-free transcript scoring.

Used by the golden-audio regression harness to compare an STT hypothesis
against a reference transcript. Implemented with a word-level Levenshtein
alignment so we can report substitution / deletion / insertion counts, not
just the aggregate rate.

Deliberately stdlib-only (no jiwer / numpy) so it runs anywhere the test
suite runs and never breaks the pipeline.
"""

import re
import unicodedata

# Characters stripped when normalizing for a fair word comparison.
_PUNCT_RE = re.compile(r"[^\w\s']", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+", flags=re.UNICODE)


def normalize(text):
    """Lower-case, strip punctuation, collapse whitespace. Unicode-safe."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.casefold()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def tokenize(text):
    """Return the normalized word tokens of `text`."""
    normalized = normalize(text)
    return normalized.split(" ") if normalized else []


def _align(ref_tokens, hyp_tokens):
    """
    Word-level Levenshtein alignment.

    Returns (substitutions, deletions, insertions, hits) counted over the
    minimum-edit path. Deletions = words in ref missing from hyp;
    insertions = extra words in hyp not in ref.
    """
    n = len(ref_tokens)
    m = len(hyp_tokens)

    # dp[i][j] = edit distance between ref[:i] and hyp[:j]
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j - 1],  # substitution
                    dp[i - 1][j],      # deletion (ref word dropped)
                    dp[i][j - 1],      # insertion (extra hyp word)
                )

    # Backtrace, preferring diagonal (match/sub) then deletion then insertion.
    subs = dels = ins = hits = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref_tokens[i - 1] == hyp_tokens[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            hits += 1
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            subs += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return subs, dels, ins, hits


def compare_transcripts(reference, hypothesis):
    """
    Compare a reference transcript against a hypothesis.

    Returns a dict:
      {
        "wer": float,            # (S + D + I) / N, clamped >= 0.0
        "substitutions": int,
        "deletions": int,
        "insertions": int,
        "hits": int,
        "ref_words": int,        # N
        "hyp_words": int,
      }

    Edge cases:
      * empty reference + empty hypothesis -> wer 0.0
      * empty reference + non-empty hypothesis -> wer 1.0 (all insertions)
    """
    ref_tokens = tokenize(reference)
    hyp_tokens = tokenize(hypothesis)
    n = len(ref_tokens)

    subs, dels, ins, hits = _align(ref_tokens, hyp_tokens)
    errors = subs + dels + ins

    if n == 0:
        wer_value = 0.0 if len(hyp_tokens) == 0 else 1.0
    else:
        wer_value = errors / n

    return {
        "wer": wer_value,
        "substitutions": subs,
        "deletions": dels,
        "insertions": ins,
        "hits": hits,
        "ref_words": n,
        "hyp_words": len(hyp_tokens),
    }


def word_error_rate(reference, hypothesis):
    """Convenience wrapper returning just the WER float."""
    return compare_transcripts(reference, hypothesis)["wer"]
