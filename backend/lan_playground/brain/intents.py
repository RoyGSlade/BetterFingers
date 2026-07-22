"""Interpreter output contract (wavebasedgame.md §3.5, §2.3): stable intent
candidates parsed defensively from a model's raw output.

The Interpreter never determines success -- it only proposes *what the
player might have meant*. `confidence` on an `IntentCandidate` is
deliberately named and documented so it can never be confused with a
success/DC roll: it answers "how sure is the parser this is what the
player meant", not "how likely is this to work". The engine (not this
package) is the only thing that ever computes a success chance, via
`degrees.py`.

`parse_raw_intents()` is the defensive boundary between whatever a model
actually returns (a dict, a list, garbage, `None`, a truncated JSON blob
already parsed one level, or an exception-raising generator) and the rest
of the engine. It must never raise -- malformed input always degrades to
the zero-intent path, never an exception escaping to the caller, per the
task's explicit requirement and §2.3 "always a response".
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_CONFIDENCE = 1
MAX_CONFIDENCE = 100
MAX_INTENTS = 3


@dataclass(frozen=True)
class IntentCandidate:
    """One parsed, validated intent candidate.

    `confidence` is *interpretation confidence* (1-100): how sure the
    Interpreter is that this is what the player meant. It is never a
    success chance and must never be read as one -- outcome resolution
    lives entirely in `degrees.py` and is computed by the engine from
    DC/attribute/skill/modifier, not from this field.
    """

    target: str | None
    method: str | None
    confidence: int
    offer: str | None = None
    request: str | None = None
    leverage: tuple = field(default_factory=tuple)
    keywords: tuple = field(default_factory=tuple)
    requested_outcome: str | None = None
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if not (MIN_CONFIDENCE <= self.confidence <= MAX_CONFIDENCE):
            raise ValueError(f"confidence must be {MIN_CONFIDENCE}-{MAX_CONFIDENCE}, got {self.confidence}")
        object.__setattr__(self, "leverage", tuple(self.leverage))
        object.__setattr__(self, "keywords", tuple(self.keywords))

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "method": self.method,
            "interpretation_confidence": self.confidence,
            "offer": self.offer,
            "request": self.request,
            "leverage": list(self.leverage),
            "keywords": list(self.keywords),
            "requested_outcome": self.requested_outcome,
            "ambiguous": self.ambiguous,
        }


@dataclass(frozen=True)
class InterpretationResult:
    """The full, bounded Interpreter output: 0-3 stable intent candidates.

    Always constructible, never partially invalid -- `parse_raw_intents`
    is the only place malformed candidates get dropped, so by the time an
    `InterpretationResult` exists every candidate in it is valid.
    """

    candidates: tuple

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        if len(candidates) > MAX_INTENTS:
            candidates = candidates[:MAX_INTENTS]
        object.__setattr__(self, "candidates", candidates)

    @property
    def is_zero_intent(self) -> bool:
        return len(self.candidates) == 0

    def to_dict(self) -> dict:
        return {"candidates": [c.to_dict() for c in self.candidates]}


ZERO_INTENT_RESULT = InterpretationResult(candidates=())


def _clamp_confidence(value) -> int | None:
    """Coerce a raw confidence value to an int in [1, 100], or None if it
    cannot be interpreted as a number at all (caller then rejects the
    candidate rather than guessing)."""
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, numeric))


def _as_str_or_none(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    # Reject non-string junk (numbers, dicts, lists) rather than guessing a cast.
    return None


def _as_tuple_of_str(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(v) for v in value if isinstance(v, str) and v.strip())
    return ()


def _parse_one_candidate(raw) -> IntentCandidate | None:
    """Parse+validate a single raw candidate dict. Returns None (never
    raises) if the candidate is malformed beyond repair -- e.g. missing a
    usable confidence value entirely. Every other field defensively
    defaults rather than rejecting, since target/method/etc. are
    individually optional in the contract."""
    if not isinstance(raw, dict):
        return None

    confidence = _clamp_confidence(
        raw.get("confidence", raw.get("interpretation_confidence"))
    )
    if confidence is None:
        return None

    try:
        return IntentCandidate(
            target=_as_str_or_none(raw.get("target")),
            method=_as_str_or_none(raw.get("method")),
            confidence=confidence,
            offer=_as_str_or_none(raw.get("offer")),
            request=_as_str_or_none(raw.get("request")),
            leverage=_as_tuple_of_str(raw.get("leverage")),
            keywords=_as_tuple_of_str(raw.get("keywords") or raw.get("triggers")),
            requested_outcome=_as_str_or_none(raw.get("requested_outcome")),
            ambiguous=bool(raw.get("ambiguous", False)),
        )
    except (ValueError, TypeError):
        # Defensive backstop: any dataclass validation failure degrades
        # this one candidate to "drop it", never propagates.
        return None


def parse_raw_intents(raw_output) -> InterpretationResult:
    """Parse a model's raw output into a bounded `InterpretationResult`.

    Never raises. Handles every malformed shape by degrading toward the
    zero-intent path:
      - `None`, non-list/non-dict junk, exceptions during iteration -> zero intents.
      - A single dict (not wrapped in a list) is treated as one candidate.
      - A list of raw candidate dicts: each is parsed independently;
        unparseable entries are dropped rather than aborting the whole call.
      - More than `MAX_INTENTS` valid candidates are truncated to the first 3.
    """
    try:
        if raw_output is None:
            return ZERO_INTENT_RESULT
        if isinstance(raw_output, dict):
            raw_list = [raw_output]
        elif isinstance(raw_output, (list, tuple)):
            raw_list = list(raw_output)
        else:
            return ZERO_INTENT_RESULT

        parsed = []
        for raw in raw_list:
            if len(parsed) >= MAX_INTENTS:
                break
            candidate = _parse_one_candidate(raw)
            if candidate is not None:
                parsed.append(candidate)
        return InterpretationResult(candidates=tuple(parsed))
    except Exception:
        # Absolute last resort: this function must never let an exception
        # escape to the caller (task requirement + §2.3 always-a-response).
        return ZERO_INTENT_RESULT
