"""Ephemeral authority for wake-phrase setup candidates.

The renderer may propose a phrase, but later wake-enrollment work must refer to
an opaque server-issued id rather than resubmitting phrase text.  This registry
holds the accepted text-preflight result for that handoff.  It is deliberately
small, process-local, and short-lived: there is no persistence, audio, file
path, clone prompt, model selection, or arbitrary TTS payload here.

Records are frozen.  Their nested fitness report is stored as JSON and decoded
afresh for every caller, so mutating a returned report can never alter the
registry's authority.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import re
import secrets
import threading
import time
from typing import Callable


DEFAULT_MAX_ENTRIES = 16
DEFAULT_TTL_SECONDS = 30 * 60.0
MAX_REPORT_BYTES = 32 * 1024

_ALLOWED_VERDICTS = frozenset({"good", "workable"})
_NORMALIZED_PHRASE_RE = re.compile(r"[a-z]+(?:'[a-z]+)?(?: [a-z]+(?:'[a-z]+)?)*\Z")
_OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9_-]{12,128}\Z")
_PHONETIC_SIGNATURE_RE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*\Z")
_REPORT_FIELDS = frozenset(
    {
        "version",
        "language",
        "normalized_phrase",
        "verdict",
        "score",
        "reasons",
        "evidence",
        "near_confusers",
        "acoustic_test_required",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {
        "word_count",
        "letter_count",
        "estimated_syllables",
        "estimated_phonemes",
        "phonetic_signature",
        "pronunciation",
        "pronunciation_source",
        "unsupported_characters",
        "nearest_vocabulary_phrase",
        "nearest_vocabulary_similarity",
        "contained_commands",
        "contained_common_phrases",
    }
)


class WakeSetupIssuanceSuspended(RuntimeError):
    """Raised when a privacy wipe has temporarily closed setup issuance."""


def _default_token_factory() -> str:
    # 144 random bits.  The token carries no phrase-derived material.
    return secrets.token_urlsafe(18)


@dataclass(frozen=True)
class WakePhraseSetup:
    """One immutable, server-approved phrase candidate."""

    phrase_id: str
    normalized_phrase: str
    issued_at: float
    expires_at: float
    _fitness_report_json: str = field(repr=False)

    @property
    def fitness_report(self) -> dict:
        """A defensive JSON copy of the accepted text-fitness report."""
        return json.loads(self._fitness_report_json)

    def to_dict(self) -> dict:
        return {
            "phrase_id": self.phrase_id,
            "normalized_phrase": self.normalized_phrase,
            "fitness_report": self.fitness_report,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


def _validated_phrase(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("normalized_phrase must be a nonempty string")
    if len(value) > 80 or _NORMALIZED_PHRASE_RE.fullmatch(value) is None:
        raise ValueError("normalized_phrase must already be normalized English wake-phrase text")
    return value


def _bounded_strings(value: object, name: str, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"fitness report {name} must be a list of strings")
    if len(value) > max_items:
        raise ValueError(f"fitness report {name} has too many entries")
    result = []
    for item in value:
        if not isinstance(item, str) or len(item) > max_chars:
            raise ValueError(f"fitness report {name} entries must be bounded strings")
        result.append(item)
    return result


def _bounded_text(
    value: object,
    name: str,
    *,
    max_chars: int,
    allow_none: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value or len(value) > max_chars:
        suffix = " or null" if allow_none else ""
        raise ValueError(
            f"fitness report evidence {name} must be a nonempty bounded string{suffix}"
        )
    if not value.isprintable():
        raise ValueError(f"fitness report evidence {name} must contain printable text")
    return value


def _bounded_int(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(
            f"fitness report evidence {name} must be an integer from 0 to {maximum}"
        )
    return value


def _bounded_number(value: object, name: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"fitness report evidence {name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValueError(
            f"fitness report evidence {name} must be between {minimum} and {maximum}"
        )
    return normalized


def _bounded_phrases(value: object, name: str, *, max_items: int) -> list[str]:
    phrases = _bounded_strings(value, name, max_items=max_items, max_chars=80)
    for phrase in phrases:
        if not phrase or _NORMALIZED_PHRASE_RE.fullmatch(phrase) is None:
            raise ValueError(
                f"fitness report {name} entries must be normalized English phrases"
            )
    return phrases


def _validated_evidence(evidence: object) -> dict:
    if not isinstance(evidence, Mapping):
        raise ValueError("fitness_report evidence must be a mapping")
    if set(evidence) - _EVIDENCE_FIELDS:
        raise ValueError("fitness_report evidence contains unsupported fields")

    sanitized = {}
    integer_fields = {
        "word_count": 80,
        "letter_count": 80,
        "estimated_syllables": 80,
        "estimated_phonemes": 160,
    }
    for name, maximum in integer_fields.items():
        if name in evidence:
            sanitized[name] = _bounded_int(evidence[name], name, maximum=maximum)

    if "phonetic_signature" in evidence:
        signature = _bounded_text(
            evidence["phonetic_signature"], "phonetic_signature", max_chars=256
        )
        if _PHONETIC_SIGNATURE_RE.fullmatch(signature) is None:
            raise ValueError(
                "fitness report evidence phonetic_signature has an invalid format"
            )
        sanitized["phonetic_signature"] = signature

    if "pronunciation" in evidence:
        sanitized["pronunciation"] = _bounded_text(
            evidence["pronunciation"],
            "pronunciation",
            max_chars=512,
            allow_none=True,
        )

    if "pronunciation_source" in evidence:
        source = evidence["pronunciation_source"]
        if source not in {"phonemizer_espeak", "heuristic_only"}:
            raise ValueError(
                "fitness report evidence pronunciation_source is unsupported"
            )
        sanitized["pronunciation_source"] = source

    if "unsupported_characters" in evidence:
        unsupported = _bounded_strings(
            evidence["unsupported_characters"],
            "evidence unsupported_characters",
            max_items=16,
            max_chars=8,
        )
        if unsupported:
            raise ValueError(
                "accepted English fitness reports cannot contain unsupported characters"
            )
        sanitized["unsupported_characters"] = []

    if "nearest_vocabulary_phrase" in evidence:
        nearest = evidence["nearest_vocabulary_phrase"]
        if nearest is not None:
            nearest = _bounded_text(
                nearest,
                "nearest_vocabulary_phrase",
                max_chars=80,
            )
            if _NORMALIZED_PHRASE_RE.fullmatch(nearest) is None:
                raise ValueError(
                    "fitness report evidence nearest_vocabulary_phrase must be normalized English"
                )
        sanitized["nearest_vocabulary_phrase"] = nearest

    if "nearest_vocabulary_similarity" in evidence:
        sanitized["nearest_vocabulary_similarity"] = _bounded_number(
            evidence["nearest_vocabulary_similarity"],
            "nearest_vocabulary_similarity",
            minimum=0.0,
            maximum=1.0,
        )

    if "contained_commands" in evidence:
        sanitized["contained_commands"] = _bounded_phrases(
            evidence["contained_commands"], "evidence contained_commands", max_items=64
        )
    if "contained_common_phrases" in evidence:
        sanitized["contained_common_phrases"] = _bounded_phrases(
            evidence["contained_common_phrases"],
            "evidence contained_common_phrases",
            max_items=64,
        )
    return sanitized


def _validated_report(normalized_phrase: str, report: object) -> str:
    if not isinstance(report, Mapping):
        raise ValueError("fitness_report must be a mapping")

    unknown = set(report) - _REPORT_FIELDS
    if unknown:
        raise ValueError("fitness_report contains unsupported fields")

    verdict = report.get("verdict")
    if verdict not in _ALLOWED_VERDICTS:
        raise ValueError("fitness_report verdict must be good or workable")

    reported_phrase = report.get("normalized_phrase", normalized_phrase)
    if reported_phrase != normalized_phrase:
        raise ValueError("fitness_report does not belong to normalized_phrase")

    acoustic_required = report.get("acoustic_test_required", True)
    if acoustic_required is not True:
        raise ValueError("fitness_report must preserve the real-acoustic-test requirement")

    sanitized = {
        "normalized_phrase": normalized_phrase,
        "verdict": verdict,
        "acoustic_test_required": True,
    }

    if "version" in report:
        version = report["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("fitness_report version must be a positive integer")
        sanitized["version"] = version

    if "language" in report:
        if report["language"] != "en":
            raise ValueError("fitness_report language must be en")
        sanitized["language"] = "en"

    if "score" in report:
        score = report["score"]
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("fitness_report score must be an integer from 0 to 100")
        sanitized["score"] = score

    if "reasons" in report:
        sanitized["reasons"] = _bounded_strings(
            report["reasons"], "reasons", max_items=32, max_chars=512
        )

    if "near_confusers" in report:
        sanitized["near_confusers"] = _bounded_phrases(
            report["near_confusers"], "near_confusers", max_items=32
        )

    if "evidence" in report:
        sanitized["evidence"] = _validated_evidence(report["evidence"])

    try:
        encoded = json.dumps(
            sanitized,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("fitness_report must contain only finite JSON data") from exc
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("fitness_report is too large")
    return encoded


class WakeSetupRegistry:
    """Thread-safe, bounded collection of short-lived phrase candidates."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = _default_token_factory,
    ):
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        try:
            ttl = float(ttl_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("ttl_seconds must be positive") from exc
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not callable(clock) or not callable(token_factory):
            raise TypeError("clock and token_factory must be callable")

        self._max_entries = max_entries
        self._ttl_seconds = ttl
        self._clock = clock
        self._token_factory = token_factory
        self._lock = threading.RLock()
        self._records: OrderedDict[str, WakePhraseSetup] = OrderedDict()
        self._issuance_suspended = False

    def suspend_issuance(self) -> None:
        """Atomically refuse new setup candidates until explicitly resumed."""
        with self._lock:
            self._issuance_suspended = True

    def resume_issuance(self) -> None:
        """Re-open setup issuance after a privacy wipe finishes or aborts."""
        with self._lock:
            self._issuance_suspended = False

    def _prune_expired_locked(self, now: float) -> int:
        expired = [
            phrase_id
            for phrase_id, record in self._records.items()
            if now >= record.expires_at
        ]
        for phrase_id in expired:
            self._records.pop(phrase_id, None)
        return len(expired)

    def prune_expired(self) -> int:
        """Remove expired candidates and return the number removed."""
        now = float(self._clock())
        with self._lock:
            return self._prune_expired_locked(now)

    def _new_phrase_id_locked(self) -> str:
        for _ in range(16):
            candidate = self._token_factory()
            if not isinstance(candidate, str) or _OPAQUE_ID_RE.fullmatch(candidate) is None:
                raise ValueError("token_factory must return a 12-128 character opaque id")
            if candidate not in self._records:
                return candidate
        raise RuntimeError("could not allocate a unique wake phrase id")

    def issue(self, normalized_phrase: str, fitness_report: Mapping) -> WakePhraseSetup:
        """Store an accepted text-preflight result and return its opaque record.

        Capacity is enforced after expired entries are removed.  When all slots
        remain live, the oldest candidate is evicted; setup candidates are
        replaceable, whereas exceeding the bound is not.
        """
        phrase = _validated_phrase(normalized_phrase)
        report_json = _validated_report(phrase, fitness_report)
        now = float(self._clock())

        with self._lock:
            if self._issuance_suspended:
                raise WakeSetupIssuanceSuspended(
                    "wake setup issuance is suspended during the privacy wipe"
                )
            self._prune_expired_locked(now)
            phrase_id = self._new_phrase_id_locked()
            while len(self._records) >= self._max_entries:
                self._records.popitem(last=False)
            record = WakePhraseSetup(
                phrase_id=phrase_id,
                normalized_phrase=phrase,
                issued_at=now,
                expires_at=now + self._ttl_seconds,
                _fitness_report_json=report_json,
            )
            self._records[phrase_id] = record
            return record

    def resolve(self, phrase_id: object) -> WakePhraseSetup | None:
        """Return a live immutable record, or ``None`` for missing/expired ids."""
        if not isinstance(phrase_id, str):
            return None
        now = float(self._clock())
        with self._lock:
            self._prune_expired_locked(now)
            return self._records.get(phrase_id)

    def discard(self, phrase_id: object) -> bool:
        """Forget one candidate.  Idempotent and safe for unknown ids."""
        if not isinstance(phrase_id, str):
            return False
        now = float(self._clock())
        with self._lock:
            self._prune_expired_locked(now)
            return self._records.pop(phrase_id, None) is not None

    def clear(self) -> int:
        """Privacy-wipe hook: remove every candidate and return the count."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
            return count

    def __len__(self) -> int:
        self.prune_expired()
        with self._lock:
            return len(self._records)


# One process-wide authority for routes, privacy wipe, and the future fixed
# Qwen benchmark worker.  It contains no persistent or raw-audio state.
WAKE_SETUP_REGISTRY = WakeSetupRegistry()


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_SECONDS",
    "WAKE_SETUP_REGISTRY",
    "WakePhraseSetup",
    "WakeSetupIssuanceSuspended",
    "WakeSetupRegistry",
]
