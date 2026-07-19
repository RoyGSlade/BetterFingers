"""Message Rescue prompt construction and safe result parsing (Phase 2 Wave 2B, F2.7).

Pure module: no FastAPI, model client, or content-logging imports. The actual
LLM call is injected by the caller (``call_fn``) exactly like the
``capture_fn``/``supported_fn`` pattern in ``selection_capture.py`` and
``context_session.py`` — this module never opens a socket itself, so every
branch (valid JSON, malformed/fenced/noisy output, empty output, timeout,
oversize, preservation violations, context leakage) is exercisable with a
plain fake callable and never needs a real model or network access.

The "Prompt and rewrite invariants" in ACCOMPLISH.md §11 are enforced here,
not merely requested from the model: the system prompt states the rules, and
independently :func:`check_preservation` verifies each candidate variant
actually kept the raw transcript's names, numbers, dates, URLs, negation,
modality, and commitments before it is ever returned. A variant that fails
is dropped (or, for ``faithful``, replaced with the raw transcript itself) —
a verified-safe, non-empty ``variants.faithful`` is the guaranteed floor for
anything that doesn't parse, is empty, too large, too deep, arrives after a
timeout, leaks captured context, or fails a preservation check.

``delivery`` (labels/confidence/evidence) is derived from the caller-supplied
``SpeechSignals`` alone and never from parsed model output, so the model has
no path to inject an emotional diagnosis into a field whose whole purpose is
to stay an observable, uncertain signal (rule 3 in ACCOMPLISH.md §3).

Nothing here calls ``logging``: every warning/check string this module
returns is either a fixed label or a bounded count/snippet meant for the
in-app review UI, matching ``log_redaction.py``'s "count survives, content
doesn't" convention for anything that *would* be logged elsewhere.
"""

from __future__ import annotations

import json
import re
import string
from typing import Any, Callable, Mapping, Sequence

from backend.domain.contracts import MessageRescueResult, SpeechSignals

# --- Output shape limits (invariant: "strict size ceiling") -----------------

MAX_VARIANT_CHARS = 4000
MAX_ASSESSMENT_INTENT_CHARS = 300
MAX_AMBIGUITY_RISK_CHARS = 40
MAX_CLARIFICATION_CHARS = 300
MAX_MISSING_DETAILS = 5
MAX_MISSING_DETAIL_CHARS = 200
MAX_PRESERVATION_CHECKS = 30
MAX_WARNINGS = 10
MAX_WARNING_CHARS = 200
MAX_DELIVERY_LABELS = 8
MAX_DELIVERY_EVIDENCE = 8

# --- Model-output guards -----------------------------------------------------

MAX_RAW_RESPONSE_CHARS = 20_000
MAX_JSON_DEPTH = 6

# Matches llm_engine.MAX_FEW_SHOT_EXAMPLES; kept as an independent constant so
# this module has zero import coupling to the (FastAPI/subprocess-adjacent)
# llm_engine module.
MAX_FEW_SHOT_EXAMPLES = 5

MAX_CONTEXT_CHARS_IN_PROMPT = 2000

_SYSTEM_INSTRUCTIONS = (
    "You are Message Rescue, an assistant that turns a rough spoken transcript into a "
    "reviewable reply the user can send. Follow every rule exactly:\n"
    "1. Do not invent facts, commitments, or details the user did not say.\n"
    "2. Preserve every name, number, date, location, and URL exactly as spoken.\n"
    "3. Preserve negation and modality (e.g. 'not', 'never', 'can', 'might', 'must') — "
    "do not soften a refusal into an agreement or a maybe into a promise.\n"
    "4. Preserve the user's stated emotional intensity unless they explicitly ask for a "
    "tone change.\n"
    "5. Context is provided only so you can understand what the user is replying to. "
    "Never copy or quote the context into your output.\n"
    "6. Ask at most one clarification question, and only when a missing detail would "
    "materially change the message's meaning.\n"
    "7. Respond with a single JSON object and nothing else — no prose before or after, "
    "no markdown code fence. Keep every string concise.\n"
    "8. If you cannot safely rewrite the transcript, set \"variants.faithful\" to the "
    "transcript's own words, cleaned only of filler, and leave \"clearer\"/\"alternate\" empty.\n\n"
    "Respond with exactly this JSON shape:\n"
    "{\n"
    '  "assessment": {"intent": "", "ambiguity_risk": "low|medium|high", '
    '"missing_details": [], "clarification_question": ""},\n'
    '  "variants": {"faithful": "", "clearer": "", "alternate": ""}\n'
    "}"
)


