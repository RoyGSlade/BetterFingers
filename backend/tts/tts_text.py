"""Text normalization for TTS (U5): make written text speak naturally.

Pure, dependency-free string transforms (no Kokoro/ONNX), so they are fully
unit-testable. Complements the existing pronunciation map + sentence-boundary
chunking in tts_engine.py (the chunker already splits on sentence/clause/word
boundaries, so it is not reimplemented here).
"""
import re

# Written abbreviation -> spoken form. Order matters (longest/most-specific first).
_ABBREVIATIONS = [
    (r"\be\.g\.", "for example"),
    (r"\bi\.e\.", "that is"),
    (r"\betc\.", "etcetera"),
    (r"\bapprox\.", "approximately"),
    (r"\bDept\.", "Department"),
    (r"\bFig\.", "Figure"),
    (r"\bProf\.", "Professor"),
    (r"\bDr\.", "Doctor"),
    (r"\bMrs\.", "Missus"),
    (r"\bMr\.", "Mister"),
    (r"\bMs\.", "Miss"),
    (r"\bSt\.", "Saint"),
    (r"\bvs\.?(?=\s|$)", "versus"),
    (r"\bNo\.\s*(?=\d)", "number "),
]


def _speak_currency(match):
    whole = match.group(1)
    cents = match.group(2)
    unit = "dollar" if whole == "1" and not cents else "dollars"
    if cents:
        cents_num = cents if len(cents) == 2 else (cents + "0")
        cents_word = "cent" if cents_num == "01" else "cents"
        return f"{whole} {unit} and {int(cents_num)} {cents_word}"
    return f"{whole} {unit}"


def normalize_for_speech(text):
    """Expand abbreviations, currency, percentages, and a few symbols so a TTS
    voice reads them naturally. Conservative and safe on plain text."""
    if not text:
        return text
    result = text

    for pattern, replacement in _ABBREVIATIONS:
        result = re.sub(pattern, replacement, result)

    # Currency: $5 -> "5 dollars", $5.50 -> "5 dollars and 50 cents".
    result = re.sub(r"\$\s?(\d+)(?:\.(\d{1,2}))?", _speak_currency, result)

    # Percentages: 50% / 50 % -> "50 percent".
    result = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", result)

    # A couple of standalone symbols that read badly as-is.
    result = re.sub(r"\s&\s", " and ", result)
    result = re.sub(r"\s@\s", " at ", result)
    result = re.sub(r"#(\d+)", r"number \1", result)

    # Tidy any doubled spaces we introduced.
    result = re.sub(r"[ \t]{2,}", " ", result).strip()
    return result


_PAUSE_STYLES = {"compact", "natural", "dramatic"}


def apply_pause_style(text, style):
    """Bias Kokoro's punctuation-driven pause lengths without changing the
    words. "natural" (default, and the fallback for any unrecognized style)
    is a no-op. "compact" shortens pauses (ellipses/dashes -> commas).
    "dramatic" lengthens them (commas -> em dashes; sentence ends gain a
    beat). Pure text transform — the actual pause length is Kokoro's own
    phonemizer behavior, this only changes which punctuation it sees.
    """
    if not text:
        return text
    style_key = str(style or "natural").strip().lower()
    if style_key not in _PAUSE_STYLES or style_key == "natural":
        return text

    result = text
    if style_key == "compact":
        result = re.sub(r"\.{3}", ",", result)
        result = re.sub(r"\s+—\s+", ", ", result)
        result = re.sub(r"\s+-\s+", ", ", result)
    else:  # dramatic
        result = re.sub(r",\s+", " — ", result)
        result = re.sub(r"([.!?])\s+(?!\.)", r"\1.. ", result)

    result = re.sub(r"[ \t]{2,}", " ", result).strip()
    return result
