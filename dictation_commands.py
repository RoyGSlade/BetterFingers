"""Spoken dictation commands (C2): turn spoken formatting words into real
formatting — a pure text pass, so it is fully unit-testable.

Handles the low-ambiguity, high-value cases:
  - structure: "new paragraph" -> blank line, "new line" -> line break,
    "new sentence" -> ". "
  - spoken punctuation: "period", "comma", "question mark", etc.
  - casing: "all caps WORD", "caps/capital WORD"

Note: spoken punctuation words are inherently ambiguous with ordinary speech
(e.g. "the Victorian period"). This whole pass is gated behind a per-profile
toggle so it can be turned off, and matching is word-boundary safe so it never
fires inside a larger word (e.g. "periodic").
"""
import re

# Applied first, longest phrases first so "new paragraph" wins over "new".
_STRUCTURAL = [
    (r"\bnew\s+paragraph\b", "\n\n"),
    (r"\bnew\s+line\b", "\n"),
    (r"\bnext\s+line\b", "\n"),
    (r"\bnew\s+sentence\b", ". "),
]

# Spoken punctuation -> mark. Multi-word keys are matched before single-word.
_PUNCTUATION = {
    "full stop": ".",
    "period": ".",
    "comma": ",",
    "question mark": "?",
    "exclamation mark": "!",
    "exclamation point": "!",
    "semicolon": ";",
    "colon": ":",
    "open parenthesis": "(",
    "open paren": "(",
    "close parenthesis": ")",
    "close paren": ")",
}


def _apply_casing(text):
    # "all caps foo" -> "FOO"
    text = re.sub(
        r"\ball\s+caps\s+([A-Za-z][A-Za-z'-]*)",
        lambda m: m.group(1).upper(),
        text,
        flags=re.IGNORECASE,
    )
    # "caps foo" / "capital foo" -> "Foo"
    text = re.sub(
        r"\b(?:caps|capital)\s+([A-Za-z][A-Za-z'-]*)",
        lambda m: m.group(1)[:1].upper() + m.group(1)[1:],
        text,
        flags=re.IGNORECASE,
    )
    return text


def _apply_punctuation(text):
    for phrase in sorted(_PUNCTUATION, key=len, reverse=True):
        mark = _PUNCTUATION[phrase]
        pattern = r"\s*\b" + re.escape(phrase) + r"\b"
        text = re.sub(pattern, mark, text, flags=re.IGNORECASE)
    return text


def _normalize_spacing(text):
    # No space before . , ; : ? ! ) — exactly one space after them.
    text = re.sub(r"\s+([.,;:?!)])", r"\1", text)
    text = re.sub(r"([.,;:?!)])(?=[^\s.,;:?!)\n])", r"\1 ", text)
    # A space before an opening paren that follows a word; none after it.
    text = re.sub(r"(\w)\(", r"\1 (", text)
    text = re.sub(r"\(\s+", "(", text)
    # Collapse runs of spaces/tabs (but keep newlines from structural commands).
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Capitalize the first letter after sentence-ending punctuation.
    text = re.sub(
        r"([.?!]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )
    # Tidy whitespace around the newlines we inserted.
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def apply_commands(text):
    """Apply spoken dictation commands to a transcript. Idempotent-ish and safe
    on text with no commands (returns it essentially unchanged)."""
    if not text:
        return text
    result = text
    for pattern, replacement in _STRUCTURAL:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = _apply_casing(result)
    result = _apply_punctuation(result)
    result = _normalize_spacing(result)
    return result
