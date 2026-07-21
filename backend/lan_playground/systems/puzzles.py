"""Real Mystery Chamber puzzle rooms (infinite_stacks.md §9.1, §10).

On breach into a `mystery_chamber` room (§7.2's d8 == 1), `exploration.
handle_breach` calls `build_instantiate_events` here to instantiate a real,
seeded `content.puzzles.ordering_sequence` instance -- replacing wave-1's
adapter-synthesized placeholder clue text entirely (that stub lived in
stacks_engine.py and covered both `mystery_chamber` and `study`; this wave's
real implementation covers `mystery_chamber` only, since that is the only
family with an authored puzzle template so far).

Asymmetric distributed clues (§10.3 #8, "no player has the full solution"):
the four inspectable objects (§10.2) are anchor / key / contradiction /
red_herring. Anchor, contradiction, and red_herring are single shared facts
-- any hero physically in the room who inspects one sees the same text.
Key is a *pool* of clue fragments (the ordering chain's individual
`immediately_before` facts): the breaching hero claims the first fragment
immediately as part of breaching (this preserves the wave-1 wire contract of
"breaching a private-clue room fires exactly one private event to the
breacher", which tests/test_stacks_api.py hard-codes); every other hero
claims their own never-before-claimed fragment the first time *they*
`inspect_object` the key object while standing in the room. Once the pool is
exhausted, later inspectors see only whatever they already hold -- with more
heroes than key fragments some heroes end up relying entirely on party
communication, which is the intended design, not a bug.

Solution checking is validator-owned (§10.1, §20.2): `submit_solution` only
ever compares the caller's answer against `instance.accepted_solutions`,
which `content/puzzles/ordering_sequence.py` computes once at instantiation
and `content/puzzles/solver.py` cross-checks independently offline
(tests/test_stacks_puzzles.py). Nothing here re-solves or re-derives an
answer, and the LLM never sees `solution` (§20.2).

Hints and fail-forward (§10.4): three escalating hints; requesting a hint a
fourth time (after all three are spent) is how a party accepts the defined
consequence and force-progresses past the room. Every wrong `submit_solution`
also fires the instance's `failure_events` through `systems/effects.py` --
never "nothing happens" (§4.1) -- and exhausting `attempt_limit` wrong
guesses force-progresses the same way as exhausting hints.
"""
from __future__ import annotations

from ..content import schemas as S
from ..content.puzzles import ordering_sequence
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import PuzzleObjectView, PuzzleRoomState, RoomState, RunState
from . import effects, turns

_KEY_ROLE = S.PuzzleObjectRole.KEY.value


def _hero(state: RunState, hero_id: str | None):
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    return state.heroes[hero_id]


def _puzzle_room(state: RunState, hero_id: str) -> tuple[RoomState, PuzzleRoomState]:
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    if room.puzzle is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no active puzzle in {hero.room_id}")
    return room, room.puzzle


