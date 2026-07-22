"""Object-`interact` half of the wave6b/slice-wiring Study-room domain wiring
(wavebasedgame.md §3.2-3.3, docs/INFINITE_STACKS_STUDY_SLICE.md). Split out of
`systems/study_wire.py` to stay under the repo's ~500-line module convention
(that module owns content-loading/instantiate/disclosure-primitives/lattice);
this module owns exactly the `interact` command: validate against the
object's `ObjectInteraction` (legal_states, verb vocabulary, repeatable) ->
immediate triggers evaluated BEFORE any check -> effects compiled through the
existing LIVE op executor (`systems/effects.py`) -> state transitions
persist. Zero-intent/unsupported input produces a `ResponseArtifact`-backed
event plus `content_gap_logged` where applicable (§2.3 always-a-response).
"""
from __future__ import annotations

from ..brain import response as brain_response
from ..brain import triggers as brain_triggers
from ..content import schemas as S
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import RunState, StudyRoomState
from . import effects, turns
from .study_wire import (
    _fact_promoted_event,
    _interaction_by_id,
    _maybe_resolve_room_and_check_lattice,
    _object_by_id,
    _response_artifact_events,
    _room_template,
    _study_room,
    _viewer_scope_hero_ids,
)


def validate_interact(state: RunState, hero_id: str | None, payload: dict):
    hero, room, study = _study_room(state, hero_id)
    template = _room_template(study.room_template_id)
    object_id = payload.get("object_id")
    interaction_id = payload.get("interaction_id")

    obj = _object_by_id(template, object_id)
    if obj is None:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown object {object_id!r} in {study.room_template_id!r}")
    interaction = _interaction_by_id(obj, interaction_id)
    if interaction is None:
        # Understood target (a real object), unsupported verb/interaction --
        # this is the "understood but no handler" content-gap path, handled
        # in handle_interact (never raised here, §2.3 always-a-response).
        return room, study, obj, None

    current_state_id = study.object_state_ids[obj.id]
    if current_state_id not in interaction.legal_states:
        raise CommandError(
            ErrorCode.ILLEGAL_ACTION,
            f"interaction {interaction_id!r} is not legal while {object_id!r} is in state {current_state_id!r}",
        )
    if not interaction.repeatable and interaction_id in study.fired_interaction_ids.get(object_id, ()):
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"interaction {interaction_id!r} on {object_id!r} is one-shot and already fired")
    turns.require_energy(state, hero_id, "interact")
    return room, study, obj, interaction


