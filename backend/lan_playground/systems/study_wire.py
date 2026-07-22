"""Wires the pure `content.rooms`/`content.npcs`/`content.lattice` (wave 6B
lane B) and `brain.*` (wave 6B lane A) packages into the domain reducer,
realizing wavebasedgame.md §3.2's revised core loop (wave6b/slice-wiring,
docs/INFINITE_STACKS_STUDY_SLICE.md, docs/INFINITE_STACKS_BRAIN.md).
DOMAIN SCHEMA OWNER this part -- new command/event vocabulary documented in
docs/INFINITE_STACKS_CONTRACTS.md.

Breaching a `study` room (d8 == 3, `systems/exploration.py`'s `handle_breach`
calls `build_instantiate_events` below, mirroring `systems/puzzles.py`/
`systems/shops_wire.py`'s own room-family hooks) seeds the authored Gothic
Living Study `RoomTemplate` + its bound `NPCTemplate` (Elara Vance) and
stores runtime state on `RoomState.study` (a `StudyRoomState`), same pattern
as `RoomState.puzzle`/`.shop`/`.encounter`.

Director rulings honored here (board notes 31/32):
  - `ContentGapRecord` persists as a domain EVENT (`content_gap_logged`); the
    event log is persistence until wave 8. Never surfaced in a player-facing
    projection -- `RunState.content_gaps` and this event type are both
    engine/owner-visible only (§2.3/§20.2's server-side-disclosure discipline
    applied to debug data too).
  - Real check resolution always calls `systems.checks.outcome_for_margin`
    (never `brain.degrees`'s duplicate, which exists only so `brain/` can
    demonstrate its own mapping standalone -- see docs/INFINITE_STACKS_BRAIN.md
    §2).
  - Compound-ordering / which verbs an object or NPC supports is driven
    entirely by the study content's own `ObjectInteraction`/NPC handler data
    -- this module never invents a verb the content doesn't declare.
  - `RichOutcomeKind` selection within an eligible margin bucket is a
    seeded-deterministic pick from NPC-authored data (see
    `systems/study_social_wire.py::_pick_rich_outcome`), never a model/engine
    "choice" beyond the RNG draw.
  - Narrator/NPC-Performer packets are always built from disclosure-FILTERED
    facts -- the engine computes what's promoted for a viewer BEFORE ever
    building a packet (`_promote_object_state`/`_promote_fact` below), never
    the other way around.
  - NPC stats reuse the hero attribute vocabulary; DCs are engine-computed
    via `brain.degrees.compute_social_dc` (see `study_social_wire.py`),
    never authored directly by content.
"""
from __future__ import annotations

import functools

from ..brain import response as brain_response
from ..content import rooms as R
from ..content import study_loader
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import HeroState, RoomState, RunState, StudyRoomState

# ---------------------------------------------------------------- content loading


@functools.lru_cache(maxsize=1)
def _study_pack() -> study_loader.StudyContentPack:
    return study_loader.load_study_pack()


def _room_template(room_template_id: str) -> R.RoomTemplate:
    template = _study_pack().rooms.get(room_template_id)
    if template is None:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown study room template {room_template_id!r}")
    return template


def _npc_template(npc_id: str):
    npc = _study_pack().npcs.get(npc_id)
    if npc is None:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown npc template {npc_id!r}")
    return npc


def _lattice_recipe(recipe_id: str):
    recipe = _study_pack().lattice_recipes.get(recipe_id)
    if recipe is None:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown lattice recipe {recipe_id!r}")
    return recipe


# Deterministic placement hook for this slice (task item 1): the one authored
# Study room this wave. A future wave with multiple Study templates would
# extend this to `rng.choice(sorted(_study_pack().rooms))`; a single-element
# pool keeps the RNG draw shape identical (still exactly one seeded choice)
# so adding templates later never changes replay/event shape.
def _select_study_room_template_id(rng: StacksRNG) -> str:
    template_ids = sorted(_study_pack().rooms)
    return rng.choice(template_ids)


# ---------------------------------------------------------------- shared helpers


def _hero(state: RunState, hero_id: str | None) -> HeroState:
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    return state.heroes[hero_id]


def _study_room(state: RunState, hero_id: str | None) -> tuple[HeroState, RoomState, StudyRoomState]:
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    if room.study is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no active study room in {hero.room_id}")
    return hero, room, room.study


def _object_by_id(template: R.RoomTemplate, object_id: str) -> R.RoomObject | None:
    return next((o for o in template.objects if o.id == object_id), None)


def _interaction_by_id(obj: R.RoomObject, interaction_id: str) -> R.ObjectInteraction | None:
    return next((i for i in obj.interactions if i.id == interaction_id), None)


# ---------------------------------------------------------------- instantiate on breach


