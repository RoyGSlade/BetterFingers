"""Bounded per-call generation packets for the four BetterFingers/Brain roles
(wavebasedgame.md §3.2, §3.5): Interpreter, NPC Performer, Narrator, and
event-to-book/note prose.

The core guarantee: **no model-owned memory, anywhere**. A packet carries
only engine-supplied allowed facts for one specific call -- scene facts,
allowed disclosures, resolved degree, state delta -- and nothing else. There
is no conversation history field on any packet, no session id that could be
used to look up prior turns, and no cache keyed by anything but the packet's
own declared inputs. This is enforced structurally, not by convention:

- Every packet type below is a frozen dataclass built only from explicit
  constructor arguments passed by the caller for *this* call.
- Nothing in this module holds a module-level cache, a class-level list, or
  any other place a previous packet or model response could be stashed
  between calls. `build_*` functions are pure: same arguments in, same
  packet out, and the module does not remember having been called before.
- `PacketBase.to_dict()` is the only serialization path a generation
  adapter should send to a model; it round-trips exactly what's on the
  dataclass, so there's no back door for extra state to sneak in through a
  broader "context" object.

Matches infinite_stacks.md §20.3's structured-generation-contract fields
(schema version, content purpose, authorized facts, prohibited additions,
persona/tone, max length, safety/privacy constraints, deterministic fallback
key, cache key, timeout) via `GenerationEnvelope`, which every packet embeds.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum

SCHEMA_VERSION = "brain.packets.v1"


class BrainRole(str, Enum):
    INTERPRETER = "interpreter"
    NPC_PERFORMER = "npc_performer"
    NARRATOR = "narrator"
    EVENT_TO_BOOK_PROSE = "event_to_book_prose"


def _freeze_facts(facts) -> tuple:
    """Coerce a mapping/sequence of facts into an immutable, hashable tuple
    of (key, value) pairs (or leave an already-tuple input alone), so no
    packet field can be a mutable list/dict a caller mutates after the fact."""
    if facts is None:
        return ()
    if isinstance(facts, dict):
        return tuple(sorted(facts.items(), key=lambda kv: kv[0]))
    return tuple(facts)


@dataclass(frozen=True)
class GenerationEnvelope:
    """The §20.3 structured-generation-contract fields, common to every role.

    `authorized_facts` and `prohibited_additions` are frozen tuples (never
    lists/dicts) precisely so a caller cannot hand in a shared mutable
    collection that later generation calls could observe changing --
    each packet is a snapshot, not a view onto live state.
    """

    schema_version: str
    content_purpose: str
    authorized_facts: tuple = field(default_factory=tuple)
    prohibited_additions: tuple = field(default_factory=tuple)
    persona: str | None = None
    tone: str | None = None
    max_length: int = 400
    safety_constraints: tuple = field(default_factory=tuple)
    deterministic_fallback_key: str = ""
    cache_key: str = ""
    timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorized_facts", _freeze_facts(self.authorized_facts))
        object.__setattr__(self, "prohibited_additions", tuple(self.prohibited_additions))
        object.__setattr__(self, "safety_constraints", tuple(self.safety_constraints))
        if self.max_length <= 0:
            raise ValueError("max_length must be positive")
        if not self.deterministic_fallback_key:
            raise ValueError("every packet must declare a deterministic_fallback_key (§20.3, §3.7 no-model-blocks-play)")


def make_envelope(
    *,
    content_purpose: str,
    authorized_facts,
    deterministic_fallback_key: str,
    cache_key: str,
    prohibited_additions=(),
    persona: str | None = None,
    tone: str | None = None,
    max_length: int = 400,
    safety_constraints=(),
    timeout_seconds: float = 3.0,
) -> GenerationEnvelope:
    return GenerationEnvelope(
        schema_version=SCHEMA_VERSION,
        content_purpose=content_purpose,
        authorized_facts=authorized_facts,
        prohibited_additions=prohibited_additions,
        persona=persona,
        tone=tone,
        max_length=max_length,
        safety_constraints=safety_constraints,
        deterministic_fallback_key=deterministic_fallback_key,
        cache_key=cache_key,
        timeout_seconds=timeout_seconds,
    )


class PacketBase:
    """Mixin providing a uniform, allow-listed `to_dict()` for every packet
    dataclass below. Only declared dataclass fields are ever emitted -- there
    is no `**kwargs` passthrough anywhere in this module a caller could use
    to smuggle extra (e.g. cached/historical) data into a generation call."""

    def to_dict(self) -> dict:
        out = {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            if isinstance(value, GenerationEnvelope):
                out[f.name] = {
                    "schema_version": value.schema_version,
                    "content_purpose": value.content_purpose,
                    "authorized_facts": list(value.authorized_facts),
                    "prohibited_additions": list(value.prohibited_additions),
                    "persona": value.persona,
                    "tone": value.tone,
                    "max_length": value.max_length,
                    "safety_constraints": list(value.safety_constraints),
                    "deterministic_fallback_key": value.deterministic_fallback_key,
                    "cache_key": value.cache_key,
                    "timeout_seconds": value.timeout_seconds,
                }
            elif isinstance(value, tuple):
                out[f.name] = list(value)
            else:
                out[f.name] = value
        return out


@dataclass(frozen=True)
class InterpreterPacket(PacketBase):
    """Fresh, bounded input for the Interpreter role (§3.5): the raw
    utterance/action plus only the scene facts/allowed disclosures the
    engine currently permits for this actor -- no history, no prior turns."""

    envelope: GenerationEnvelope
    raw_utterance: str
    actor_id: str
    scene_facts: tuple = field(default_factory=tuple)
    allowed_disclosures: tuple = field(default_factory=tuple)
    visible_targets: tuple = field(default_factory=tuple)
    visible_objects: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scene_facts", _freeze_facts(self.scene_facts))
        object.__setattr__(self, "allowed_disclosures", _freeze_facts(self.allowed_disclosures))
        object.__setattr__(self, "visible_targets", tuple(self.visible_targets))
        object.__setattr__(self, "visible_objects", tuple(self.visible_objects))


@dataclass(frozen=True)
class NPCPerformerPacket(PacketBase):
    """Fresh, bounded input for the NPC Performer role (§3.4, §19.3): the
    NPC's authored dialogue act plus only the scene facts this NPC is
    currently allowed to disclose -- never the NPC's full authored profile,
    never another player's private clues (§19.4)."""

    envelope: GenerationEnvelope
    npc_id: str
    dialogue_act: str
    allowed_disclosures: tuple = field(default_factory=tuple)
    scene_facts: tuple = field(default_factory=tuple)
    disposition: str | None = None
    resolved_degree: str | None = None
    state_delta: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_disclosures", _freeze_facts(self.allowed_disclosures))
        object.__setattr__(self, "scene_facts", _freeze_facts(self.scene_facts))
        object.__setattr__(self, "state_delta", _freeze_facts(self.state_delta))


