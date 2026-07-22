"""Social/`converse` half of the wave6b/slice-wiring Study-room domain wiring
(wavebasedgame.md §3.6, docs/INFINITE_STACKS_BRAIN.md §4, docs/
INFINITE_STACKS_STUDY_SLICE.md). Split out of `systems/study_wire.py` to stay
under the repo's ~500-line module convention (that module already owns
instantiate/interact/disclosure/lattice); this module owns exactly the social
degree check (`converse`) and its NPC-state consequences, importing the
shared room/NPC lookup helpers from `study_wire` rather than duplicating them.

Director rulings honored here (board notes 31/32):
  - Real check resolution always calls `systems.checks.outcome_for_margin`
    (this module never calls `brain.degrees.outcome_for_margin` -- `checks.
    perform_check` already IS the authoritative resolution).
  - The ±5 contextual modifier's inputs are evidence/motive enums derived
    from game state only (`_hero_evidence_tier`/`_hero_motive_alignment`
    below), never free text.
  - `RichOutcomeKind` selection within an eligible margin bucket is a
    seeded-deterministic pick from NPC-authored data (`_pick_rich_outcome`).
  - NPC stats reuse the hero attribute vocabulary; DCs are engine-computed
    via `brain.degrees.compute_social_dc`, never authored directly.
"""
from __future__ import annotations

from ..brain import degrees as brain_degrees
from ..brain import response as brain_response
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import HeroState, RoomState, RunState, StudyRoomState
from . import checks, turns
from .study_wire import _fact_promoted_event, _npc_template, _response_artifact_events, _study_room

_MOTIVE_TIERS = {t.value: t for t in brain_degrees.MotiveAlignment}

# The concrete in-world evidence signal this slice recognizes (director
# ruling: the +/-5 modifier derives ONLY from evidence/motive enums present in
# game state, never free text). `fact_compartment_contents_revealed` is
# emitted by `compartment_open_action` (study.yaml) the moment a hero opens
# the hidden compartment and finds Elara's sister's letters -- carrying that
# fact (i.e. having personally promoted/witnessed it, tracked per-viewer on
# `StudyRoomState.promoted_fact_ids`) is this slice's "holding the letters as
# leverage" signal, checkable server-side rather than a claimed string.
EVIDENCE_FACT_ID = "fact_compartment_contents_revealed"


def validate_converse(state: RunState, hero_id: str | None, payload: dict) -> tuple[RoomState, StudyRoomState, str]:
    hero, room, study = _study_room(state, hero_id)
    npc_id = payload.get("npc_id")
    if study.npc_id != npc_id:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"no npc {npc_id!r} present in this room")
    turns.require_energy(state, hero_id, "converse")
    return room, study, npc_id


def _hero_evidence_tier(study: StudyRoomState, hero_id: str) -> brain_degrees.EvidenceTier:
    """The +/-5 contextual modifier derives ONLY from evidence/motive enums
    present in game state (director ruling) -- never free text, never a
    caller-claimed tier. This hero counts as holding VERIFIABLE evidence iff
    `EVIDENCE_FACT_ID` has actually been promoted for THIS viewer (i.e. this
    hero personally opened the compartment or was told the fact by another
    party member's earlier interaction) -- server-checked, never taken on
    the caller's word."""
    promoted = study.promoted_fact_ids.get(hero_id, ())
    if EVIDENCE_FACT_ID in promoted:
        return brain_degrees.EvidenceTier.VERIFIABLE
    return brain_degrees.EvidenceTier.NONE


def _hero_motive_alignment(payload: dict) -> brain_degrees.MotiveAlignment:
    """Motive alignment is declared by the caller as one of the authored
    enum values (matched against NPC objective content elsewhere) -- this
    slice accepts the caller's declared alignment only if it names a real
    `MotiveAlignment` member, defaulting to NEUTRAL otherwise (never free
    text read as a signal)."""
    raw = payload.get("motive_alignment")
    return _MOTIVE_TIERS.get(raw, brain_degrees.MotiveAlignment.NEUTRAL)


def _pick_rich_outcome(npc, outcome: brain_degrees.SocialOutcome, rng: StacksRNG) -> str | None:
    """Seeded-deterministic pick from NPC-authored data (director ruling --
    never a model choice). `eligible = brain.degrees.ELIGIBLE_RICH_OUTCOMES`
    bounds the kind; this NPC's own tells/lies/objectives narrow which of
    the eligible kinds this NPC can actually produce, and the RNG (the
    engine's own seeded stream, never re-rolled on replay) breaks ties
    deterministically among the remaining candidates."""
    eligible = brain_degrees.ELIGIBLE_RICH_OUTCOMES[outcome]
    candidates: list[str] = []
    for kind in eligible:
        if kind is brain_degrees.RichOutcomeKind.LIE and npc.lies:
            candidates.append(kind.value)
        elif kind is brain_degrees.RichOutcomeKind.BEHAVIORAL_TELL and npc.tells:
            candidates.append(kind.value)
        elif kind is brain_degrees.RichOutcomeKind.DISPOSITION_CHANGE:
            candidates.append(kind.value)
        elif kind is brain_degrees.RichOutcomeKind.OBJECTIVE_CHANGE and npc.objectives:
            candidates.append(kind.value)
        elif kind in (
            brain_degrees.RichOutcomeKind.PARTIAL_CONCESSION,
            brain_degrees.RichOutcomeKind.COUNTEROFFER,
            brain_degrees.RichOutcomeKind.NEW_DANGER,
        ):
            candidates.append(kind.value)
    if not candidates:
        return None
    return rng.choice(sorted(candidates))