def build_instantiate_events(
    command: Command,
    state: RunState,
    rng: StacksRNG,
    room_id: str,
    breaching_hero_id: str,
    seq: int,
) -> tuple[Event, ...]:
    """Called from systems/exploration.py's handle_breach exactly when the
    rolled family is `study`. One RNG draw (which authored Study room
    template -- see `_select_study_room_template_id`); the instance is fully
    reconstructible from `room_template_id` alone, so `reduce()`'s applier
    below never touches rng again for this event (same discipline as
    `puzzles.build_instantiate_events`'s `puzzle_seed`)."""

    room_template_id = _select_study_room_template_id(rng)
    template = _room_template(room_template_id)
    npc_id = template.npc_ids[0] if template.npc_ids else None

    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.STUDY_ROOM_INSTANTIATED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=breaching_hero_id,
            room_id=room_id,
            payload={"room_id": room_id, "room_template_id": room_template_id, "npc_id": npc_id},
        ),
    )


def apply_study_room_instantiated(state: RunState, event: Event) -> RunState:
    room = state.map.rooms[event.payload["room_id"]]
    template = _room_template(event.payload["room_template_id"])
    npc_id = event.payload["npc_id"]

    object_state_ids = {obj.id: obj.initial_state for obj in template.objects}
    npc_disposition = ""
    if npc_id is not None:
        npc = _npc_template(npc_id)
        npc_disposition = npc.state.disposition

    room.study = StudyRoomState(
        room_template_id=event.payload["room_template_id"],
        npc_id=npc_id,
        object_state_ids=object_state_ids,
        npc_disposition=npc_disposition,
    )
    if state.floor_lattice_recipe_id is None:
        # First Study room this floor assigns the floor's recipe (the
        # slice's authored one-room recipe) -- a future multi-room floor
        # would instead assign this once at floor-generation time, but that
        # machinery doesn't exist yet (out of scope, §2.1's recipe is
        # per-floor not per-room).
        recipes = _study_pack().lattice_recipes
        if recipes:
            state.floor_lattice_recipe_id = sorted(recipes)[0]
    return state


# ---------------------------------------------------------------- disclosure promotion (pure helpers)


def _promote_object_state(study: StudyRoomState, hero_id: str, object_id: str) -> bool:
    """Promote `object_id` into `hero_id`'s visible set. Returns True if this
    changed anything (caller only emits a FACT_PROMOTED event on a real
    change, never a redundant one)."""
    existing = study.promoted_object_ids.get(hero_id, ())
    if object_id in existing:
        return False
    study.promoted_object_ids[hero_id] = existing + (object_id,)
    return True


def _promote_fact(study: StudyRoomState, hero_id: str, fact_id: str) -> bool:
    existing = study.promoted_fact_ids.get(hero_id, ())
    if fact_id in existing:
        return False
    study.promoted_fact_ids[hero_id] = existing + (fact_id,)
    return True


def _viewer_scope_hero_ids(state: RunState, room_id: str, viewer_scope) -> tuple[str, ...]:
    """Which hero ids a PARTY-scoped promotion should fan out to: every hero
    currently in the same room (a party/PUBLIC-in-room model for the room
    itself; a hero elsewhere in the map never receives this room's
    promotions -- the cross-player privacy exit-gate test proves this)."""
    from ..content.schemas import ViewerScope

    if viewer_scope == ViewerScope.ENGINE_ONLY:
        return ()
    return tuple(hid for hid, h in state.heroes.items() if h.room_id == room_id)


# Note: `interact` (the object-interaction command) lives in
# systems/study_interact_wire.py, split out to stay under the ~500-line
# module convention -- it imports the shared helpers below plus
# `_maybe_resolve_room_and_check_lattice` from this module rather than
# duplicating them. `converse` (the social-degree check) similarly lives in
# systems/study_social_wire.py.


def _fact_promoted_event(command, state, seq, actor_hero_id, room_id, viewer_hero_id, *, object_id, fact_id) -> Event:
    return Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.FACT_PROMOTED,
        visibility=Visibility.PRIVATE,
        actor_hero_id=actor_hero_id,
        room_id=room_id,
        payload={"viewer_hero_id": viewer_hero_id, "object_id": object_id, "fact_id": fact_id},
    )


# Note: apply_object_state_changed/apply_fact_promoted live in
# systems/study_interact_wire.py (the FACT_PROMOTED applier calls back into
# this module's _promote_object_state/_promote_fact helpers).


def _response_artifact_events(command, state, artifact, *, seq, actor_hero_id, room_id) -> tuple[Event, ...]:
    events = [
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.RESPONSE_ARTIFACT_EMITTED,
            visibility=Visibility.PARTY,
            actor_hero_id=actor_hero_id,
            room_id=room_id,
            payload=artifact.to_dict(),
        )
    ]
    if artifact.content_gap is not None:
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + 1),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.CONTENT_GAP_LOGGED,
                visibility=Visibility.PRIVATE,  # owner/debug-visible only (director ruling)
                actor_hero_id=actor_hero_id,
                room_id=room_id,
                payload={"viewer_hero_id": None, **artifact.content_gap.to_dict()},
            )
        )
    return tuple(events)


def apply_response_artifact_emitted(state: RunState, event: Event) -> RunState:
    return state


