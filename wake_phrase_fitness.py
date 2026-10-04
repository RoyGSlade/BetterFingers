"""Deterministic, offline preflight for an English wake phrase.

This module deliberately does *not* listen to audio, download a model, or
claim that a phrase will work acoustically.  It catches inexpensive textual
problems before BetterFingers asks the user to record enrollment audio or lend
the app their GPU.  The final decision still belongs to real-microphone tests.

The optional ``phonemizer`` dependency is used only to add local pronunciation
evidence to the report.  Fitness scoring always uses the same built-in
heuristics, so installing (or not installing) eSpeak cannot change a verdict.
"""

from difflib import SequenceMatcher
from functools import lru_cache
import importlib
import re
import unicodedata


REPORT_VERSION = 1
SUPPORTED_LANGUAGE = "en"

# These are exact phrases that are too common to make useful wake phrases.
# Callers can add product-specific vocabulary through ``evaluate_wake_phrase``.
DEFAULT_COMMON_VOCABULARY = (
    "hello",
    "hello there",
    "hey",
    "hi",
    "okay",
    "ok",
    "yes",
    "no",
    "please",
    "thanks",
    "thank you",
    "good morning",
    "good night",
    "how are you",
    "what time is it",
    "never mind",
    "computer",
    "assistant",
)

# A wake phrase that is itself an action is ambiguous: was the person trying
# to wake BetterFingers or already asking it to do something?
DEFAULT_COMMAND_VOCABULARY = (
    "start",
    "stop",
    "cancel",
    "help",
    "open",
    "close",
    "launch",
    "play",
    "pause",
    "mute",
    "unmute",
    "record",
    "save",
    "quit",
    "exit",
    "spotify",
    "discord",
    "obs",
)

_FILLER_WORDS = {"hey", "okay", "ok"}
_VOWELS = set("aeiouy")

# This intentionally small map generates test prompts; it is not presented as
# a complete English pronunciation dictionary.  Values are ordinary words,
# deterministic, and license-free.
_CONFUSABLE_WORDS = {
    "hey": ("hay",),
    "okay": ("ok",),
    "better": ("beta", "butter"),
    "finger": ("figure", "singer"),
    "fingers": ("features", "figures", "singers"),
    "four": ("for",),
    "for": ("four",),
    "one": ("won",),
    "two": ("to", "too"),
    "to": ("too", "two"),
    "wake": ("wait", "way"),
    "night": ("knight", "light"),
    "write": ("right",),
    "right": ("write",),
    "play": ("place",),
}

_MULTIGRAPHS = ("tch", "dge", "ch", "sh", "th", "ph", "ng", "qu", "ck", "wh")
_SOUNDEX_CODES = {
    **dict.fromkeys("bfpv", "1"),
    **dict.fromkeys("cgjkqsxz", "2"),
    **dict.fromkeys("dt", "3"),
    "l": "4",
    **dict.fromkeys("mn", "5"),
    "r": "6",
}