def handle_converse(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, study, npc_id = validate_converse(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    npc = _npc_template(npc_id)

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["converse"], "action": "converse"},
    )
    events: list[Event] = [energy_event]

    evidence = _hero_evidence_tier(study, hero_id)
    motive = _hero_motive_alignment(command.payload)
    modifier_inputs = brain_degrees.SocialModifierInputs(evidence=evidence, motive=motive)

    npc_resolve = npc.stats.get("resolve", 0)
    dc_inputs = brain_degrees.SocialDCInputs(npc_resolve=npc_resolve)
    dc = brain_degrees.compute_social_dc(dc_inputs)
    modifier = brain_degrees.compute_contextual_modifier(modifier_inputs)

    hero_insight = hero.sheet.attributes.get("insight") if hero.sheet is not None else 0
    check_result = checks.perform_check(rng, attribute_score=hero_insight, skill_rank=0, dc=dc, modifiers=modifier)
    # Real check resolution always calls systems.checks.outcome_for_margin
    # (director ruling) -- check_result.outcome already IS that call's
    # result; brain.degrees.outcome_for_margin is never invoked here.
    outcome_value = check_result.outcome.value
    eligible = brain_degrees.ELIGIBLE_RICH_OUTCOMES[brain_degrees.SocialOutcome(outcome_value)]
    rich_outcome = _pick_rich_outcome(npc, brain_degrees.SocialOutcome(outcome_value), rng)

    check_event = Event(
        event_id=make_event_id(state.world_round, seq + len(events)),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.SOCIAL_CHECK_RESOLVED,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "npc_id": npc_id,
            "dc": dc,
            "modifier": modifier,
            "evidence_tier": evidence.value,
            "motive_alignment": motive.value,
            "die_rolls": list(check_result.die_rolls),
            "total": check_result.total,
            "margin": check_result.margin,
            "outcome": outcome_value,
            "eligible_rich_outcomes": [k.value for k in eligible],
            "rich_outcome": rich_outcome,
        },
    )
    events.append(check_event)

    if rich_outcome == brain_degrees.RichOutcomeKind.DISPOSITION_CHANGE.value:
        new_disposition = "warmer" if outcome_value in ("strong_success", "clean_success") else "colder"
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + len(events)),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.NPC_DISPOSITION_CHANGED,
                visibility=Visibility.PARTY,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"npc_id": npc_id, "disposition": new_disposition},
            )
        )
    elif rich_outcome == brain_degrees.RichOutcomeKind.OBJECTIVE_CHANGE.value:
        main_objectives = [o for o in npc.objectives if o.kind.value == "main"]
        if main_objectives:
            objective = main_objectives[0]
            events.append(
                Event(
                    event_id=make_event_id(state.world_round, seq + len(events)),
                    run_id=state.run_id,
                    world_round=state.world_round,
                    caused_by=command.command_id,
                    type=EventType.NPC_OBJECTIVE_CHANGED,
                    visibility=Visibility.PARTY,
                    actor_hero_id=hero_id,
                    room_id=hero.room_id,
                    payload={"npc_id": npc_id, "objective_id": objective.id, "state": "changed"},
                )
            )

    # Disclose whatever FREE-layer knowledge is relevant on a clean-or-better
    # outcome (a minimally real NPC Performer disclosure step for this
    # slice); GATED atoms are never disclosed here -- disclosure validation
    # stays server-side per §3.4/§19.4.
    if outcome_value in ("strong_success", "clean_success"):
        for atom in npc.knowledge:
            if atom.disclosure.value == "free" and atom.id not in study.npc_disclosed_atom_ids.get(hero_id, ()):
                events.append(
                    _fact_promoted_event(
                        command, state, seq + len(events), hero_id, hero.room_id, hero_id, object_id=None, fact_id=f"npc_atom:{atom.id}"
                    )
                )

    artifact = brain_response.resolved_response(
        narration_facts=(f"{npc_id} responds to the approach.",),
        state_delta=(outcome_value,),
    )
    events.extend(_response_artifact_events(command, state, artifact, seq=seq + len(events), actor_hero_id=hero_id, room_id=hero.room_id))
    return tuple(events)


def apply_social_check_resolved(state: RunState, event: Event) -> RunState:
    return state


def apply_npc_disposition_changed(state: RunState, event: Event) -> RunState:
    study = state.map.rooms[event.room_id].study
    study.npc_disposition = event.payload["disposition"]
    return state


def apply_npc_objective_changed(state: RunState, event: Event) -> RunState:
    study = state.map.rooms[event.room_id].study
    study.npc_objective_states[event.payload["objective_id"]] = event.payload["state"]
    return state


EVENT_APPLIERS = {
    EventType.SOCIAL_CHECK_RESOLVED: apply_social_check_resolved,
    EventType.NPC_DISPOSITION_CHANGED: apply_npc_disposition_changed,
    EventType.NPC_OBJECTIVE_CHANGED: apply_npc_objective_changed,
}
