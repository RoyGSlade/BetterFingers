"""Immediate triggers (wavebasedgame.md §3.5): engine-defined data that
alters state BEFORE a check resolves -- the canonical example is offering
bacon to a dragon, which can raise its hunger or change its objective before
any roll happens.

This package defines only the trigger *data shape* and the *evaluation
order*; it never defines or applies a trigger itself; that authored content
lives wherever the domain/content lane puts it. The model never defines or
applies a trigger either -- triggers only ever come from engine/content data
matched against a parsed intent, and application is a pure function over
that data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TriggerCondition(str, Enum):
    """How a trigger decides whether it fires for a given intent candidate."""

    METHOD_EQUALS = "method_equals"
    KEYWORD_PRESENT = "keyword_present"
    OFFER_MATCHES_ITEM = "offer_matches_item"
    TARGET_EQUALS = "target_equals"


@dataclass(frozen=True)
class ImmediateTrigger:
    """One engine-authored immediate trigger. `priority` (lower runs first)
    fixes deterministic evaluation order when multiple triggers could match
    the same intent -- the same intent set + trigger set always evaluates
    in the same order, regardless of dict/iteration order at runtime."""

    trigger_id: str
    condition: TriggerCondition
    match_value: str
    state_delta: tuple = field(default_factory=tuple)
    priority: int = 100

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_delta", tuple(self.state_delta))

    def matches(self, candidate) -> bool:
        """`candidate` is a `brain.intents.IntentCandidate`. Pure structural
        match against the declared condition -- no model involvement."""
        if self.condition == TriggerCondition.METHOD_EQUALS:
            return candidate.method == self.match_value
        if self.condition == TriggerCondition.KEYWORD_PRESENT:
            return self.match_value in candidate.keywords
        if self.condition == TriggerCondition.OFFER_MATCHES_ITEM:
            return candidate.offer == self.match_value
        if self.condition == TriggerCondition.TARGET_EQUALS:
            return candidate.target == self.match_value
        return False


def evaluate_triggers(candidate, triggers) -> tuple:
    """Return every `ImmediateTrigger` in `triggers` that matches
    `candidate`, in deterministic priority order (ties broken by
    `trigger_id` for full determinism regardless of input order/replay).
    Does not apply anything -- application (folding `state_delta`s into
    real state) is the caller's job once the domain wiring exists; this
    function only decides *which* triggers fire and in what order."""
    matched = [t for t in triggers if t.matches(candidate)]
    matched.sort(key=lambda t: (t.priority, t.trigger_id))
    return tuple(matched)


def fold_trigger_state_deltas(matched_triggers: tuple) -> tuple:
    """Pure fold of every matched trigger's `state_delta` entries, in the
    same deterministic order `evaluate_triggers` produced. Concatenation
    only -- no merging/collapsing logic lives here, since what a
    "state_delta" entry actually means is the domain-wiring lane's concern
    once this package's output is consumed."""
    deltas: list = []
    for trigger in matched_triggers:
        deltas.extend(trigger.state_delta)
    return tuple(deltas)
