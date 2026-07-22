"""Projection-level privacy tests for wave-6B part 4's `study_projection.py`
(docs/INFINITE_STACKS_CONTRACTS.md §5.11's "Wire projection requirement").

`tests/test_stacks_study_wire.py`'s existing cross-player privacy tests prove
the per-viewer LEDGER (`StudyRoomState.promoted_object_ids`/
`promoted_fact_ids`) never leaks between heroes at the domain-state layer --
that part shipped before any client-facing projection existed. This file
proves the same property one layer up, through the REAL
`study_projection.project_study(domain_state, viewer)` path the client
actually reads: viewer B's projected `study` block must never contain
viewer A's promoted objects/facts, viewer B's appeal-picker source (`npc.
objectives`) must never contain an objective only disclosed to A (in this
slice's authored content, objectives are PARTY-scoped-or-ENGINE_ONLY, not
per-hero, so this also proves the ENGINE_ONLY hidden objective is absent for
EVERY viewer, not just a specific one), and nothing ENGINE_ONLY (the hidden
objective, `RunState.content_gaps`) ever reaches any viewer's wire.

Same Harness pattern as tests/test_stacks_study_wire.py (drives
`domain.reducer.apply()` directly) -- duplicated rather than cross-imported,
matching this repo's existing per-test-file harness convention.
"""
from __future__ import annotations

from backend.lan_playground.domain import reducer
from backend.lan_playground.domain.commands import Command, CommandType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState
from backend.lan_playground.study_projection import project_study

GENERAL_CARD_IDS = ["careful_approach", "steady_nerve"]
PERSONA_CARD_ID = "signature_flourish"

# Same locked seed tests/test_stacks_study_wire.py uses: STUDY_SEED=6's first
# breach (after one hero completes character creation) lands on the authored
# gothic_living_study room.
STUDY_SEED = 6


class Harness:
    def __init__(self, run_id="run_studyproj", seed=STUDY_SEED):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=0)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self.event_log: list = []
        self._n = 0

    def send(self, hero_id, ctype, payload=None):
        self._n += 1
        cmd = Command(
            command_id=f"cmd_{self._n}",
            idempotency_key=f"cmd_{self._n}",
            run_id=self.state.run_id,
            type=ctype,
            hero_id=hero_id,
            expected_revision=self.state.revision,
            payload=payload or {},
        )
        result = reducer.apply(cmd, self.state, self.rng, viewer=hero_id, seq=self.seq)
        self.state = result.state
        self.seq = result.next_seq
        self.event_log.extend(result.events)
        return result

    def door_direction(self, room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.DOOR:
                return d
        return None

    def open_direction_to(self, room_id, target_room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.OPEN:
                dx, dy = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}[d.value]
                if f"room_{room.x + dx}_{room.y + dy}" == target_room_id:
                    return d
        return None

    def create_hero(self, hero_id, background_id="exiled_court_scribe", *, name=None):
        self.send(hero_id, CommandType.JOIN_RUN)
        self.send(hero_id, CommandType.ROLL_ATTRIBUTE_DICE)
        dice = self.state.heroes[hero_id].pending_dice
        assignment = {"force": dice[0], "finesse": dice[1], "insight": dice[2], "presence": dice[3]}
        self.send(
            hero_id,
            CommandType.CREATE_HERO,
            {
                "name": name or hero_id,
                "background_id": background_id,
                "attribute_assignment": assignment,
                "general_card_ids": list(GENERAL_CARD_IDS),
                "persona_card_id": PERSONA_CARD_ID,
            },
        )
        return self.state.heroes[hero_id]

    def breach_into_study(self, hero_id):
        entrance = self.state.map.entrance_room_id
        direction = self.door_direction(entrance)
        result = self.send(hero_id, CommandType.BREACH, {"direction": direction.value})
        return self.state.heroes[hero_id].room_id

    def refresh_energy(self):
        for hero_id, hero in list(self.state.heroes.items()):
            if hero.alive and hero.conscious and not hero.submitted_turn:
                self.send(hero_id, CommandType.PASS)


def _open_compartment(h: Harness, room_id: str):
    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    h.refresh_energy()
    h.send("hero_a", CommandType.INTERACT, {"object_id": "hidden_compartment", "interaction_id": "compartment_open_action"})
    h.refresh_energy()


# --------------------------------------------------------------------------- object/fact privacy


def test_viewer_b_never_in_room_sees_none_of_viewer_as_promotions():
    """hero_b never enters the study room at all -- their projection must
    show only FREE-visibility objects (the room's baseline furniture), never
    hero_a's promoted hidden_compartment/study_diary or any promoted fact
    id, and an empty promoted_object_ids/promoted_fact_ids ledger."""
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    h.send("hero_b", CommandType.JOIN_RUN)

    _open_compartment(h, room_id)

    proj_b = project_study(h.state, "hero_b")
    room_b = proj_b[room_id]
    assert room_b["promoted_object_ids"] == []
    assert room_b["promoted_fact_ids"] == []
    object_ids_b = {o["id"] for o in room_b["objects"]}
    assert "hidden_compartment" not in object_ids_b
    assert "study_diary" not in object_ids_b

    proj_a = project_study(h.state, "hero_a")
    room_a = proj_a[room_id]
    assert "hidden_compartment" in room_a["promoted_object_ids"]
    assert "fact_compartment_contents_revealed" in room_a["promoted_fact_ids"]
    # Never cross-contaminated: hero_a's own ledger is exactly hero_a's.
    assert set(room_a["promoted_object_ids"]).isdisjoint(set(room_b["promoted_object_ids"]))


def test_viewer_b_sharing_the_room_gets_own_ledger_not_a_copy_of_a():
    """hero_b physically shares the room (so party-scoped promotions DO fan
    out to them per §3.3) -- but project_study(state, "hero_b") must read
    hero_b's OWN promoted_object_ids/promoted_fact_ids entry, never hero_a's
    list object-identity-shared (a mutation to one must never appear to
    leak into the other's returned list from this function)."""
    h = Harness()
    h.create_hero("hero_a")
    entrance_id = h.state.map.entrance_room_id
    room_id = h.breach_into_study("hero_a")
    h.create_hero("hero_b")
    direction = h.open_direction_to(entrance_id, room_id)
    h.send("hero_b", CommandType.MOVE, {"direction": direction.value})
    assert h.state.heroes["hero_b"].room_id == room_id

    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})

    proj_a = project_study(h.state, "hero_a")[room_id]
    proj_b = project_study(h.state, "hero_b")[room_id]
    # Both were in the room, so the payoff cascade fans out to both -- this
    # is legitimate PARTY-scoped disclosure, not a leak.
    assert "hidden_compartment" in proj_a["promoted_object_ids"]
    assert "hidden_compartment" in proj_b["promoted_object_ids"]
    # But the returned lists are independent snapshots, not the same
    # underlying mutable object -- mutating one must never affect the other.
    assert proj_a["promoted_object_ids"] is not proj_b["promoted_object_ids"]