def normalize_phrase(value):
    """Return the stable lowercase form used by the fitness evaluator.

    Punctuation is treated as a boundary, apostrophes inside an English word
    are retained, and no transliteration is attempted.  Unsupported scripts
    are reported separately by :func:`evaluate_wake_phrase`.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return " ".join(re.findall(r"[a-z]+(?:'[a-z]+)?", text))


def _unsupported_characters(value):
    if value is None:
        return []
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    unsupported = {
        char
        for char in text
        if char.isdigit() or (char.isalpha() and not ("a" <= char <= "z"))
    }
    return sorted(unsupported)


def _word_syllables(word):
    letters = re.sub(r"[^a-z]", "", word)
    if not letters:
        return 0
    groups = len(re.findall(r"[aeiouy]+", letters))
    if letters.endswith("e") and not letters.endswith(("le", "ye")) and groups > 1:
        groups -= 1
    return max(1, groups)


def _estimated_phonemes(word):
    """Conservative spelling-based sound-unit estimate, not an IPA parser."""
    letters = re.sub(r"[^a-z]", "", word)
    if not letters:
        return 0
    count = 0
    index = 0
    while index < len(letters):
        if (
            index == len(letters) - 1
            and letters[index] == "e"
            and len(letters) > 2
            and _word_syllables(letters) == 1
        ):
            index += 1
            continue
        matched = next((item for item in _MULTIGRAPHS if letters.startswith(item, index)), None)
        if matched:
            count += 1
            index += len(matched)
            continue
        char = letters[index]
        if char in _VOWELS:
            count += 1
            index += 1
            while index < len(letters) and letters[index] in _VOWELS:
                index += 1
            continue
        if char == "x":
            count += 2
        elif index == 0 or char != letters[index - 1]:
            count += 1
        index += 1
    return max(1, count)


def _soundex(word):
    letters = re.sub(r"[^a-z]", "", word)
    if not letters:
        return ""
    first = letters[0].upper()
    previous = _SOUNDEX_CODES.get(letters[0], "")
    digits = []
    for char in letters[1:]:
        code = _SOUNDEX_CODES.get(char, "")
        if code and code != previous:
            digits.append(code)
        previous = code
    return (first + "".join(digits) + "000")[:4]


def _phonetic_signature(words):
    return "-".join(filter(None, (_soundex(word) for word in words)))


@lru_cache(maxsize=256)
def _optional_pronunciation(phrase):
    """Return local eSpeak IPA when available, otherwise ``None``.

    Import, backend, and data failures are all expected deployment states.
    They must never prevent the deterministic heuristic report from working.
    """
    try:
        module = importlib.import_module("phonemizer")
        pronunciation = module.phonemize(
            phrase,
            language="en-us",
            backend="espeak",
            strip=True,
            preserve_punctuation=False,
            with_stress=False,
            njobs=1,
        )
    except Exception:
        return None
    pronunciation = " ".join(str(pronunciation or "").split())
    return pronunciation or None


def _extend_vocabulary(defaults, extra):
    values = list(defaults)
    if extra is not None:
        if isinstance(extra, str):
            values.append(extra)
        else:
            try:
                values.extend(extra)
            except TypeError:
                values.append(extra)
    return tuple(sorted({normalize_phrase(value) for value in values if normalize_phrase(value)}))


def _contains_phrase(container, candidate):
    container_words = container.split()
    candidate_words = candidate.split()
    width = len(candidate_words)
    if not width or width > len(container_words):
        return False
    return any(container_words[index:index + width] == candidate_words
               for index in range(len(container_words) - width + 1))


def _similarity(left, right):
    left_words = left.split()
    right_words = right.split()
    compact_left = "".join(left_words)
    compact_right = "".join(right_words)
    spelling = SequenceMatcher(None, compact_left, compact_right).ratio()
    phonetic = SequenceMatcher(
        None, _phonetic_signature(left_words), _phonetic_signature(right_words)
    ).ratio()
    left_set, right_set = set(left_words), set(right_words)
    token_overlap = len(left_set & right_set) / max(1, len(left_set | right_set))
    return round((0.55 * spelling) + (0.30 * phonetic) + (0.15 * token_overlap), 4)


def _split_compound(word, known_words):
    if len(word) < 6:
        return None
    options = []
    for index in range(3, len(word) - 2):
        left, right = word[:index], word[index:]
        if left in known_words and right in known_words:
            options.append((left, right))
    if not options:
        return None
    return min(options, key=lambda pair: (abs(len(pair[0]) - len(pair[1])), pair))


def _near_confusers(phrase, common_vocabulary, command_vocabulary, limit=10):
    if not phrase:
        return []
    words = phrase.split()
    known_words = set(_CONFUSABLE_WORDS)
    for alternatives in _CONFUSABLE_WORDS.values():
        known_words.update(alternatives)
    for value in common_vocabulary + command_vocabulary:
        known_words.update(value.split())

    forms = [words]
    split_form = []
    for word in words:
        split_form.extend(_split_compound(word, known_words) or (word,))
    if split_form != words:
        forms.append(split_form)

    generated = set()
    for form in forms:
        joined = " ".join(form)
        if joined != phrase:
            generated.add(joined)
        if len(form) > 1:
            for index in range(len(form)):
                generated.add(" ".join(form[:index] + form[index + 1:]))
        for index, word in enumerate(form):
            for replacement in _CONFUSABLE_WORDS.get(word, ()):
                variant = list(form)
                variant[index] = replacement
                generated.add(" ".join(variant))

    candidates = generated | set(common_vocabulary) | set(command_vocabulary)
    candidates.discard(phrase)
    ranked = []
    for candidate in candidates:
        candidate = normalize_phrase(candidate)
        if not candidate or candidate == phrase:
            continue
        similarity = _similarity(phrase, candidate)
        if candidate in generated or similarity >= 0.48:
            ranked.append((similarity, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, candidate in ranked[:max(0, int(limit))]]


def evaluate_wake_phrase(phrase, command_vocabulary=None, common_vocabulary=None):
    """Return a JSON-serializable English wake-phrase fitness report.

    Optional vocabularies extend the built-in common-speech and command lists;
    they never replace the baseline safety checks.  ``verdict`` is one of
    ``good``, ``workable``, or ``reject``.  It predicts textual suitability
    only, so every report explicitly requires later real-microphone testing.
    """
    normalized = normalize_phrase(phrase)
    words = normalized.split()
    unsupported = _unsupported_characters(phrase)
    common = _extend_vocabulary(DEFAULT_COMMON_VOCABULARY, common_vocabulary)
    commands = _extend_vocabulary(DEFAULT_COMMAND_VOCABULARY, command_vocabulary)

    syllables = sum(_word_syllables(word) for word in words)
    phonemes = sum(_estimated_phonemes(word) for word in words)
    letter_count = sum(char.isalpha() for char in normalized)
    score = 100
    hard_reject = False
    reasons = []

    if not normalized:
        hard_reject = True
        score = 0
        reasons.append("Enter a wake phrase containing English words.")
    if unsupported:
        hard_reject = True
        score = min(score, 20)
        reasons.append("English-only V1 does not accept digits or non-English letters.")

    if normalized:
        if letter_count < 4 or syllables < 2 or phonemes < 6:
            hard_reject = True
            score = min(score, 30)
            reasons.append(
                "The phrase is too short or acoustically thin; use at least two syllables "
                "and roughly six sound units."
            )
        elif 3 <= syllables <= 6:
            reasons.append("The estimated length is inside the preferred 3-6 syllable range.")
        elif syllables == 2:
            score -= 25
            reasons.append("Two syllables can work, but leave less room to reject similar speech.")
        elif 7 <= syllables <= 8:
            score -= 20
            reasons.append("The phrase is longer than ideal and may feel slow to repeat.")
        else:
            hard_reject = True
            score = min(score, 40)
            reasons.append("The phrase is too long for a practical wake interaction.")

        if len(words) > 6:
            hard_reject = True
            score = min(score, 40)
            reasons.append("Use no more than six words for the V1 wake phrase.")
        elif len(words) >= 5:
            score -= 15
            reasons.append("Five or more words increase latency and pronunciation variation.")

        if phonemes in (6, 7) and not hard_reject:
            score -= 10
            reasons.append("The estimated sound-unit count is usable but still borderline.")

        if len(words) > 1 and len(set(words)) / len(words) < 0.6:
            score -= 25
            reasons.append("Repeated words make the phrase less distinctive.")

        if normalized in common:
            hard_reject = True
            score = min(score, 20)
            reasons.append("The phrase is common everyday speech and would invite false wakes.")
        if normalized in commands:
            hard_reject = True
            score = min(score, 20)
            reasons.append("The phrase is already a command and cannot cleanly separate wake from action.")

        contained_commands = tuple(
            item for item in commands if item != normalized and _contains_phrase(normalized, item)
        )
        if contained_commands:
            score -= 25
            reasons.append("The phrase contains command vocabulary that may also occur after waking.")

        contained_common = tuple(
            item
            for item in common
            if item != normalized
            and item not in _FILLER_WORDS
            and _contains_phrase(normalized, item)
        )
        if contained_common:
            score -= 15
            reasons.append("Part of the phrase is common speech, so real-world confuser testing matters.")

        near_common = sorted(
            (
                (_similarity(normalized, item), item)
                for item in common + commands
                if item != normalized
            ),
            key=lambda item: (-item[0], item[1]),
        )
        nearest_score = near_common[0][0] if near_common else 0.0
        nearest_phrase = near_common[0][1] if near_common else None
        if nearest_score >= 0.90 and not contained_commands and not contained_common:
            score -= 30
            reasons.append("The phrase closely resembles common speech or an existing command.")
        elif nearest_score >= 0.82 and not contained_commands and not contained_common:
            score -= 15
            reasons.append("The phrase has a possible vocabulary collision to test aloud.")
    else:
        nearest_score = 0.0
        nearest_phrase = None
        contained_commands = ()
        contained_common = ()

    score = max(0, min(100, int(score)))
    if hard_reject or score < 55:
        verdict = "reject"
    elif score < 85:
        verdict = "workable"
    else:
        verdict = "good"

    if normalized and not hard_reject and not any("collision" in reason for reason in reasons):
        reasons.append("No direct collision with the supplied vocabulary was found.")
    reasons.append("Text preflight cannot guarantee acoustic success; real microphone testing is required.")

    pronunciation = _optional_pronunciation(normalized) if normalized and not unsupported else None
    confusers = _near_confusers(normalized, common, commands)
    return {
        "version": REPORT_VERSION,
        "language": SUPPORTED_LANGUAGE,
        "normalized_phrase": normalized,
        "verdict": verdict,
        "score": score,
        "reasons": reasons,
        "evidence": {
            "word_count": len(words),
            "letter_count": letter_count,
            "estimated_syllables": syllables,
            "estimated_phonemes": phonemes,
            "phonetic_signature": _phonetic_signature(words),
            "pronunciation": pronunciation,
            "pronunciation_source": "phonemizer_espeak" if pronunciation else "heuristic_only",
            "unsupported_characters": unsupported,
            "nearest_vocabulary_phrase": nearest_phrase,
            "nearest_vocabulary_similarity": nearest_score,
            "contained_commands": list(contained_commands),
            "contained_common_phrases": list(contained_common),
        },
        "near_confusers": confusers,
        "acoustic_test_required": True,
    }

