"""Orthogonal tile graph generation (infinite_stacks.md §7.1, §7.3).

Rooms grow from the entrance as a randomized spanning structure: every new
room attaches to an already-placed room at an unoccupied grid coordinate, so
by construction there are no overlaps and every placed room -- including the
exit -- is reachable from the entrance. A handful of extra connector edges
are added afterwards between already-adjacent placed rooms to create loops,
per the "may place loops, forks, ... shortcuts" allowance in §7.1.

Room family/subtype is intentionally NOT rolled here -- §7.2 rolls the d8 at
breach time. This module only decides positions and door topology.
"""
from __future__ import annotations

from ..domain.state import (
    OPPOSITE,
    ConnectorState,
    Direction,
    MapState,
    RoomState,
    room_id_for,
)
from ..domain.rng import StacksRNG

EXTRA_LOOP_EDGE_ATTEMPTS = 3


def required_room_count(chapter_floor_index: int) -> int:
    return min(6 + chapter_floor_index, 12)


def maximum_room_count(required_rooms: int) -> int:
    return required_rooms + 3


def generate_topology(rng: StacksRNG, chapter_floor_index: int) -> MapState:
    required_rooms = required_room_count(chapter_floor_index)
    maximum_rooms = maximum_room_count(required_rooms)

    entrance = RoomState(room_id=room_id_for(0, 0), x=0, y=0, is_entrance=True, discovered=True, entered=True)
    rooms: dict[str, RoomState] = {entrance.room_id: entrance}
    occupied: set[tuple[int, int]] = {(0, 0)}
    placement_order: list[str] = []  # non-entrance rooms in placement order

    total_non_entrance = maximum_rooms
    frontier = [entrance.room_id]

    while len(placement_order) < total_non_entrance:
        source_id = rng.choice(frontier)
        source = rooms[source_id]
        candidate_dirs = rng.shuffled(list(Direction))
        placed_from_source = False
        for direction in candidate_dirs:
            dx, dy = _delta(direction)
            nx, ny = source.x + dx, source.y + dy
            if (nx, ny) in occupied:
                continue
            new_room = RoomState(room_id=room_id_for(nx, ny), x=nx, y=ny)
            rooms[new_room.room_id] = new_room
            occupied.add((nx, ny))
            _connect(source, new_room, direction)
            placement_order.append(new_room.room_id)
            frontier.append(new_room.room_id)
            placed_from_source = True
            break
        if not placed_from_source:
            frontier.remove(source_id)
            if not frontier:
                # exhausted all growth points before reaching the target count;
                # this is only possible on pathologically small grids and never
                # happens for maximum_rooms <= 15 on an unbounded integer grid.
                break

    for _ in range(EXTRA_LOOP_EDGE_ATTEMPTS):
        room_ids = list(rooms.keys())
        a_id = rng.choice(room_ids)
        a = rooms[a_id]
        for direction in rng.shuffled(list(Direction)):
            if a.connectors.get(direction, ConnectorState.NONE) != ConnectorState.NONE:
                continue
            dx, dy = _delta(direction)
            neighbor_id = room_id_for(a.x + dx, a.y + dy)
            if neighbor_id in rooms:
                _connect(a, rooms[neighbor_id], direction)
                break

    required_ids = placement_order[:required_rooms]
    for rid in required_ids:
        rooms[rid].required = True
    exit_room_id = required_ids[-1] if required_ids else entrance.room_id
    rooms[exit_room_id].is_exit = True

    return MapState(
        required_rooms=required_rooms,
        maximum_rooms=maximum_rooms,
        entrance_room_id=entrance.room_id,
        exit_room_id=exit_room_id,
        rooms=rooms,
    )


def _delta(direction: Direction) -> tuple[int, int]:
    from ..domain.state import DELTA

    return DELTA[direction]


def _connect(a: RoomState, b: RoomState, direction: Direction) -> None:
    a.connectors[direction] = ConnectorState.DOOR
    b.connectors[OPPOSITE[direction]] = ConnectorState.DOOR


def all_rooms_reachable(map_state: MapState) -> bool:
    """BFS over connector edges regardless of DOOR/OPEN state (topology, not discovery)."""
    start = map_state.entrance_room_id
    seen = {start}
    stack = [start]
    while stack:
        rid = stack.pop()
        room = map_state.rooms[rid]
        for direction, connector in room.connectors.items():
            if connector == ConnectorState.NONE:
                continue
            dx, dy = _delta(direction)
            neighbor_id = room_id_for(room.x + dx, room.y + dy)
            if neighbor_id in map_state.rooms and neighbor_id not in seen:
                seen.add(neighbor_id)
                stack.append(neighbor_id)
    return seen == set(map_state.rooms.keys())


def has_overlaps(map_state: MapState) -> bool:
    coords = [(r.x, r.y) for r in map_state.rooms.values()]
    return len(coords) != len(set(coords))