def handle_interact(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, study, obj, interaction = validate_interact(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    template = _room_template(study.room_template_id)

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["interact"], "action": "interact"},
    )
    events: list[Event] = [energy_event]

    if interaction is None:
        # Zero-intent/unsupported path (§2.3, task requirement #2): a real
        # object, but no matching interaction -- always a ResponseArtifact +
        # ContentGapRecord, never a bare error or silence.
        object_id = command.payload.get("object_id")
        interaction_id = command.payload.get("interaction_id")
        artifact = brain_response.unsupported_response(
            raw_utterance=f"interact:{object_id}:{interaction_id}",
            actor_id=hero_id,
            attempted_method=interaction_id,
            attempted_target=object_id,
            reason="no_handler",
            narration_facts=("Nothing about that interaction is supported here.",),
        )
        events.extend(_response_artifact_events(command, state, artifact, seq=seq + len(events), actor_hero_id=hero_id, room_id=hero.room_id))
        return tuple(events)

    # Immediate triggers evaluate BEFORE any check (brain.triggers shapes,
    # engine applies) -- this slice's authored content has no ImmediateTrigger
    # data yet (no object interaction demands a pre-check state delta), so
    # `evaluate_triggers` runs over an empty tuple; the seam is exercised even
    # though today it is always a no-op, per task requirement #2.
    matched = brain_triggers.evaluate_triggers(candidate=_InteractCandidate(method=interaction.id, target=obj.id), triggers=())
    brain_triggers.fold_trigger_state_deltas(matched)

    state_changed_events = []
    if interaction.state_transition_id is not None:
        transition = next(t for t in obj.transitions if t.id == interaction.state_transition_id)
        state_changed_events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + len(events) + len(state_changed_events)),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.OBJECT_STATE_CHANGED,
                visibility=Visibility.PARTY,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"object_id": obj.id, "from_state": transition.from_state, "to_state": transition.to_state, "interaction_id": interaction.id},
            )
        )
    events.extend(state_changed_events)

    # Promote whatever this interaction reveals for every hero currently in
    # the room (party-scoped, per §3.3's visibility tiers) -- promotion
    # happens BEFORE any narration packet is built (disclosure filter runs
    # first, task requirement #5).
    promote_targets = _viewer_scope_hero_ids(state, hero.room_id, S.ViewerScope.PARTY)
    if interaction.reveals_state is not None:
        for viewer_id in promote_targets:
            if _would_promote_object(study, viewer_id, obj.id):
                events.append(_fact_promoted_event(command, state, seq + len(events), hero_id, hero.room_id, viewer_id, object_id=obj.id, fact_id=None))

    # The room's declared payoff interaction (§29/§3.3: "the room's whole
    # reason for existing") may promote OTHER objects from a HIDDEN state to
    # their first NOTICED state -- e.g. moving the rug promotes the hidden
    # floor compartment to noticed (docs/INFINITE_STACKS_STUDY_SLICE.md §7
    # step 1: "promoting hidden_compartment from visibility: hidden to
    # noticed"). Content declares this as plain-English narrative rather than
    # a dedicated cross-object field, so the wiring layer infers it
    # generically and deterministically: firing the room's own
    # payoff_interaction promotes every OTHER object currently sitting in a
    # HIDDEN-visibility state to its first declared NOTICED-visibility state,
    # in object-declaration order -- never guessing which object beyond what
    # the room's own authored states/visibility tiers already declare.
    if interaction.id == template.payoff_interaction.interaction_id and obj.id == template.payoff_interaction.object_id:
        for other in template.objects:
            if other.id == obj.id:
                continue
            current_state_id = study.object_state_ids[other.id]
            current_state = other.state_by_id(current_state_id)
            if current_state.visibility.value != "hidden":
                continue
            noticed_state = next((s for s in other.states if s.visibility.value == "noticed"), None)
            if noticed_state is None:
                continue
            events.append(
                Event(
                    event_id=make_event_id(state.world_round, seq + len(events)),
                    run_id=state.run_id,
                    world_round=state.world_round,
                    caused_by=command.command_id,
                    type=EventType.OBJECT_STATE_CHANGED,
                    visibility=Visibility.PARTY,
                    actor_hero_id=hero_id,
                    room_id=hero.room_id,
                    payload={
                        "object_id": other.id,
                        "from_state": current_state_id,
                        "to_state": noticed_state.id,
                        # Not a real interaction on `other` -- a synthetic
                        # marker distinguishing this payoff-cascade promotion
                        # from a genuine fired interaction, so it never
                        # pollutes `other`'s own one-shot-interaction ledger.
                        "interaction_id": None,
                    },
                )
            )
            for viewer_id in promote_targets:
                if _would_promote_object(study, viewer_id, other.id):
                    events.append(
                        _fact_promoted_event(command, state, seq + len(events), hero_id, hero.room_id, viewer_id, object_id=other.id, fact_id=None)
                    )

    fact_ids = [e["args"]["fact_id"] for e in S.compile_effects(interaction.effects) if e["op"] == "emit_fact"]
    for fact_id in fact_ids:
        for viewer_id in promote_targets:
            if _would_promote_fact(study, viewer_id, fact_id):
                events.append(_fact_promoted_event(command, state, seq + len(events), hero_id, hero.room_id, viewer_id, object_id=None, fact_id=fact_id))

    events.extend(
        effects.dispatch(
            S.compile_effects(interaction.effects),
            command=command,
            state=state,
            rng=rng,
            seq=seq + len(events),
            actor_hero_id=hero_id,
            room_id=hero.room_id,
        )
    )

    artifact = brain_response.resolved_response(
        narration_facts=(interaction.prose.fallback,),
        state_delta=tuple(fact_ids),
    )
    events.extend(_response_artifact_events(command, state, artifact, seq=seq + len(events), actor_hero_id=hero_id, room_id=hero.room_id))

    events.extend(_maybe_resolve_room_and_check_lattice(command, state, template, study, hero_id, hero.room_id, seq + len(events)))
    return tuple(events)


class _InteractCandidate:
    """Minimal stand-in satisfying `brain.triggers.ImmediateTrigger.matches`'s
    duck-typed `candidate` contract (`.method`/`.keywords`/`.offer`/
    `.target`) without depending on a model-produced `brain.intents.
    IntentCandidate` for a purely mechanical object interaction."""

    def __init__(self, method: str, target: str):
        self.method = method
        self.target = target
        self.keywords: tuple = ()
        self.offer = None


def _would_promote_object(study: StudyRoomState, hero_id: str, object_id: str) -> bool:
    return object_id not in study.promoted_object_ids.get(hero_id, ())


def _would_promote_fact(study: StudyRoomState, hero_id: str, fact_id: str) -> bool:
    return fact_id not in study.promoted_fact_ids.get(hero_id, ())


def apply_object_state_changed(state: RunState, event: Event) -> RunState:
    study = state.map.rooms[event.room_id].study
    study.object_state_ids[event.payload["object_id"]] = event.payload["to_state"]
    interaction_id = event.payload["interaction_id"]
    if interaction_id is not None:
        existing = study.fired_interaction_ids.get(event.payload["object_id"], ())
        if interaction_id not in existing:
            study.fired_interaction_ids[event.payload["object_id"]] = existing + (interaction_id,)
    return state


def apply_fact_promoted(state: RunState, event: Event) -> RunState:
    from .study_wire import _promote_fact, _promote_object_state

    study = state.map.rooms[event.room_id].study
    viewer_id = event.payload["viewer_hero_id"]
    if event.payload.get("object_id") is not None:
        _promote_object_state(study, viewer_id, event.payload["object_id"])
    if event.payload.get("fact_id") is not None:
        _promote_fact(study, viewer_id, event.payload["fact_id"])
    return state


EVENT_APPLIERS = {
    EventType.OBJECT_STATE_CHANGED: apply_object_state_changed,
    EventType.FACT_PROMOTED: apply_fact_promoted,
}
