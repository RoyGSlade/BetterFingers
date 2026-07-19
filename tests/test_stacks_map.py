"""Map topology and room-roll property tests (§7.1, §7.2, §7.3)."""
from __future__ import annotations

from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, Direction
from backend.lan_playground.systems import map_generation, room_generation

SEEDS = list(range(1, 201))


def test_required_and_maximum_room_formula():
    assert map_generation.required_room_count(0) == 6
    assert map_generation.required_room_count(1) == 7
    assert map_generation.required_room_count(6) == 12
    assert map_generation.required_room_count(100) == 12  # capped
    assert map_generation.maximum_room_count(6) == 9
    assert map_generation.maximum_room_count(12) == 15


def test_no_overlapping_rooms_across_many_seeds():
    for seed in SEEDS:
        for floor_index in (0, 1, 5, 20):
            rng = StacksRNG(seed * 1000 + floor_index)
            map_state = map_generation.generate_topology(rng, floor_index)
            assert not map_generation.has_overlaps(map_state), f"overlap at seed={seed} floor={floor_index}"


def test_every_room_reachable_from_entrance_across_many_seeds():
    for seed in SEEDS:
        for floor_index in (0, 1, 5, 20):
            rng = StacksRNG(seed * 2000 + floor_index)
            map_state = map_generation.generate_topology(rng, floor_index)
            assert map_generation.all_rooms_reachable(map_state), f"unreachable room at seed={seed} floor={floor_index}"


def test_required_rooms_and_exit_are_flagged_and_reachable():
    for seed in SEEDS:
        rng = StacksRNG(seed * 3000)
        map_state = map_generation.generate_topology(rng, chapter_floor_index=0)
        required = [r for r in map_state.rooms.values() if r.required]
        assert len(required) == map_state.required_rooms
        exit_room = map_state.rooms[map_state.exit_room_id]
        assert exit_room.is_exit
        assert exit_room.required  # exit is one of the required rooms this wave
        assert map_generation.all_rooms_reachable(map_state)


def test_room_count_within_bounds():
    for seed in SEEDS:
        for floor_index in (0, 3, 6, 11):
            rng = StacksRNG(seed * 4000 + floor_index)
            map_state = map_generation.generate_topology(rng, floor_index)
            non_entrance = len(map_state.rooms) - 1
            assert non_entrance <= map_state.maximum_rooms
            assert map_state.required_rooms <= map_state.maximum_rooms


def test_entrance_is_discovered_and_entered_but_not_required():
    rng = StacksRNG(55)
    map_state = map_generation.generate_topology(rng, 0)
    entrance = map_state.rooms[map_state.entrance_room_id]
    assert entrance.is_entrance
    assert entrance.discovered and entrance.entered
    assert entrance.required is False


def test_connectors_are_symmetric():
    from backend.lan_playground.domain.state import OPPOSITE, DELTA, room_id_for

    for seed in SEEDS[:50]:
        rng = StacksRNG(seed * 5000)
        map_state = map_generation.generate_topology(rng, 0)
        for room in map_state.rooms.values():
            for direction, connector in room.connectors.items():
                if connector == ConnectorState.NONE:
                    continue
                dx, dy = DELTA[direction]
                neighbor_id = room_id_for(room.x + dx, room.y + dy)
                assert neighbor_id in map_state.rooms
                neighbor = map_state.rooms[neighbor_id]
                assert neighbor.connectors.get(OPPOSITE[direction]) == connector


# ---------------------------------------------------------------- d8 room roll (§7.2)

def test_d8_face_maps_to_documented_family_table():
    expected = {
        1: "mystery_chamber",
        2: "passage",
        3: "study",
        4: "wild_place",
        5: "conflict",
        6: "shop",
        7: "social_encounter",
        8: "anomaly",
    }
    assert room_generation.FAMILY_BY_D8 == expected


def test_roll_family_never_alters_die_face():
    rng = StacksRNG(321)
    for _ in range(500):
        face, family = room_generation.roll_family(rng)
        assert 1 <= face <= 8
        assert family == room_generation.FAMILY_BY_D8[face]


def test_selected_subtype_is_always_legal_for_rolled_family():
    rng = StacksRNG(654)
    used: dict[str, list[str]] = {}
    for _ in range(500):
        face, family, subtype = room_generation.roll_family_and_subtype(rng, used)
        assert subtype in room_generation.SUBTYPES_BY_FAMILY[family]
        used.setdefault(family, [])
        if subtype not in used[family]:
            used[family].append(subtype)


def test_subtypes_vary_on_repeated_rolls_of_same_family():
    # Force many rolls of the same family by fixing the RNG's d8 outcome and
    # only varying subtype selection, using select_subtype directly.
    rng = StacksRNG(77)
    family = "passage"
    seen: list[str] = []
    used: list[str] = []
    for _ in range(10):
        subtype = room_generation.select_subtype(rng, family, used)
        seen.append(subtype)
        if subtype not in used:
            used.append(subtype)
    # Once every legal subtype has been used at least once, further picks may
    # repeat -- but early picks (fewer than the family's subtype count) must
    # not repeat, proving "varied subtypes" isn't just re-picking the same one.
    legal_count = len(room_generation.SUBTYPES_BY_FAMILY[family])
    assert len(set(seen[:legal_count])) == legal_count