@dataclass(frozen=True)
class NarratorPacket(PacketBase):
    """Fresh, bounded input for the Narrator role (§3.2, §20.1): only the
    resolved facts/degree/state-delta for the action that just happened --
    the Narrator never receives the running scene history, only what
    changed and what is now true."""

    envelope: GenerationEnvelope
    scene_facts: tuple = field(default_factory=tuple)
    resolved_degree: str | None = None
    state_delta: tuple = field(default_factory=tuple)
    allowed_disclosures: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scene_facts", _freeze_facts(self.scene_facts))
        object.__setattr__(self, "state_delta", _freeze_facts(self.state_delta))
        object.__setattr__(self, "allowed_disclosures", _freeze_facts(self.allowed_disclosures))


@dataclass(frozen=True)
class EventToBookPacket(PacketBase):
    """Fresh, bounded input for event-to-book/note prose generation (§18.3,
    §20.1): a list of event IDs and their engine-declared facts only --
    never raw event payloads, and never facts not authorized for the
    requesting viewer (§20.2's 'no secret information not authorized for
    the requesting viewer')."""

    envelope: GenerationEnvelope
    event_ids: tuple = field(default_factory=tuple)
    declared_facts: tuple = field(default_factory=tuple)
    prose_stage: str = "title"  # title -> summary -> excerpt -> chapter (§20 progressive reading)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_ids", tuple(self.event_ids))
        object.__setattr__(self, "declared_facts", _freeze_facts(self.declared_facts))


