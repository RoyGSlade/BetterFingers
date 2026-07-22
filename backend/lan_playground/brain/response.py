"""Always-a-response resolution artifacts (wavebasedgame.md §2.3): the
resolution of ANY utterance -- zero intents, harmless, or mechanically
unsupported -- produces a structured `ResponseArtifact`, never "nothing
happens". Unsupported interaction demand is captured as a real,
persistable `ContentGapRecord`, not a print statement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ResponseKind(str, Enum):
    ZERO_INTENT = "zero_intent"           # nothing parseable, still gets a response
    HARMLESS = "harmless"                 # understood, mechanically inert by design
    UNSUPPORTED = "unsupported"           # understood, no handler/mechanic exists yet
    RESOLVED = "resolved"                 # a real handler ran and produced a state delta
    CLARIFICATION_NEEDED = "clarification_needed"  # ambiguous, needs a follow-up
    CONFIRMATION_NEEDED = "confirmation_needed"    # high-impact/ambiguous, needs explicit confirm


@dataclass(frozen=True)
class ContentGapRecord:
    """A real, persistable data structure logging unsupported interaction
    demand -- the engine can serialize and store this for content-design
    review. Never a print/log-line side effect: this is the record itself.
    """

    raw_utterance: str
    actor_id: str
    attempted_method: str | None
    attempted_target: str | None
    reason: str
    scene_context: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "raw_utterance": self.raw_utterance,
            "actor_id": self.actor_id,
            "attempted_method": self.attempted_method,
            "attempted_target": self.attempted_target,
            "reason": self.reason,
            "scene_context": list(self.scene_context),
        }


@dataclass(frozen=True)
class ResponseArtifact:
    """The one required output of resolving any utterance/action. Always
    constructible from any resolution path -- there is no code path in
    this package that returns `None` or an empty/absent artifact for a
    processed utterance."""

    kind: ResponseKind
    narration_facts: tuple = field(default_factory=tuple)
    state_delta: tuple = field(default_factory=tuple)
    content_gap: ContentGapRecord | None = None
    clarification_prompt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "narration_facts", tuple(self.narration_facts))
        object.__setattr__(self, "state_delta", tuple(self.state_delta))
        if self.kind == ResponseKind.UNSUPPORTED and self.content_gap is None:
            raise ValueError("an UNSUPPORTED response artifact must carry a content_gap record")
        if self.kind == ResponseKind.CLARIFICATION_NEEDED and not self.clarification_prompt:
            raise ValueError("a CLARIFICATION_NEEDED response artifact must carry a clarification_prompt")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "narration_facts": list(self.narration_facts),
            "state_delta": list(self.state_delta),
            "content_gap": self.content_gap.to_dict() if self.content_gap else None,
            "clarification_prompt": self.clarification_prompt,
        }


def zero_intent_response(*, raw_utterance: str, actor_id: str, fallback_fact: str) -> ResponseArtifact:
    """Build the response artifact for an utterance that parsed to zero
    intents. Still a real, narratable response -- `fallback_fact` is an
    engine/content-authored line (e.g. "the room offers no visible reaction
    to that"), never a blank result."""
    return ResponseArtifact(
        kind=ResponseKind.ZERO_INTENT,
        narration_facts=(fallback_fact,),
    )


def harmless_response(*, narration_facts: tuple) -> ResponseArtifact:
    return ResponseArtifact(kind=ResponseKind.HARMLESS, narration_facts=narration_facts)


def unsupported_response(
    *,
    raw_utterance: str,
    actor_id: str,
    attempted_method: str | None,
    attempted_target: str | None,
    reason: str,
    narration_facts: tuple,
    scene_context: tuple = (),
) -> ResponseArtifact:
    """Build the response artifact for a mechanically-unsupported but
    understood action. Always attaches a `ContentGapRecord` -- this is the
    one place unsupported demand gets captured, and it happens
    unconditionally, not opportunistically."""
    gap = ContentGapRecord(
        raw_utterance=raw_utterance,
        actor_id=actor_id,
        attempted_method=attempted_method,
        attempted_target=attempted_target,
        reason=reason,
        scene_context=scene_context,
    )
    return ResponseArtifact(
        kind=ResponseKind.UNSUPPORTED,
        narration_facts=narration_facts,
        content_gap=gap,
    )


def resolved_response(*, narration_facts: tuple, state_delta: tuple) -> ResponseArtifact:
    return ResponseArtifact(kind=ResponseKind.RESOLVED, narration_facts=narration_facts, state_delta=state_delta)


def clarification_response(*, clarification_prompt: str) -> ResponseArtifact:
    return ResponseArtifact(kind=ResponseKind.CLARIFICATION_NEEDED, clarification_prompt=clarification_prompt)


def confirmation_response(*, clarification_prompt: str) -> ResponseArtifact:
    return ResponseArtifact(kind=ResponseKind.CONFIRMATION_NEEDED, clarification_prompt=clarification_prompt)
