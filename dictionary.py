"""Personal dictionary (C1): user-specific terms that bias transcription and fix
common mishears.

Two levers:
  1. hotwords — the terms are handed to faster-whisper as `hotwords`, biasing the
     ASR toward them (the biggest quality win, and lossless).
  2. post-ASR correction — a conservative, dependency-free fuzzy pass (stdlib
     difflib) that snaps near-miss single tokens back to a dictionary term.

Kept deliberately cautious: only fairly long tokens with a strong similarity match
are corrected, so ordinary words are never mangled.
"""
import difflib
import json
import logging
import os
import re
import threading

from utils import get_user_data_path

_lock = threading.RLock()

# Only correct tokens at least this long, and only when similarity is at least
# this high — both guard against mangling ordinary words.
MIN_TOKEN_LEN = 4
SIMILARITY_CUTOFF = 0.82


def _dictionary_path():
    return os.path.join(get_user_data_path(), "dictionary.json")


def get_terms():
    """Return the list of dictionary terms (strings), preserving canonical casing."""
    with _lock:
        try:
            with open(_dictionary_path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
    if isinstance(data, dict):
        data = data.get("terms", [])
    terms = []
    seen = set()
    for item in data or []:
        term = str(item).strip()
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def _save_terms(terms):
    with _lock:
        try:
            with open(_dictionary_path(), "w", encoding="utf-8") as handle:
                json.dump({"terms": terms}, handle, indent=2)
        except OSError as exc:
            logging.warning(f"Failed to save dictionary: {exc}")


def add_term(term):
    term = str(term or "").strip()
    if not term:
        return get_terms()
    terms = get_terms()
    if term.lower() not in {t.lower() for t in terms}:
        terms.append(term)
        _save_terms(terms)
    return terms


def remove_term(term):
    term = str(term or "").strip().lower()
    terms = [t for t in get_terms() if t.lower() != term]
    _save_terms(terms)
    return terms


def hotwords_string(terms=None):
    """faster-whisper takes a single space-joined hotwords string (or None)."""
    terms = terms if terms is not None else get_terms()
    joined = " ".join(t for t in terms if t)
    return joined or None


def correct_text(text, terms=None):
    """Snap near-miss tokens to dictionary terms. Conservative and casing-aware."""
    terms = terms if terms is not None else get_terms()
    if not text or not terms:
        return text

    # Only single-word terms participate in token-level correction; multi-word
    # terms are handled by the hotwords bias instead.
    single = [t for t in terms if " " not in t]
    if not single:
        return text
    lower_to_canonical = {t.lower(): t for t in single}
    candidates = list(lower_to_canonical.keys())

    def fix(match):
        word = match.group(0)
        if len(word) < MIN_TOKEN_LEN:
            return word
        low = word.lower()
        if low in lower_to_canonical:
            canonical = lower_to_canonical[low]
            return _match_case(word, canonical)
        close = difflib.get_close_matches(low, candidates, n=1, cutoff=SIMILARITY_CUTOFF)
        if close:
            return _match_case(word, lower_to_canonical[close[0]])
        return word

    return re.sub(r"[A-Za-z][A-Za-z'\-]*", fix, text)


def _match_case(original, canonical):
    """Preserve the original token's leading capitalization on the replacement."""
    if original.isupper() and len(original) > 1:
        return canonical.upper()
    if original[:1].isupper():
        return canonical[:1].upper() + canonical[1:]
    return canonical


# Common words that are never worth proposing as personal-dictionary terms.
_STOPWORDS = {
    "this", "that", "with", "from", "have", "will", "your", "they", "them", "then",
    "than", "were", "what", "when", "which", "there", "their", "would", "could",
    "should", "about", "into", "over", "just", "like", "some", "more", "most",
    "also", "here", "very", "only", "even", "much", "many", "such", "does",
}


def suggest_from_edit(raw_text, edited_text, existing=None):
    """Auto-learn (C1c): propose dictionary terms from how the user edited a draft.

    Words present in the edited text but not the raw transcript — and not already
    known — are candidate personal terms (names, jargon the ASR missed).
    """
    existing = {t.lower() for t in (existing if existing is not None else get_terms())}
    raw_words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", raw_text or "")}
    suggestions = []
    seen = set()
    for word in re.findall(r"[A-Za-z][A-Za-z'\-]+", edited_text or ""):
        low = word.lower()
        if len(word) < MIN_TOKEN_LEN:
            continue
        if low in raw_words or low in existing or low in seen or low in _STOPWORDS:
            continue
        seen.add(low)
        suggestions.append(word)
    return suggestions
