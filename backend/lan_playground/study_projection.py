"""Viewer-filtered wire projection for wave6b/slice-wiring's Study-room domain
state (wave-6B part 4, docs/INFINITE_STACKS_CONTRACTS.md §5.11 "Wire
projection requirement (not yet built -- the following client/UX part's
file)"). This IS that file.

`project_study(domain_state, viewer)` builds the `project(state, viewer)`
top-level `"study"` key `stacks_engine.py`'s docstring promised: one entry per
room currently holding a `domain.state.StudyRoomState`, filtered so a viewer
only ever sees what has actually been promoted/disclosed to THEM.

Split out of `stacks_engine.py` (already over the module-line-cap, frozen per
this wave's brief) rather than growing that file -- `stacks_engine.py.project()`
gains only a minimal two-line hook that imports and calls this module, mirroring
exactly how it already folds in `_project_puzzles`/`_neutral_shop_snapshot`.
This module imports `content.rooms`/`content.npcs`/`content.study_loader` and
`domain.state` only -- never `stacks_engine`/`stacks_protocol` -- so the
dependency stays one-directional (engine -> projection, never back).

Disclosure rules enforced here (never trust a caller to have already filtered):
  - Object `states`: a state is only ever included if its own `visibility` is
    FREE, or its id is present in `StudyRoomState.promoted_object_ids[viewer]`.
    A HIDDEN/NOTICED state never leaks to a viewer who hasn't had it promoted,
    even though `object_state_ids` (engine-authoritative current state) may
    already have advanced past it -- the wire never serializes "the true
    current state" for a state this viewer hasn't earned.
  - `promoted_fact_ids`: this viewer's own promotions only (never another
    hero's ledger) -- mirrors `PuzzleRoomState.private_clue_assignments` /
    `your_private_clues`'s existing "your own key only" wire discipline.
  - NPC objectives: only `PUBLIC`/`PARTY`-scoped objectives are ever
    serialized (an `ENGINE_ONLY`-scoped hidden objective, e.g. Elara's, is
    never present in ANY viewer's projection, not even redacted) -- this is
    exactly the set `converse`'s `appeal_objective_id` may legitimately name,
    so the client's appeal picker is built from this list and nothing else.
  - `RoomTemplate.secrets` with `viewer_scope: engine_only` and
    `RunState.content_gaps` are never read by this module at all -- there is
    no code path here that could leak them, by construction (this module
    never imports/looks at either field).
  - A spectator (`viewer is None`) gets object/NPC public-tier data (the
    room's FREE-visibility states and PARTY/PUBLIC NPC objectives are party
    knowledge, not owner-only) but empty per-hero ledgers (`promoted_object_ids`/
    `promoted_fact_ids`), matching `project_puzzles`'s existing
    "viewer is None -> no per-hero data" rule.
"""
from __future__ import annotations

from typing import Any

from backend.lan_playground.content import study_loader
from backend.lan_playground.content.rooms import ObjectVisibility, RoomTemplate
from backend.lan_playground.content.schemas import ViewerScope
from backend.lan_playground.domain.state import RunState as DomainRunState
from backend.lan_playground.domain.state import StudyRoomState


def _study_pack() -> study_loader.StudyContentPack:
    # Mirrors systems/study_wire.py's own @functools.lru_cache(maxsize=1)
    # module-level cache -- a second independent cache here is deliberate:
    # this module must never import systems/study_wire.py (that would be a
    # projection -> domain-wiring dependency, backwards from every other
    # projection helper in this codebase), so it cannot reuse that cache
    # directly. load_study_pack() is itself a pure, side-effect-free parse of
    # static YAML, so two independent caches of the same content is cheap and
    # correct, not a source of drift.
    return study_loader.load_study_pack()


def _room_template(room_template_id: str) -> RoomTemplate | None:
    return _study_pack().rooms.get(room_template_id)