def _require_open_puzzle(puzzle: PuzzleRoomState) -> None:
    if puzzle.solved:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "puzzle already solved")
    if puzzle.forced:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "puzzle already resolved by forced progress")


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
    rolled family is mystery_chamber. Draws exactly one RNG value (contract
    §9: handle() is the only rng caller); the instance is fully
    reconstructible from (puzzle_seed, difficulty) alone, so reduce()'s
    applier below never touches rng again for these events."""

    puzzle_seed = rng.randint(0, 2**31 - 1)
    difficulty = max(1, min(5, 1 + state.chapter_floor_index))
    instance = ordering_sequence.generate_instance(seed=puzzle_seed, difficulty=difficulty)

    events: list[Event] = [
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.MYSTERY_PUZZLE_INSTANTIATED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=breaching_hero_id,
            room_id=room_id,
            payload={
                "room_id": room_id,
                "instance_id": instance.id,
                "template_id": instance.template_id,
                "puzzle_seed": puzzle_seed,
                "difficulty": difficulty,
            },
        )
    ]

    key_object = next(o for o in instance.objects if o.role is S.PuzzleObjectRole.KEY)
    first_clue_id = key_object.clue_ids[0]
    clue = next(c for c in instance.clues if c.id == first_clue_id)
    events.append(
        Event(
            event_id=make_event_id(state.world_round, seq + 1),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.PRIVATE_CLUE_REVEALED,
            visibility=Visibility.PRIVATE,
            actor_hero_id=breaching_hero_id,
            room_id=room_id,
            payload={
                "viewer_hero_id": breaching_hero_id,
                "clues": [
                    {"clue_id": clue.id, "fallback": clue.prose.fallback, "accessible": clue.prose.accessible}
                ],
            },
        )
    )
    return tuple(events)


def apply_mystery_puzzle_instantiated(state: RunState, event: Event) -> RunState:
    payload = event.payload
    instance = ordering_sequence.generate_instance(seed=payload["puzzle_seed"], difficulty=payload["difficulty"])
    room = state.map.rooms[payload["room_id"]]

    objects = tuple(
        PuzzleObjectView(id=o.id, role=o.role.value, fallback=o.prose.fallback, accessible=o.prose.accessible)
        for o in instance.objects
    )
    object_clue_ids = {o.id: tuple(o.clue_ids) for o in instance.objects}
    clue_text = {c.id: (c.prose.fallback, c.prose.accessible) for c in instance.clues}
    key_object = next(o for o in instance.objects if o.role is S.PuzzleObjectRole.KEY)

    # submit_solution's {solution: [item_id, ...]} refers to these ids -- expose
    # them PUBLIC in a fixed lexicographic order that never depends on the
    # shuffled `instance.solution` order (never itself put on the wire), so a
    # client can build a valid submission without seeing the answer (director
    # fix, 2026-07-19). ordering_sequence is the only puzzle template this
    # wave; systems/puzzles.py is already coupled to it (see module docstring).
    items = tuple(
        {"item_id": item_id, "fallback": ordering_sequence.item_name(item_id), "accessible": f"Item: {ordering_sequence.item_name(item_id)}"}
        for item_id in sorted(instance.solution)
    )

    room.puzzle = PuzzleRoomState(
        instance_id=instance.id,
        template_id=instance.template_id,
        seed=payload["puzzle_seed"],
        difficulty=payload["difficulty"],
        objects=objects,
        items=items,
        object_clue_ids=object_clue_ids,
        clue_text=clue_text,
        unclaimed_key_clue_ids=list(key_object.clue_ids),
        private_clue_assignments={},
        solution=tuple(instance.solution),
        accepted_solutions=tuple(tuple(sol) for sol in instance.accepted_solutions),
        hint_steps=tuple((h.fallback, h.accessible) for h in instance.hint_steps),
        attempt_limit=instance.attempt_limit,
        failure_effects=tuple(S.compile_effects(list(instance.failure_events))),
        success_effects=tuple(S.compile_effects(list(instance.success_events))),
    )
    return state


def apply_private_clue_revealed(state: RunState, event: Event) -> RunState:
    hero_id = event.payload["viewer_hero_id"]
    room = state.map.rooms[event.room_id]
    puzzle = room.puzzle
    clue_ids = tuple(c["clue_id"] for c in event.payload["clues"])
    existing = puzzle.private_clue_assignments.get(hero_id, ())
    puzzle.private_clue_assignments[hero_id] = tuple(dict.fromkeys(existing + clue_ids))
    for cid in clue_ids:
        if cid in puzzle.unclaimed_key_clue_ids:
            puzzle.unclaimed_key_clue_ids.remove(cid)
    return state


# ---------------------------------------------------------------- inspect_object


def validate_inspect_object(state: RunState, hero_id: str | None, payload: dict) -> tuple[RoomState, PuzzleRoomState, str]:
    room, puzzle = _puzzle_room(state, hero_id)
    object_id = payload.get("object_id")
    if object_id not in puzzle.object_clue_ids:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown puzzle object {object_id!r}")
    turns.require_energy(state, hero_id, "inspect")
    return room, puzzle, object_id


def handle_inspect_object(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, puzzle, object_id = validate_inspect_object(state, hero_id, command.payload)
    hero = state.heroes[hero_id]

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["inspect"], "action": "inspect_object"},
    )

    obj = next(o for o in puzzle.objects if o.id == object_id)
    object_clue_ids = puzzle.object_clue_ids[object_id]
    owned = set(puzzle.private_clue_assignments.get(hero_id, ()))

    newly_claimed_id = None
    if obj.role == _KEY_ROLE and not owned and puzzle.unclaimed_key_clue_ids:
        newly_claimed_id = puzzle.unclaimed_key_clue_ids[0]
        owned = {newly_claimed_id}

    if obj.role == _KEY_ROLE:
        visible_ids = [cid for cid in object_clue_ids if cid in owned]
    else:
        visible_ids = list(object_clue_ids)

    revealed = [
        {"clue_id": cid, "fallback": puzzle.clue_text[cid][0], "accessible": puzzle.clue_text[cid][1]}
        for cid in visible_ids
    ]

    inspect_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.PUZZLE_OBJECT_INSPECTED,
        visibility=Visibility.PRIVATE,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "viewer_hero_id": hero_id,
            "object_id": object_id,
            "role": obj.role,
            "fallback": obj.fallback,
            "accessible": obj.accessible,
            "revealed_clues": revealed,
        },
    )

    events: list[Event] = [energy_event, inspect_event]
    if newly_claimed_id is not None:
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + 2),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.PRIVATE_CLUE_REVEALED,
                visibility=Visibility.PRIVATE,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"viewer_hero_id": hero_id, "clues": revealed},
            )
        )
    return tuple(events)


def apply_puzzle_object_inspected(state: RunState, event: Event) -> RunState:
    return state


# ---------------------------------------------------------------- submit_solution


def validate_submit_solution(state: RunState, hero_id: str | None, payload: dict) -> tuple[RoomState, PuzzleRoomState]:
    room, puzzle = _puzzle_room(state, hero_id)
    _require_open_puzzle(puzzle)
    solution = payload.get("solution")
    if not isinstance(solution, (list, tuple)) or not all(isinstance(x, str) for x in solution):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "solution must be a list of item ids")
    return room, puzzle


def handle_submit_solution(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, puzzle = validate_submit_solution(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    candidate = tuple(command.payload["solution"])
    attempts_used = puzzle.attempts_used + 1

    events: list[Event] = []
    if candidate in puzzle.accepted_solutions:
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.PUZZLE_SOLUTION_ACCEPTED,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"attempts_used": attempts_used},
            )
        )
        events.extend(
            effects.dispatch(
                list(puzzle.success_effects),
                command=command,
                state=state,
                rng=rng,
                seq=seq + len(events),
                actor_hero_id=hero_id,
                room_id=hero.room_id,
            )
        )
        return tuple(events)

    force = puzzle.attempt_limit is not None and attempts_used >= puzzle.attempt_limit
    events.append(
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.PUZZLE_SOLUTION_REJECTED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={"attempts_used": attempts_used, "attempt_limit": puzzle.attempt_limit, "forced": force},
        )
    )
    events.extend(
        effects.dispatch(
            list(puzzle.failure_effects),
            command=command,
            state=state,
            rng=rng,
            seq=seq + len(events),
            actor_hero_id=hero_id,
            room_id=hero.room_id,
        )
    )
    if force:
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + len(events)),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.PUZZLE_FORCE_PROGRESS,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"reason": "attempts_exhausted"},
            )
        )
    return tuple(events)


def apply_puzzle_solution_accepted(state: RunState, event: Event) -> RunState:
    puzzle = state.map.rooms[event.room_id].puzzle
    puzzle.solved = True
    puzzle.attempts_used = event.payload["attempts_used"]
    return state


def apply_puzzle_solution_rejected(state: RunState, event: Event) -> RunState:
    state.map.rooms[event.room_id].puzzle.attempts_used = event.payload["attempts_used"]
    return state


def apply_puzzle_force_progress(state: RunState, event: Event) -> RunState:
    state.map.rooms[event.room_id].puzzle.forced = True
    return state


# ---------------------------------------------------------------- request_hint


def validate_request_hint(state: RunState, hero_id: str | None, payload: dict) -> tuple[RoomState, PuzzleRoomState]:
    room, puzzle = _puzzle_room(state, hero_id)
    _require_open_puzzle(puzzle)
    return room, puzzle


def handle_request_hint(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, puzzle = validate_request_hint(state, hero_id, command.payload)
    hero = state.heroes[hero_id]

    if puzzle.hints_used < len(puzzle.hint_steps):
        index = puzzle.hints_used
        fallback, accessible = puzzle.hint_steps[index]
        return (
            Event(
                event_id=make_event_id(state.world_round, seq),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.PUZZLE_HINT_REVEALED,
                visibility=Visibility.PARTY,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"hint_index": index, "fallback": fallback, "accessible": accessible},
            ),
        )

    # §10.4: once all three hints are spent, requesting again is how the
    # party accepts the defined consequence and force-progresses the room.
    events: list[Event] = [
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.PUZZLE_FORCE_PROGRESS,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={"reason": "hints_exhausted"},
        )
    ]
    events.extend(
        effects.dispatch(
            list(puzzle.failure_effects),
            command=command,
            state=state,
            rng=rng,
            seq=seq + len(events),
            actor_hero_id=hero_id,
            room_id=hero.room_id,
        )
    )
    return tuple(events)


def apply_puzzle_hint_revealed(state: RunState, event: Event) -> RunState:
    state.map.rooms[event.room_id].puzzle.hints_used = event.payload["hint_index"] + 1
    return state


# ---------------------------------------------------------------- share_clue


def validate_share_clue(state: RunState, hero_id: str | None, payload: dict) -> tuple[RoomState, str]:
    """Wave 5 addition (board task #18): a hero shares one of their own
    private clues (§10.3's asymmetric distributed clues) to the party --
    server-side, so shared notes sync across browsers instead of staying
    client-local (board note 14). Client wiring is stacks-heroui's side; this
    only needs the caller to already own `clue_id` (`_KEY_ROLE`'s per-hero
    `private_clue_assignments`, the same ledger `inspect_object` populates)."""

    room, puzzle = _puzzle_room(state, hero_id)
    clue_id = payload.get("clue_id")
    owned = puzzle.private_clue_assignments.get(hero_id, ())
    if clue_id not in owned:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} does not own clue {clue_id!r}")
    return room, clue_id


def handle_share_clue(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, clue_id = validate_share_clue(state, hero_id, command.payload)
    puzzle = room.puzzle
    fallback, accessible = puzzle.clue_text[clue_id]
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.CLUE_SHARED,
            visibility=Visibility.PARTY,
            actor_hero_id=hero_id,
            room_id=room.room_id,
            payload={"clue_id": clue_id, "fallback": fallback, "accessible": accessible},
        ),
    )


def apply_clue_shared(state: RunState, event: Event) -> RunState:
    room_id = event.room_id
    existing = state.party_shared_clues.get(room_id, ())
    clue_id = event.payload["clue_id"]
    if clue_id not in existing:
        state.party_shared_clues[room_id] = existing + (clue_id,)
    return state


# ---------------------------------------------------------------- legal actions


def legal_action_names(state: RunState, hero_id: str) -> list[str]:
    hero = state.heroes.get(hero_id)
    if hero is None or state.map is None:
        return []
    room = state.map.rooms.get(hero.room_id)
    if room is None or room.puzzle is None:
        return []
    actions: list[str] = []
    if not room.puzzle.solved and not room.puzzle.forced:
        actions.extend(["inspect_object", "submit_solution", "request_hint"])
    owned = room.puzzle.private_clue_assignments.get(hero_id, ())
    shared = state.party_shared_clues.get(room.room_id, ())
    if any(cid not in shared for cid in owned):
        actions.append("share_clue")
    return actions


EVENT_APPLIERS = {
    EventType.MYSTERY_PUZZLE_INSTANTIATED: apply_mystery_puzzle_instantiated,
    EventType.PRIVATE_CLUE_REVEALED: apply_private_clue_revealed,
    EventType.PUZZLE_OBJECT_INSPECTED: apply_puzzle_object_inspected,
    EventType.PUZZLE_HINT_REVEALED: apply_puzzle_hint_revealed,
    EventType.PUZZLE_SOLUTION_ACCEPTED: apply_puzzle_solution_accepted,
    EventType.PUZZLE_SOLUTION_REJECTED: apply_puzzle_solution_rejected,
    EventType.PUZZLE_FORCE_PROGRESS: apply_puzzle_force_progress,
    EventType.CLUE_SHARED: apply_clue_shared,
}
