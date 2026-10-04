"""One negation rule for every spoken-command parser.

"Don't scratch that" must not scratch, "do not delete last word" must not delete
a word, "don't send it" must not send. But "send it, no problem", "not bad, send
it", "never mind, send it" and "no, send it" are all plain commands with a
harmless "no"/"not"/"never" next to them. A veto over the whole utterance (the
first cut, 253a626) gets the first set right and the second set wrong; this
rule gets both.

A command is negated when a negation word GOVERNS it:

* BEFORE it: a negation word in the same clause, with at most ``MAX_GAP_WORDS``
  words between it and the command ("don't scratch that", "no don't undo that",
  "I told you not to quote that", "never send it"). A clause ends at , . ; : ! ?
  so "I can't make it tomorrow. Scratch that." and "no, send it" are not negated.
* AFTER it, as a retraction: whatever follows the command is nothing but
  negation words ("send it? No, don't.", "scratch that, never mind").

Benign idioms are blanked out first ("no problem", "no worries", "no changes",
"not bad", "don't worry", "nothing else", "no need," ...), and "never mind"
before a command is a discourse marker, not a negation. A negation word that is
part of the command's own phrase ("no punctuation") or its argument ("replace
yes with no") is outside the scanned regions and never counts.

Pure text -> bool, no side effects. Used by ``voice_commands.parse_command`` and
``voice_edit_commands`` (``parse_edit_command`` and ``apply_inline_edits``) so
the app commands and the commands that run during dictation cannot disagree.
It only ever decides whether a COMMAND fires; dictated text is never altered.
"""
import re

# Words allowed between a negation and the command it governs ("don't ever
# scratch that", "do not want you to delete last word").
MAX_GAP_WORDS = 3

# Clause breaks: , . ; : ! ? em dash, en dash, ellipsis, newline. Built from code
# points so the source stays plain ASCII.
_BREAKS = ",.;:!?" + "".join(map(chr, (0x2014, 0x2013, 0x2026, 10)))
_BREAK_CLASS = "[" + re.escape(_BREAKS) + "]"

_NEGATION = (
    r"(?:no|nope|nah|not|never|cannot"
    r"|(?:don|won|can|shouldn|wouldn|couldn|mustn|isn|aren|wasn|weren|haven|hasn|hadn|didn|doesn)'?t)"
)
NEGATION_RE = re.compile(r"\b" + _NEGATION + r"\b")

# Idioms where the negation word does not negate a command. Blanked (not
# removed) so every character offset the caller holds stays valid.
_BENIGN_RE = re.compile(
    r"\b(?:"
    r"no\s+(?:problems?|worr(?:y|ies)|rush|hurry|biggie|big\s+deal|doubt|matter"
    r"|(?:changes?|edits?|updates?|corrections?|errors?|typos?|mistakes?|issues?|concerns?|questions?))"
    r"|no\s+need(?=\s*(?:" + _BREAK_CLASS + r"|$))"  # "no need," yes; "no need to send it" no
    r"|not\s+(?:bad|too\s+bad|(?:a|an)\s+(?:problem|issue))"
    r"|(?:don'?t|do\s+not)\s+worry"
    r"|nothing\s+else"
    r")\b"
)
_NEVER_MIND_RE = re.compile(r"\bnever\s*mind\b")
# "No, ..." / "Nope. ..." at the very start of an utterance with no clause in
# front of it: an interjection, not a negation of what follows.
_LEADING_NO_RE = re.compile(r"^\s*(?:(?:no|nope|nah)\s*" + _BREAK_CLASS + r"+\s*)+")
_WORD_RE = re.compile(r"[a-z0-9']+")

_RETRACTION_WORD = r"(?:never\s*mind|" + _NEGATION + r"|please|actually|now|thanks?|wait)"
_RETRACTION_TOKEN_RE = re.compile(_RETRACTION_WORD)  # the tail run holds only retraction words
# The trailing run of retraction words, if the utterance ends with one.
_TAIL_RE = re.compile(
    r"(?:^|(?<=[\s" + re.escape(_BREAKS) + r"]))"
    r"((?:" + _RETRACTION_WORD + r"\b[\s" + re.escape(_BREAKS) + r"]*)+)$"
)

# Right/left single quotation mark, modifier letter apostrophe, prime.
_APOSTROPHES = str.maketrans({0x2019: "'", 0x2018: "'", 0x02BC: "'", 0x2032: "'"})


def _fold(text):
    """Lower-case and straighten apostrophes, keeping every offset unchanged
    (a character whose lower-case form is longer is left as it was)."""
    lowered = "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)
    return lowered.translate(_APOSTROPHES)


def _blank(match):
    return " " * len(match.group(0))


def is_negated(text, start=None, end=None):
    """True when a negation governs the command at ``text[start:end]``.

    ``start``/``end`` are offsets into ``text`` (any case, any apostrophe) of the
    matched command phrase. With no span the whole utterance is the command (the
    fuzzy whole-utterance match): any negation word left after the benign
    idioms, a leading "no," and "never mind" are ignored counts.
    """
    if not text:
        return False
    folded = _BENIGN_RE.sub(_blank, _fold(text))
    if start is None:
        return _whole_utterance_is_negated(folded)
    return _negated_before(folded, start) or _retracted_after(folded, start, start if end is None else end)


def _whole_utterance_is_negated(folded):
    body = _NEVER_MIND_RE.sub(_blank, folded)
    body = _LEADING_NO_RE.sub(_blank, body)
    return NEGATION_RE.search(body) is not None


def _negated_before(folded, start):
    head = folded[:start]
    clause_start = max(head.rfind(ch) for ch in _BREAKS) + 1
    # "never mind <command>" dismisses what came before; it is not a refusal.
    clause = _NEVER_MIND_RE.sub(_blank, head[clause_start:])
    hits = list(NEGATION_RE.finditer(clause))
    if not hits:
        return False
    return len(_WORD_RE.findall(clause[hits[-1].end():])) <= MAX_GAP_WORDS


def _has_negative(text):
    return NEGATION_RE.search(text) is not None or _NEVER_MIND_RE.search(text) is not None


def _retracted_after(folded, start, end):
    tail = _TAIL_RE.search(folded)
    if tail is None:
        return False
    tail_start = tail.start(1)
    if tail_start >= end:
        # Right behind the command, with no other words in between, and with
        # something negative in it ("send it please" is not a retraction).
        return _WORD_RE.search(folded[end:tail_start]) is None and _has_negative(tail.group(1))
    # The run reaches into a free-text argument ("replace foo with bar, no
    # don't"; "replace yes with no, no don't"). Only a part of it introduced by
    # a clause break is a retraction: "replace yes with no" ends in a word of the
    # argument, not in a retraction.
    for token in _RETRACTION_TOKEN_RE.finditer(tail.group(1)):
        position = tail_start + token.start()
        if position <= start:
            continue
        before = folded[:position].rstrip()
        if before and before[-1] in _BREAKS and _has_negative(folded[position:]):
            return True
    return False
