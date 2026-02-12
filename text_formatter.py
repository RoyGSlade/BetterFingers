"""
Text Formatter (Heuristic/Non-LLM)
----------------------------------
Formatting helpers for transcription segments based on silence gaps.

No third-party dependencies are required; this module uses only Python built-ins.
"""
import re


_MULTISPACE_RE = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_SPACE_AFTER_PUNCT_RE = re.compile(r"([,:;!?])(?=[A-Za-z0-9])")
_REPEAT_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z']{1,})\s+\1\b", flags=re.IGNORECASE)
_DISFLUENCY_RE = re.compile(r"(^|[.!?\n]\s+)(um+|uh+|er+|ah+)(?:,\s*|\s+)", flags=re.IGNORECASE)


def _segment_value(segment, key, default=None):
    if segment is None:
        return default
    if isinstance(segment, dict):
        return segment.get(key, default)
    return getattr(segment, key, default)


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _normalize_whitespace(text):
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = _MULTISPACE_RE.sub(" ", value)
    value = re.sub(r" ?\n ?", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _fix_punctuation_spacing(text):
    value = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", str(text or ""))
    value = _SPACE_AFTER_PUNCT_RE.sub(r"\1 ", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+\)", ")", value)
    value = re.sub(r"\[\s+", "[", value)
    value = re.sub(r"\s+\]", "]", value)
    value = re.sub(r"\{\s+", "{", value)
    value = re.sub(r"\s+\}", "}", value)
    return value


def _collapse_punctuation_noise(text):
    value = str(text or "")
    value = re.sub(r"[!?]{2,}", lambda match: match.group(0)[0], value)
    value = re.sub(r",{2,}", ",", value)
    value = re.sub(r";{2,}", ";", value)
    value = re.sub(r"\.{4,}", "...", value)
    return value


def _normalize_pronouns(text):
    value = re.sub(r"\bi\b", "I", str(text or ""))
    value = re.sub(r"\bi'([a-z])", lambda match: f"I'{match.group(1)}", value)
    return value


def _dedupe_repeated_words(text):
    value = str(text or "")
    for _ in range(4):
        updated = _REPEAT_WORD_RE.sub(lambda match: match.group(1), value)
        if updated == value:
            break
        value = updated
    return value


def _strip_disfluencies(text):
    return _DISFLUENCY_RE.sub(lambda match: match.group(1), str(text or ""))


def polish_text(text):
    value = _normalize_whitespace(text)
    if not value:
        return ""
    value = _fix_punctuation_spacing(value)
    value = _collapse_punctuation_noise(value)
    value = _normalize_pronouns(value)
    value = _dedupe_repeated_words(value)
    value = _strip_disfluencies(value)
    value = _normalize_whitespace(value)
    return value


def _format_segments_impl(segments, paragraph_threshold=1.2):
    seg_list = list(segments or [])
    if not seg_list:
        return ""

    threshold = max(0.0, _to_float(paragraph_threshold, 1.2))
    first_seg = seg_list[0]
    parts = [_to_text(_segment_value(first_seg, "text", ""))]
    last_end_time = _to_float(_segment_value(first_seg, "end", 0.0), 0.0)

    for current_seg in seg_list[1:]:
        current_start = _to_float(_segment_value(current_seg, "start", last_end_time), last_end_time)
        gap = current_start - last_end_time
        parts.append("\n\n" if gap >= threshold else " ")
        parts.append(_to_text(_segment_value(current_seg, "text", "")))
        last_end_time = _to_float(_segment_value(current_seg, "end", current_start), current_start)

    return polish_text("".join(parts))


def format_segments(segments, paragraph_threshold=1.2):
    return _format_segments_impl(segments, paragraph_threshold=paragraph_threshold)


def format_text(text):
    return polish_text(text)


class TextFormatter:
    @staticmethod
    def format_segments(segments, paragraph_threshold=1.2):
        """
        Args:
            segments: Iterable of segment objects or dicts.
                Expected fields: start, end, text
            paragraph_threshold (float): Silence seconds to trigger paragraph split.
        """
        return _format_segments_impl(segments, paragraph_threshold=paragraph_threshold)

    @staticmethod
    def format_text(text):
        return polish_text(text)
