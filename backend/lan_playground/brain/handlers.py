"""Versioned intent handler registry (wavebasedgame.md §3.5) and engine-side
validation hooks that run before a handler is ever invoked.

Global handlers are looked up by `method` (or a wildcard `"*"`); an
object-specific or NPC-specific handler with the same key always overrides
the matching global one. This mirrors content-vs-engine layering elsewhere
in the codebase (object/NPC authors can specialize a generic verb like
"give" without touching the global handler).

This module defines the *shape* of a handler and its validation outcome; it
does not itself implement any game handler (no domain knowledge lives in a
pure package) -- callers register their own handler callables from whatever
wave wires this package into the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class UnsupportedReason(str, Enum):
    NO_HANDLER = "no_handler"
    TARGET_NOT_FOUND = "target_not_found"
    ACTION_ECONOMY_EXHAUSTED = "action_economy_exhausted"
    ORDERING_VIOLATION = "compound_ordering_violation"
    UNSUPPORTED_BY_TARGET = "unsupported_by_target"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of running the engine-side validation hooks on a candidate
    intent before dispatch. `supported=False` always carries a
    `reason`; `requires_confirmation=True` means the engine must get an
    explicit confirm before the handler runs (ambiguous or high-impact
    intents), independent of whether the intent is otherwise supported."""

    supported: bool
    requires_confirmation: bool = False
    reason: UnsupportedReason | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.supported and self.reason is None:
            raise ValueError("an unsupported ValidationResult must carry a reason")


def validate_target_exists(target: str | None, known_target_ids) -> ValidationResult:
    """Engine hook: does the named target actually exist in the current
    scene? `known_target_ids` is whatever the caller's scene/room state
    considers addressable (objects, NPCs, exits, other heroes)."""
    if target is None:
        # No target named is not automatically invalid -- some methods
        # (e.g. "wait", "look_around") are targetless by design.
        return ValidationResult(supported=True)
    if target in known_target_ids:
        return ValidationResult(supported=True)
    return ValidationResult(
        supported=False,
        reason=UnsupportedReason.TARGET_NOT_FOUND,
        detail=f"no such target: {target!r}",
    )


def validate_action_economy(actions_remaining: int) -> ValidationResult:
    """Engine hook: does the actor have any action economy left this turn/
    round? A negative or zero remaining count blocks dispatch."""
    if actions_remaining > 0:
        return ValidationResult(supported=True)
    return ValidationResult(
        supported=False,
        reason=UnsupportedReason.ACTION_ECONOMY_EXHAUSTED,
        detail="no actions remaining",
    )


def validate_compound_ordering(sub_intents: tuple) -> ValidationResult:
    """Engine hook: for a compound utterance decomposed into multiple
    atomic intents, confirm they can execute in the order given (each
    later intent's precondition isn't invalidated by an earlier one in the
    same batch, e.g. 'unlock the door then open it' vs 'open the door then
    unlock it'). `sub_intents` is a tuple of already-parsed method strings
    in the order the caller intends to run them; the actual ordering rules
    are supplied by the caller since they're method-pair-specific and this
    package holds no game knowledge -- so this hook simply enforces the
    structural precondition that the batch is non-empty and within the
    §3.5 cap of 3 atomic intents."""
    if len(sub_intents) == 0:
        return ValidationResult(supported=True)
    if len(sub_intents) > 3:
        return ValidationResult(
            supported=False,
            reason=UnsupportedReason.ORDERING_VIOLATION,
            detail="more than 3 atomic intents in one compound utterance",
        )
    return ValidationResult(supported=True)


def requires_confirmation(*, ambiguous: bool, high_impact: bool) -> bool:
    """Ambiguous or high-impact intents require an explicit player
    confirmation before the handler runs (§3.5)."""
    return bool(ambiguous or high_impact)


@dataclass(frozen=True)
class HandlerKey:
    """Lookup key for a registered handler: a method name plus an optional
    scope (object instance id or NPC id). `scope=None` means global."""

    method: str
    scope: str | None = None


@dataclass
class HandlerRegistry:
    """Versioned registry of intent handlers. `version` bumps whenever the
    handler set changes shape in a way callers should be able to detect
    (e.g. content packs asserting compatibility)."""

    version: str = "brain.handlers.v1"
    _global: dict = field(default_factory=dict)
    _scoped: dict = field(default_factory=dict)

    def register_global(self, method: str, handler) -> None:
        self._global[method] = handler

    def register_scoped(self, method: str, scope: str, handler) -> None:
        """Register an object- or NPC-specific override for `method` on
        the given `scope` (an object instance id or NPC id)."""
        self._scoped[(method, scope)] = handler

    def resolve(self, method: str, scope: str | None = None):
        """Return the handler that should run for (method, scope):
        a scoped override wins if present, else the global handler
        (including a global wildcard "*" fallback), else None."""
        if scope is not None and (method, scope) in self._scoped:
            return self._scoped[(method, scope)]
        if method in self._global:
            return self._global[method]
        if "*" in self._global:
            return self._global["*"]
        return None

    def has_handler(self, method: str, scope: str | None = None) -> bool:
        return self.resolve(method, scope) is not None