def apply_content_gap_logged(state: RunState, event: Event) -> RunState:
    record = {k: v for k, v in event.payload.items() if k != "viewer_hero_id"}
    state.content_gaps = state.content_gaps + (record,)
    return state


# Note: `converse` (the social-degree check with the NPC) lives in
# systems/study_social_wire.py, split out to stay under the ~500-line module
# convention -- it imports `_study_room`/`_npc_template`/`_fact_promoted_event`/
# `_response_artifact_events` from this module rather than duplicating them.


# ---------------------------------------------------------------- lattice + stair reveal


def _maybe_resolve_room_and_check_lattice(
    command: Command, state: RunState, template: R.RoomTemplate, study: StudyRoomState, hero_id: str, room_id: str, seq: int
) -> tuple[Event, ...]:
    """A room "resolves" for lattice purposes once its declared
    `payoff_interaction` has fired (§29/§3.3: the payoff is the room's whole
    reason for existing) -- never merely on room entry (§2.1 locked decision
    1: "entering a room alone does not repair it")."""
    if study.resolved:
        return ()
    payoff = template.payoff_interaction
    fired = payoff.interaction_id in study.fired_interaction_ids.get(payoff.object_id, ())
    if not fired:
        return ()

    events: list[Event] = [
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.LATTICE_CONTRIBUTION_REGISTERED,
            visibility=Visibility.PARTY,
            actor_hero_id=hero_id,
            room_id=room_id,
            payload={
                "room_id": room_id,
                "amounts": {c.value: amt for c, amt in template.lattice_contribution.amounts.items()},
            },
        )
    ]

    if state.floor_lattice_recipe_id is not None and not state.stair_revealed:
        recipe = _lattice_recipe(state.floor_lattice_recipe_id)
        projected_totals = dict(state.resolved_lattice_contributions)
        projected_totals[room_id] = {c.value: amt for c, amt in template.lattice_contribution.amounts.items()}
        from ..content.lattice import LatticeComponent, LatticeContribution

        contributions = [
            LatticeContribution(amounts={LatticeComponent(k): v for k, v in amounts.items()})
            for amounts in projected_totals.values()
        ]
        if recipe.is_satisfied(contributions):
            events.append(
                Event(
                    event_id=make_event_id(state.world_round, seq + len(events)),
                    run_id=state.run_id,
                    world_round=state.world_round,
                    caused_by=command.command_id,
                    type=EventType.LATTICE_RECIPE_SATISFIED,
                    visibility=Visibility.PARTY,
                    actor_hero_id=hero_id,
                    room_id=room_id,
                    payload={"recipe_id": recipe.id},
                )
            )
            events.append(
                Event(
                    event_id=make_event_id(state.world_round, seq + len(events)),
                    run_id=state.run_id,
                    world_round=state.world_round,
                    caused_by=command.command_id,
                    type=EventType.STAIR_REVEALED,
                    visibility=Visibility.PUBLIC,
                    actor_hero_id=hero_id,
                    room_id=room_id,
                    payload={"recipe_id": recipe.id, "floor_id": recipe.floor_id},
                )
            )
    return tuple(events)


def apply_lattice_contribution_registered(state: RunState, event: Event) -> RunState:
    room_id = event.payload["room_id"]
    state.resolved_lattice_contributions[room_id] = dict(event.payload["amounts"])
    study = state.map.rooms[room_id].study
    if study is not None:
        study.resolved = True
    return state


def apply_lattice_recipe_satisfied(state: RunState, event: Event) -> RunState:
    return state


def apply_stair_revealed(state: RunState, event: Event) -> RunState:
    state.stair_revealed = True
    return state


# ---------------------------------------------------------------- legal actions


def legal_action_names(state: RunState, hero_id: str) -> list[str]:
    hero = state.heroes.get(hero_id)
    if hero is None or state.map is None:
        return []
    room = state.map.rooms.get(hero.room_id)
    if room is None or room.study is None:
        return []
    actions = ["interact"]
    if room.study.npc_id is not None:
        actions.append("converse")
    return actions


# Note: EVENT_APPLIERS here deliberately excludes OBJECT_STATE_CHANGED/
# FACT_PROMOTED (study_interact_wire.EVENT_APPLIERS) and
# SOCIAL_CHECK_RESOLVED/NPC_DISPOSITION_CHANGED/NPC_OBJECTIVE_CHANGED
# (study_social_wire.EVENT_APPLIERS) -- domain/reducer.py merges all three
# modules' dicts together.
EVENT_APPLIERS = {
    EventType.STUDY_ROOM_INSTANTIATED: apply_study_room_instantiated,
    EventType.RESPONSE_ARTIFACT_EMITTED: apply_response_artifact_emitted,
    EventType.CONTENT_GAP_LOGGED: apply_content_gap_logged,
    EventType.LATTICE_CONTRIBUTION_REGISTERED: apply_lattice_contribution_registered,
    EventType.LATTICE_RECIPE_SATISFIED: apply_lattice_recipe_satisfied,
    EventType.STAIR_REVEALED: apply_stair_revealed,
}