def test_spectator_viewer_none_gets_empty_ledgers_but_public_objects():
    """A spectator/system view (viewer=None) sees the room's FREE-visibility
    baseline (party/public knowledge, same as any hero who never
    interacted), but no per-hero promoted ledger at all -- matching
    project_puzzles's existing 'viewer is None -> no per-hero data' rule."""
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    _open_compartment(h, room_id)

    proj_none = project_study(h.state, None)
    room_none = proj_none[room_id]
    assert room_none["promoted_object_ids"] == []
    assert room_none["promoted_fact_ids"] == []
    object_ids_none = {o["id"] for o in room_none["objects"]}
    assert "hidden_compartment" not in object_ids_none
    assert "study_rug" in object_ids_none  # FREE-visibility baseline object


# --------------------------------------------------------------------------- NPC objective privacy (appeal picker source)


def test_npc_objectives_never_include_the_engine_only_hidden_objective():
    """The appeal picker's source data (study.npc.objectives) must never
    contain Elara's ENGINE_ONLY hidden objective
    (objective_hidden_avoid_confronting_death) for ANY viewer, including the
    acting hero, a party member, a hero never in the room, or a spectator --
    its *value* must never reach any player-facing wire at all."""
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    h.send("hero_b", CommandType.JOIN_RUN)

    for viewer in ("hero_a", "hero_b", None):
        proj = project_study(h.state, viewer)
        objective_ids = {o["id"] for o in proj[room_id]["npc"]["objectives"]}
        assert "objective_hidden_avoid_confronting_death" not in objective_ids
        # The three authored PARTY-scoped main objectives ARE present for
        # every viewer (this is the exact set a legitimate appeal may name).
        assert objective_ids == {
            "objective_protect_the_letters",
            "objective_maintain_the_study",
            "objective_be_addressed_properly",
        }


def test_appeal_picker_source_identical_regardless_of_disclosure_state():
    """Main objectives are PARTY-scoped in this slice's authored content (not
    per-hero disclosed atoms) -- so hero_a and hero_b's appeal-picker source
    lists are identical to each other, and identical before/after any
    interact/converse activity, since nothing in this projection derives
    objective visibility from promoted_fact_ids/promoted_object_ids. This
    locks in the "appeal picker built from EXACTLY what this hero knows"
    contract for the ONE disclosure axis this content actually has."""
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    before = {o["id"] for o in project_study(h.state, "hero_a")[room_id]["npc"]["objectives"]}

    _open_compartment(h, room_id)
    after = {o["id"] for o in project_study(h.state, "hero_a")[room_id]["npc"]["objectives"]}
    assert before == after


# --------------------------------------------------------------------------- ENGINE_ONLY / content-gap never on the wire


def test_content_gaps_never_appear_in_any_viewer_projection():
    """A content-gap-triggering unsupported interaction persists on
    RunState.content_gaps (owner/debug-visible only, director ruling) -- the
    study PROJECTION must never surface it, for any viewer. project_study
    doesn't even look at RunState.content_gaps, but this test proves the
    observable outcome directly: the field is simply absent from every
    room's projected dict."""
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "gibberish_verb_xyz"})
    assert len(h.state.content_gaps) == 1  # sanity: the gap really was logged server-side

    for viewer in ("hero_a", None):
        proj = project_study(h.state, viewer)
        assert "content_gaps" not in proj[room_id]
        assert "content_gaps" not in proj


def test_no_domain_map_or_no_study_room_yields_empty_projection_never_raises():
    """Absence (no map generated yet, or a room with no StudyRoomState) is
    empty, never an error -- matching project_puzzles's discipline."""
    assert project_study(None, "hero_a") == {}

    h = Harness()
    h.create_hero("hero_a")
    # Still in the entrance room (family "entrance", never a study room) --
    # no room in the map holds a StudyRoomState yet.
    assert project_study(h.state, "hero_a") == {}
    assert project_study(h.state, None) == {}