# --- Prompt construction ------------------------------------------------------


def _summarize_signals(signals: SpeechSignals) -> str:
    """Short, bounded, text-free description of delivery for the prompt.

    Numbers only — never echoes transcript text, matching F2.1's own
    evidence-never-echoes-text guarantee.
    """
    axes = signals.delivery_axes or {}
    parts = [f"{key}={value:.2f}" for key, value in sorted(axes.items()) if isinstance(value, (int, float))]
    if signals.pause_count:
        parts.append(f"pauses={signals.pause_count}")
    if signals.filler_count:
        parts.append(f"fillers={signals.filler_count}")
    if signals.self_correction_count:
        parts.append(f"self_corrections={signals.self_correction_count}")
    return ", ".join(parts) if parts else "none"


def build_rescue_prompt(
    transcript: str,
    signals: SpeechSignals | None = None,
    *,
    context_text: str | None = None,
    persona: Mapping[str, Any] | None = None,
    examples: Sequence[Mapping[str, Any]] | None = None,
    max_examples: int = MAX_FEW_SHOT_EXAMPLES,
) -> list[dict[str, str]]:
    """Assemble OpenAI-style chat messages for the rescue call.

    Only the current raw transcript, explicit context, a speech-signal
    summary, the selected persona's voice, and approved examples go in — no
    history, no other drafts, matching the §11 invariant list exactly.
    ``examples`` (approved raw/final pairs) takes precedence over
    ``persona["few_shot"]`` when both are given, so a caller that already
    resolved consented examples doesn't need to also thread them through the
    persona dict.
    """
    system_parts = [_SYSTEM_INSTRUCTIONS]
    persona_prompt = ""
    if isinstance(persona, Mapping):
        persona_prompt = str(persona.get("prompt") or persona.get("system_prompt") or "").strip()
    if persona_prompt:
        system_parts.append(f"VOICE: {persona_prompt}")
    messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]

    few_shot = examples
    if few_shot is None and isinstance(persona, Mapping):
        few_shot = persona.get("few_shot")
    if few_shot:
        for item in list(few_shot)[:max_examples]:
            if not isinstance(item, Mapping):
                continue
            raw = str(item.get("raw", "") or "").strip()
            out = str(item.get("out", "") or "").strip()
            if raw and out:
                messages.append({"role": "user", "content": raw})
                messages.append({"role": "assistant", "content": out})

    user_parts = []
    if context_text and str(context_text).strip():
        trimmed_context = str(context_text).strip()[:MAX_CONTEXT_CHARS_IN_PROMPT]
        user_parts.append(
            "CONTEXT (for interpretation only — do not copy into your output):\n" + trimmed_context
        )
    if signals is not None:
        user_parts.append("DELIVERY SIGNAL SUMMARY: " + _summarize_signals(signals))
    user_parts.append("TRANSCRIPT:\n" + str(transcript or ""))
    messages.append({"role": "user", "content": "\n\n".join(user_parts)})
    return messages


