"""Voice editing commands (phrase-history aware) — sibling to
dictation_commands.py's pure formatting pass, but stateful: several of these
actions ("scratch that", "delete last word") need to know what was just
said, not just the current utterance text in isolation.

This module only classifies and transforms text; it does not decide *when*
to run (that's server.py's job, same split as voice_commands.py). Like
dictation_commands.py, these commands are always-on during active dictation
(profile-gated), not context-gated the way app-control commands are —
"scratch that" mid-dictation is expected and safe to act on, same risk
category as "new paragraph".
"""
import re
from dataclasses import dataclass, field

# Applied first, longest phrases first so a more specific phrase wins.
_COMMANDS = [
    (r"\bscratch\s+that\b", "scratch_that"),
    (r"\bundo\s+that\b", "scratch_that"),
    (r"\bundo\s+last\s+sentence\b", "delete_last_sentence"),
    (r"\bdelete\s+last\s+word\b", "delete_last_word"),
    (r"\bquote\s+that\b", "quote_that"),
    (r"\bbullet\s+list\b", "bullet_list"),
    (r"\bnumbered\s+list\b", "numbered_list"),
    (r"\bnew\s+heading\b", "new_heading"),
    (r"\bno\s+punctuation\b", "no_punctuation"),
    (r"\bliteral\s+mode\b", "literal_mode"),
]

_REPLACE_RE = re.compile(r"\breplace\s+(.+?)\s+with\s+(.+)", re.IGNORECASE)
_CAPITALIZE_RE = re.compile(r"\bcapitalize\s+(?:the\s+word\s+)?(\S+)\b", re.IGNORECASE)


@dataclass
class EditCommand:
    action: str
    args: dict = field(default_factory=dict)


def parse_edit_command(text):
    """Classify a transcript into an EditCommand, or None if it contains no
    recognized editing command. Only inspects the first match found."""
    if not text:
        return None
    lowered = text.lower()

    replace_match = _REPLACE_RE.search(lowered)
    if replace_match:
        return EditCommand(
            action="replace",
            args={"old": replace_match.group(1).strip(), "new": replace_match.group(2).strip()},
        )

    capitalize_match = _CAPITALIZE_RE.search(lowered)
    if capitalize_match:
        return EditCommand(action="capitalize_word", args={"word": capitalize_match.group(1).strip()})

    for pattern, action in _COMMANDS:
        if re.search(pattern, lowered):
            return EditCommand(action=action)

    return None


def delete_last_word(text):
    """Strip the trailing word (and any trailing whitespace/punctuation)."""
    if not text:
        return text
    return re.sub(r"\s*\S+\s*$", "", text)


def delete_last_sentence(text):
    """Strip back to the previous sentence boundary (. ! ?), or clear
    entirely if there is no earlier boundary."""
    if not text:
        return text
    trimmed = text.rstrip()
    matches = list(re.finditer(r"[.!?]", trimmed[:-1] if trimmed[-1:] in ".!?" else trimmed))
    if not matches:
        return ""
    end = matches[-1].end()
    return trimmed[:end].rstrip()


def replace_word(text, old, new):
    """Whole-word, case-insensitive replace of every occurrence of `old`
    with `new` (word-boundary safe, like macros.apply_macros)."""
    if not text or not old:
        return text
    pattern = r"\b" + re.escape(old) + r"\b"
    return re.sub(pattern, lambda _m: new, text, flags=re.IGNORECASE)


def capitalize_word(text, word):
    """Title-case every whole-word occurrence of `word` in text."""
    if not text or not word:
        return text
    pattern = r"\b" + re.escape(word) + r"\b"
    return re.sub(
        pattern,
        lambda m: m.group(0)[:1].upper() + m.group(0)[1:],
        text,
        flags=re.IGNORECASE,
    )


def quote(text):
    if not text:
        return text
    return f'"{text}"'


_STRUCTURAL_INSERTS = {
    "bullet_list": "\n- ",
    "numbered_list": "\n1. ",
    "new_heading": "\n## ",
}


def structural_insert(action):
    """Text to splice in for a structural action, or None if not structural."""
    return _STRUCTURAL_INSERTS.get(action)


_STRUCTURAL_PATTERNS = [
    (re.compile(r"\bbullet\s+list\b", re.IGNORECASE), "bullet_list"),
    (re.compile(r"\bnumbered\s+list\b", re.IGNORECASE), "numbered_list"),
    (re.compile(r"\bnew\s+heading\b", re.IGNORECASE), "new_heading"),
]
_DELETE_LAST_WORD_RE = re.compile(r"\bdelete\s+last\s+word\b", re.IGNORECASE)
_UNDO_LAST_SENTENCE_RE = re.compile(r"\bundo\s+last\s+sentence\b", re.IGNORECASE)
_QUOTE_THAT_RE = re.compile(r"\bquote\s+that\b", re.IGNORECASE)


def apply_inline_edits(text):
    """Apply editing commands that target the text preceding them within the
    same utterance ("...brown fox delete last word" -> "...brown"). This does
    NOT handle `scratch_that` — that targets the *previous* utterance via
    utterance_history, which only the caller (server.py) has access to."""
    if not text:
        return text
    result = text

    match = _DELETE_LAST_WORD_RE.search(result)
    if match:
        before = delete_last_word(result[: match.start()])
        after = result[match.end() :]
        result = (before + after).strip()

    match = _UNDO_LAST_SENTENCE_RE.search(result)
    if match:
        before = delete_last_sentence(result[: match.start()])
        after = result[match.end() :].strip()
        result = f"{before} {after}".strip() if after else before

    match = _QUOTE_THAT_RE.search(result)
    if match:
        before = result[: match.start()].strip()
        after = result[match.end() :]
        result = (quote(before) + after) if before else after.strip()

    match = _REPLACE_RE.search(result)
    if match:
        stripped = (result[: match.start()] + result[match.end() :]).strip()
        result = replace_word(stripped, match.group(1).strip(), match.group(2).strip())

    match = _CAPITALIZE_RE.search(result)
    if match:
        stripped = (result[: match.start()] + result[match.end() :]).strip()
        result = capitalize_word(stripped, match.group(1).strip())

    for pattern, action in _STRUCTURAL_PATTERNS:
        match = pattern.search(result)
        if match:
            insert = structural_insert(action)
            result = result[: match.start()].rstrip() + insert + result[match.end() :].lstrip()

    return result