def build_interpreter_packet(
    *,
    raw_utterance: str,
    actor_id: str,
    scene_facts=(),
    allowed_disclosures=(),
    visible_targets=(),
    visible_objects=(),
    cache_key: str = "",
    max_length: int = 200,
) -> InterpreterPacket:
    """Build a fresh Interpreter packet from explicit arguments only. There
    is nothing cached between calls -- call this again for the next
    utterance and it builds an entirely new, independent packet."""
    envelope = make_envelope(
        content_purpose="interpret_player_utterance",
        authorized_facts=scene_facts,
        deterministic_fallback_key="interpreter.zero_intent",
        cache_key=cache_key or f"interpreter:{actor_id}:{raw_utterance}",
        max_length=max_length,
    )
    return InterpreterPacket(
        envelope=envelope,
        raw_utterance=raw_utterance,
        actor_id=actor_id,
        scene_facts=scene_facts,
        allowed_disclosures=allowed_disclosures,
        visible_targets=visible_targets,
        visible_objects=visible_objects,
    )


def build_npc_performer_packet(
    *,
    npc_id: str,
    dialogue_act: str,
    allowed_disclosures=(),
    scene_facts=(),
    disposition: str | None = None,
    resolved_degree: str | None = None,
    state_delta=(),
    cache_key: str = "",
    max_length: int = 300,
) -> NPCPerformerPacket:
    envelope = make_envelope(
        content_purpose="perform_npc_dialogue_act",
        authorized_facts=allowed_disclosures,
        deterministic_fallback_key="npc_performer.authored_line",
        cache_key=cache_key or f"npc:{npc_id}:{dialogue_act}",
        max_length=max_length,
    )
    return NPCPerformerPacket(
        envelope=envelope,
        npc_id=npc_id,
        dialogue_act=dialogue_act,
        allowed_disclosures=allowed_disclosures,
        scene_facts=scene_facts,
        disposition=disposition,
        resolved_degree=resolved_degree,
        state_delta=state_delta,
    )


def build_narrator_packet(
    *,
    scene_facts=(),
    resolved_degree: str | None = None,
    state_delta=(),
    allowed_disclosures=(),
    cache_key: str = "",
    max_length: int = 400,
) -> NarratorPacket:
    envelope = make_envelope(
        content_purpose="narrate_resolved_action",
        authorized_facts=scene_facts,
        deterministic_fallback_key="narrator.factual_summary",
        cache_key=cache_key or f"narrator:{resolved_degree}",
        max_length=max_length,
    )
    return NarratorPacket(
        envelope=envelope,
        scene_facts=scene_facts,
        resolved_degree=resolved_degree,
        state_delta=state_delta,
        allowed_disclosures=allowed_disclosures,
    )


def build_event_to_book_packet(
    *,
    event_ids,
    declared_facts=(),
    prose_stage: str = "title",
    cache_key: str = "",
    max_length: int = 600,
) -> EventToBookPacket:
    envelope = make_envelope(
        content_purpose=f"generate_book_prose_{prose_stage}",
        authorized_facts=declared_facts,
        deterministic_fallback_key=f"event_to_book.{prose_stage}",
        cache_key=cache_key or f"book:{prose_stage}:{','.join(event_ids)}",
        max_length=max_length,
    )
    return EventToBookPacket(
        envelope=envelope,
        event_ids=tuple(event_ids),
        declared_facts=declared_facts,
        prose_stage=prose_stage,
    )