def _object_states_view(obj, study: StudyRoomState, viewer: str | None) -> dict[str, Any] | None:
    """One object's projected view, or None if this object is not yet visible
    to this viewer AT ALL (its current state's own visibility is HIDDEN/
    NOTICED and the OBJECT id has never been promoted for this viewer --
    `StudyRoomState.promoted_object_ids` records promoted OBJECT ids, per
    `study_wire._promote_object_state`'s signature, never state ids).

    Once an object is visible at all (FREE-visibility current state, or the
    object id itself has been promoted for this viewer), its TRUE current
    state is what projects -- never an earlier/weaker state -- because
    promotion means the viewer has earned the disclosure event that
    accompanied whatever transition put the object in that state (e.g.
    `hidden_compartment` is only ever promoted at the moment it becomes
    `compartment_closed`, so a promoted viewer seeing it later in
    `compartment_open` is exactly correct, not a leak)."""

    promoted = set(study.promoted_object_ids.get(viewer, ())) if viewer is not None else set()
    current_state_id = study.object_state_ids.get(obj.id)
    current_state = obj.state_by_id(current_state_id) if current_state_id is not None else None
    if current_state is None:
        return None
    if current_state.visibility != ObjectVisibility.FREE and obj.id not in promoted:
        # Never narrated to this viewer yet -- omit the object entirely
        # rather than leaking its existence via an earlier placeholder state.
        return None
    visible_state = current_state

    interactions = []
    for interaction in obj.interactions:
        legal = visible_state.id in interaction.legal_states
        if not interaction.repeatable and interaction.id in study.fired_interaction_ids.get(obj.id, ()):
            legal = False
        interactions.append(
            {
                "id": interaction.id,
                "verb": interaction.verb,
                "fallback": interaction.prose.fallback,
                "accessible": interaction.prose.accessible,
                "legal": legal,
            }
        )

    return {
        "id": obj.id,
        "name": obj.name,
        "state_id": visible_state.id,
        "fallback": visible_state.prose.fallback,
        "accessible": visible_state.prose.accessible,
        "interactions": interactions,
    }


def _npc_view(npc_id: str | None, study: StudyRoomState) -> dict[str, Any] | None:
    if npc_id is None:
        return None
    npc = _study_pack().npcs.get(npc_id)
    if npc is None:
        return None

    # Only PUBLIC/PARTY-scoped objectives are ever serialized -- an
    # ENGINE_ONLY hidden objective (Elara's "avoid confronting her own
    # death") is never present here, in any viewer's projection, not even
    # redacted. This is deliberately the exact set converse's
    # appeal_objective_id may legitimately name.
    disclosed_objectives = [
        {
            "id": objective.id,
            "kind": objective.kind.value,
            "fallback": objective.prose.fallback,
            "accessible": objective.prose.accessible,
        }
        for objective in npc.objectives
        if objective.viewer_scope in (ViewerScope.PUBLIC, ViewerScope.PARTY)
    ]

    return {
        "npc_id": npc_id,
        "disposition": study.npc_disposition,
        "objectives": disclosed_objectives,
        "objective_states": dict(sorted(study.npc_objective_states.items())),
    }


def _project_one_room(study: StudyRoomState, viewer: str | None) -> dict[str, Any] | None:
    template = _room_template(study.room_template_id)
    if template is None:
        return None

    objects = []
    for obj in template.objects:
        entry = _object_states_view(obj, study, viewer)
        if entry is not None:
            objects.append(entry)

    payoff = template.payoff_interaction
    payoff_triggered = payoff.interaction_id in study.fired_interaction_ids.get(payoff.object_id, ())

    return {
        "room_template_id": study.room_template_id,
        "objects": objects,
        # Own-viewer-only ledgers (empty for a spectator/other hero), same
        # "your own key only" rule PuzzleRoomState.private_clue_assignments's
        # your_private_clues already uses on the wire.
        "promoted_object_ids": list(study.promoted_object_ids.get(viewer, ())) if viewer is not None else [],
        "promoted_fact_ids": list(study.promoted_fact_ids.get(viewer, ())) if viewer is not None else [],
        "npc": _npc_view(study.npc_id, study),
        "payoff_triggered": payoff_triggered,
        "resolved": study.resolved,
    }


def project_study(domain_state: DomainRunState | None, viewer: str | None) -> dict[str, Any]:
    """Top-level `"study"` projection key, room_id -> the shape above. Empty
    dict if there is no domain map yet (pre-golden-floor-generation) or no
    room currently holds a `StudyRoomState` -- never raises, matching every
    other project_* helper's "absent means empty, not an error" discipline."""

    if domain_state is None or domain_state.map is None:
        return {}
    projected: dict[str, Any] = {}
    for room_id, room in domain_state.map.rooms.items():
        if room.study is None:
            continue
        entry = _project_one_room(room.study, viewer)
        if entry is not None:
            projected[room_id] = entry
    return projected