# --- Robust JSON extraction ---------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _first_balanced_object(text: str) -> str | None:
    """Return the substring from the first ``{`` to its matching ``}``.

    String-aware (braces inside JSON string literals don't confuse the
    depth count), so a noisy wrapper like ``Sure! {...} Hope that helps.``
    still yields the embedded object.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _json_candidates(text: str):
    yield text
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        yield fence_match.group(1).strip()
    balanced = _first_balanced_object(text)
    if balanced:
        yield balanced


def _max_depth(value: Any, current: int = 1) -> int:
    if isinstance(value, dict):
        if not value:
            return current
        return max(_max_depth(v, current + 1) for v in value.values())
    if isinstance(value, list):
        if not value:
            return current
        return max(_max_depth(v, current + 1) for v in value)
    return current


def parse_rescue_response(raw_response: Any) -> dict[str, Any] | None:
    """Best-effort, safety-first JSON extraction from a raw model completion.

    Accepts a bare JSON object, one wrapped in a ```json fence, or one
    preceded/followed by explanatory prose (bracket-matched, string-aware).
    Returns ``None`` — never raises — for anything that isn't a well-formed,
    bounded JSON *object*, so callers always have an unambiguous "could not
    parse" signal to fall back on instead of a partially-trusted result.
    """
    if not isinstance(raw_response, str):
        return None
    text = raw_response.strip()
    if not text or len(text) > MAX_RAW_RESPONSE_CHARS:
        return None

    for candidate in _json_candidates(text):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
        if isinstance(parsed, dict) and _max_depth(parsed) <= MAX_JSON_DEPTH:
            return parsed
    return None


# --- Result normalization (strict per-field limits) ---------------------------


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp_str(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _clamp_list_str(value: Any, max_items: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:max_items]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:item_limit])
    return out


def _normalize_assessment(raw_assessment: Any) -> dict[str, Any]:
    a = raw_assessment if isinstance(raw_assessment, dict) else {}
    ambiguity_risk: Any = a.get("ambiguity_risk")
    if isinstance(ambiguity_risk, bool):
        ambiguity_risk = ""
    elif isinstance(ambiguity_risk, (int, float)):
        ambiguity_risk = _clamp01(float(ambiguity_risk))
    elif isinstance(ambiguity_risk, str):
        ambiguity_risk = ambiguity_risk.strip()[:MAX_AMBIGUITY_RISK_CHARS]
    else:
        ambiguity_risk = ""
    return {
        "intent": _clamp_str(a.get("intent"), MAX_ASSESSMENT_INTENT_CHARS),
        "ambiguity_risk": ambiguity_risk,
        "missing_details": _clamp_list_str(a.get("missing_details"), MAX_MISSING_DETAILS, MAX_MISSING_DETAIL_CHARS),
        "clarification_question": _clamp_str(a.get("clarification_question"), MAX_CLARIFICATION_CHARS),
    }


def _normalize_variants(raw_variants: Any, raw_text: str) -> dict[str, str]:
    v = raw_variants if isinstance(raw_variants, dict) else {}
    out = {key: _clamp_str(v.get(key), MAX_VARIANT_CHARS) for key in ("faithful", "clearer", "alternate")}
    if not out["faithful"]:
        out["faithful"] = raw_text[:MAX_VARIANT_CHARS]
    return out


_AXIS_DESCRIPTIONS = (("arousal", "energy"), ("urgency", "urgency"), ("hesitation", "hesitation"))
_LEVEL_THRESHOLDS = ((0.66, "high"), (0.33, "moderate"), (0.0, "low"))


def _level_label(value: float) -> str:
    for threshold, label in _LEVEL_THRESHOLDS:
        if value >= threshold:
            return label
    return "low"


def _derive_delivery(signals: SpeechSignals | None) -> dict[str, Any]:
    """Build the result's ``delivery`` block entirely from ``SpeechSignals``.

    Deliberately never reads parsed model output: this is the structural
    guarantee behind ACCOMPLISH.md rule 3 ("emotion is presented as an
    uncertain signal") — the model has no field to write an emotional
    diagnosis into, because this block is never sourced from it.
    """
    if signals is None:
        return {"labels": [], "confidence": 0.0, "evidence": []}
    axes = signals.delivery_axes or {}
    labels = []
    for axis_key, description in _AXIS_DESCRIPTIONS:
        value = axes.get(axis_key)
        if isinstance(value, (int, float)):
            labels.append(f"{_level_label(float(value))} {description}")
    confidence = signals.confidence if isinstance(signals.confidence, (int, float)) else 0.0
    return {
        "labels": labels[:MAX_DELIVERY_LABELS],
        "confidence": _clamp01(float(confidence)),
        "evidence": list(signals.evidence or [])[:MAX_DELIVERY_EVIDENCE],
    }


# --- Deterministic preservation checks ----------------------------------------

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+\b", re.IGNORECASE)
_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_WEEKDAYS = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_DATE_RE = re.compile(
    rf"\b\d{{1,4}}[/-]\d{{1,2}}[/-]\d{{1,4}}\b"
    rf"|\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{2,4}})?\b"
    rf"|\b{_WEEKDAYS}\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(?:not|never|none|nobody|nothing|nowhere|neither|nor|without|no|"
    r"can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|"
    r"haven't|hasn't|hadn't|wouldn't|shouldn't|couldn't)\b",
    re.IGNORECASE,
)
_MODALITY_RE = re.compile(
    r"\b(?:can|could|may|might|must|shall|should|will|would|"
    r"won't|can't|couldn't|shouldn't|wouldn't)\b",
    re.IGNORECASE,
)
_COMMITMENT_RE = re.compile(
    r"\bI(?:'ll| will| can| could| promise| commit| guarantee| plan to| am going to)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_name_tokens(text: str) -> set[str]:
    """Heuristic proper-noun/place extraction: capitalized words that are not
    the first word of their sentence (sentence-initial capitalization is just
    grammar, not a name)."""
    names: set[str] = set()
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        words = sentence.split()
        for i, word in enumerate(words):
            core = word.strip(string.punctuation)
            if i == 0 or len(core) < 2:
                continue
            if core[0].isupper() and core[1:].islower():
                names.add(core)
    return names


def _check_pattern_category(label: str, name: str, pattern: re.Pattern, raw_text: str, candidate_text: str, case_sensitive: bool) -> list[dict[str, Any]]:
    raw_tokens = _dedupe_preserve_order([m.group(0) for m in pattern.finditer(raw_text)])
    if not raw_tokens:
        return []
    haystack = candidate_text if case_sensitive else candidate_text.lower()
    missing = [t for t in raw_tokens if (t if case_sensitive else t.lower()) not in haystack]
    passed = not missing
    detail = "preserved" if passed else f"missing after rewrite: {', '.join(missing[:5])}"
    return [{"name": f"{label}/{name}", "passed": passed, "detail": detail[:MAX_WARNING_CHARS]}]


def check_preservation(raw_text: str, candidate_text: str, label: str = "variant") -> list[dict[str, Any]]:
    """Deterministically verify a rewrite kept the raw transcript's facts.

    Checks each category present in ``raw_text`` (numbers, dates, URLs,
    negation, modality, commitment phrases, capitalized names/places) still
    appears verbatim in ``candidate_text``. A category with nothing to
    preserve in the raw text produces no check entry. Never raises.
    """
    checks: list[dict[str, Any]] = []
    checks.extend(_check_pattern_category(label, "numbers", _NUMBER_RE, raw_text, candidate_text, True))
    checks.extend(_check_pattern_category(label, "dates", _DATE_RE, raw_text, candidate_text, False))
    checks.extend(_check_pattern_category(label, "urls", _URL_RE, raw_text, candidate_text, True))
    checks.extend(_check_pattern_category(label, "negation", _NEGATION_RE, raw_text, candidate_text, False))
    checks.extend(_check_pattern_category(label, "modality", _MODALITY_RE, raw_text, candidate_text, False))
    checks.extend(_check_pattern_category(label, "commitments", _COMMITMENT_RE, raw_text, candidate_text, False))

    raw_names = _extract_name_tokens(raw_text)
    if raw_names:
        missing_names = sorted(n for n in raw_names if n not in candidate_text)
        passed = not missing_names
        detail = "preserved" if passed else f"missing after rewrite: {', '.join(missing_names[:5])}"
        checks.append({"name": f"{label}/names", "passed": passed, "detail": detail[:MAX_WARNING_CHARS]})
    return checks


_LEAK_WINDOW = 24


def _context_leak(context_text: str | None, candidate_text: str) -> bool:
    """True if a long verbatim slice of the (interpretation-only) captured
    context shows up in the rewrite, i.e. it got copied instead of used."""
    if not context_text or not candidate_text:
        return False
    ctx = context_text.strip()
    if len(ctx) < _LEAK_WINDOW:
        return False
    step = max(1, _LEAK_WINDOW // 2)
    for i in range(0, len(ctx) - _LEAK_WINDOW + 1, step):
        window = ctx[i : i + _LEAK_WINDOW]
        if window.strip() and window in candidate_text:
            return True
    return False


# --- Orchestration --------------------------------------------------------


def _looks_like_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in type(exc).__name__.lower()


def rescue_message(
    transcript: str,
    signals: SpeechSignals | None = None,
    *,
    context_text: str | None = None,
    persona: Mapping[str, Any] | None = None,
    examples: Sequence[Mapping[str, Any]] | None = None,
    call_fn: Callable[[list[dict[str, str]]], str],
    max_examples: int = MAX_FEW_SHOT_EXAMPLES,
) -> MessageRescueResult:
    """Build the rescue prompt, call the model via ``call_fn``, and return a
    validated :class:`MessageRescueResult`.

    ``call_fn`` receives the chat messages from :func:`build_rescue_prompt`
    and must return the raw completion string, or raise on failure/timeout.
    Any failure to call, parse, or preservation-check the result falls back
    to a result whose ``variants.faithful`` is the raw transcript itself
    (never empty when the transcript wasn't) with a ``warnings`` entry
    explaining why — malformed model output can never become an empty
    message.
    """
    raw_text = str(transcript or "").strip()
    delivery = _derive_delivery(signals)

    def fallback(reason: str) -> MessageRescueResult:
        return MessageRescueResult(
            assessment={},
            delivery=delivery,
            variants={"faithful": raw_text[:MAX_VARIANT_CHARS], "clearer": "", "alternate": ""},
            preservation_checks=[],
            warnings=[reason[:MAX_WARNING_CHARS]],
        )

    if not raw_text:
        return fallback("empty transcript")

    messages = build_rescue_prompt(
        raw_text, signals, context_text=context_text, persona=persona, examples=examples, max_examples=max_examples
    )

    try:
        raw_response = call_fn(messages)
    except Exception as exc:  # noqa: BLE001 - call_fn is an arbitrary injected boundary
        kind = "model call timed out" if _looks_like_timeout(exc) else "model call failed"
        return fallback(f"{kind}: {type(exc).__name__}")

    if not isinstance(raw_response, str) or not raw_response.strip():
        return fallback("empty model output")
    if len(raw_response) > MAX_RAW_RESPONSE_CHARS:
        return fallback("model output exceeded size limit")

    parsed = parse_rescue_response(raw_response)
    if parsed is None:
        return fallback("model output was not valid JSON")

    assessment = _normalize_assessment(parsed.get("assessment"))
    variants = _normalize_variants(parsed.get("variants"), raw_text)

    preservation_checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    safe_variants: dict[str, str] = {}

    for key, text in variants.items():
        if not text:
            safe_variants[key] = ""
            continue
        checks = check_preservation(raw_text, text, label=key)
        preservation_checks.extend(checks)
        failed = any(not c["passed"] for c in checks)
        leaked = _context_leak(context_text, text)
        if leaked:
            preservation_checks.append(
                {"name": f"{key}/context_not_copied", "passed": False, "detail": "rewrite appears to copy captured context verbatim"}
            )
        if failed or leaked:
            if key == "faithful":
                safe_variants[key] = raw_text[:MAX_VARIANT_CHARS]
                warnings.append("faithful variant failed preservation checks; replaced with raw transcript")
            else:
                safe_variants[key] = ""
                warnings.append(f"{key} variant dropped: failed preservation checks")
        else:
            safe_variants[key] = text

    if not safe_variants.get("faithful"):
        safe_variants["faithful"] = raw_text[:MAX_VARIANT_CHARS]

    return MessageRescueResult(
        assessment=assessment,
        delivery=delivery,
        variants=safe_variants,
        preservation_checks=preservation_checks[:MAX_PRESERVATION_CHECKS],
        warnings=warnings[:MAX_WARNINGS],
    )
