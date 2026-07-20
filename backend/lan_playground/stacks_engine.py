"""The Lost Meaning: Infinite Stacks -- StacksEngineAdapter, the ONE seam.

Isolates every engine call (validate/handle/reduce, per
docs/INFINITE_STACKS_CONTRACTS.md S1 and infinite_stacks.md S22.1) behind one
class. ``StacksEngineAdapter`` now delegates the golden-floor rules (map
generation, movement, breach, energy, world rounds, checks) to the real
``backend.lan_playground.{domain,systems}`` engine -- this is the ONLY module
that imports domain/systems. stacks_api.py's transport, connection hub, and
REST/WS routes never touch engine internals directly, and stacks_projections
.py's viewer-filtering never changes shape underneath them: this class
translates between the real engine's Command/Event/RunState shapes and the
wire shapes in stacks_protocol.py, which is a stable contract the client was
built against and does not change here.

Wave 2 (board task #5): the wave-1 adapter-synthesized private-clue
embellishment is gone. Mystery Chamber rooms now run a real, seeded
`content.puzzles.ordering_sequence` instance through `backend.lan_playground.
systems.puzzles`; this class only translates the resulting domain events
(mystery_puzzle_instantiated, private_clue_revealed, puzzle_object_inspected,
puzzle_hint_revealed, puzzle_solution_accepted/rejected, puzzle_force_progress)
into wire events and folds a solution-free puzzle snapshot into `project()`
-- it never invents puzzle content itself anymore.

Split out of stacks_api.py (board task #3 follow-up) to keep each module
under the infinite_stacks.md S22.2 soft 500-line cap.
"""

from __future__ import annotations

import random
import uuid
from typing import Any

from backend.lan_playground.domain import reducer as domain_reducer
from backend.lan_playground.domain.commands import Command as DomainCommand
from backend.lan_playground.domain.commands import CommandError as DomainCommandError
from backend.lan_playground.domain.commands import CommandType as DomainCommandType
from backend.lan_playground.domain.events import Event as DomainEvent
from backend.lan_playground.domain.events import EventType as DomainEventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConflictEncounterState
from backend.lan_playground.domain.state import HeroState as DomainHeroState
from backend.lan_playground.domain.state import RunState as DomainRunState
from backend.lan_playground.systems import heroes_wire, map_generation

from backend.lan_playground.stacks_projections import events_since as _events_since
from backend.lan_playground.stacks_projections import legal_actions as _legal_actions
from backend.lan_playground.stacks_projections import project as _project
from backend.lan_playground.stacks_projections import project_puzzles as _project_puzzles
from backend.lan_playground.stacks_protocol import (
    DISPLAY_NAME_MAX_CHARS,
    ApplyResult,
    Command,
    CommandError,
    Connector,
    Event,
    Hero,
    Room,
    RunState,
    _IdemRecord,
)

# Domain ConnectorState.value -> wire Connector.state (contract doc S6: real
# engine is 3-state NONE|DOOR|OPEN; wire's Literal keeps "locked" for a future
# wave and never emits it here).
_WIRE_CONNECTOR_STATE = {"none": "none", "door": "undiscovered", "open": "open"}
_DOMAIN_DELTA = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}


class StacksEngineAdapter:
    """Isolates every engine call (validate/handle/reduce/project) behind one
    class, delegating to the real domain/systems pipeline. Each ``RunState``
    this class hands to callers is a wire-shape object (stacks_protocol.py);
    internally the adapter keeps a real ``domain.state.RunState`` + seeded
    ``StacksRNG`` per run_id and keeps the two in sync on every ``apply()``.
    """

    def __init__(self) -> None:
        self._domain_states: dict[str, DomainRunState] = {}
        self._rngs: dict[str, StacksRNG] = {}
        self._seqs: dict[str, int] = {}
        self._names: dict[tuple[str, str], str] = {}

    def create_run(self, seed: int, chapter_floor_index: int = 0) -> RunState:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        self._domain_states[run_id] = DomainRunState.initial(
            run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index
        )
        self._rngs[run_id] = StacksRNG(seed)
        self._seqs[run_id] = 0

        required_rooms = map_generation.required_room_count(chapter_floor_index)
        maximum_rooms = map_generation.maximum_room_count(required_rooms)
        return RunState(
            run_id=run_id,
            seed=seed,
            revision=0,
            world_round=1,
            chapter_floor_index=chapter_floor_index,
            required_rooms=required_rooms,
            maximum_rooms=maximum_rooms,
            heroes={},
            rooms={},
            pending_turns={},
            event_log=[],
            _applied={},
            _rng=random.Random(seed),
        )

    def legal_actions(self, state: RunState, hero_id: str | None) -> dict[str, Any]:
        return _legal_actions(state, hero_id)

    def project(self, state: RunState, viewer: str | None) -> dict[str, Any]:
        base = _project(state, viewer)
        domain_state = self._domain_states.get(state.run_id)
        puzzles_by_room: dict[str, Any] = {}
        conflict_by_room: dict[str, Any] = {}
        if domain_state is not None and domain_state.map is not None:
            for room_id, room in domain_state.map.rooms.items():
                if room.puzzle is not None:
                    puzzles_by_room[room_id] = self._neutral_puzzle_snapshot(room.puzzle)
                if room.encounter is not None:
                    conflict_by_room[room_id] = self._neutral_conflict_snapshot(room.encounter, domain_state.heroes)
        base["puzzles"] = _project_puzzles(puzzles_by_room, viewer)
        base["conflict"] = conflict_by_room
        return base

    @staticmethod
    def _neutral_conflict_snapshot(
        encounter: Any, domain_heroes: dict[str, DomainHeroState] | None = None
    ) -> dict[str, Any]:
        """Domain ConflictEncounterState -> a viewer-agnostic wire-safe dict
        (docs/INFINITE_STACKS_CONTRACTS.md §5.3). No hidden combat state
        leaks: no resists/weaknesses/converts tables, no un-telegraphed
        intent (that folds from combat_events on each conflict_* wire event
        instead, same pattern as puzzles' hints_revealed). Never imports
        backend.lan_playground.combat -- everything needed is already a
        plain field on the domain snapshot.

        `legal_attacks` (wave-4, board task #13 acceptance item 5): a
        per-hero enumeration of real attack options against every living
        enemy, built from the hero's actual character-sheet skill rank and
        resolved weapon (heroes_wire.resolve_hero_combat_equipment) -- never
        a client-suppliable number -- so the combat UI can render per-target
        buttons instead of a generic form. Empty for a hero with no
        `domain_heroes` entry or no completed character creation yet
        (pre-wave-4 heroes), matching every other seam's zero-modifier
        fallback."""

        living_ids = {hid for hid, h in encounter.heroes.items() if h["life_state"] == "alive"}
        living_enemy_ids = {eid for eid, e in encounter.enemies.items() if e["alive"]}
        living_ids |= living_enemy_ids
        initiative_order = [c["combatant_id"] for c in encounter.order if c["combatant_id"] in living_ids]

        domain_heroes = domain_heroes or {}
        heroes_wire_data: dict[str, Any] = {}
        for hid, h in encounter.heroes.items():
            legal_attacks: list[dict[str, Any]] = []
            domain_hero = domain_heroes.get(hid)
            if h["life_state"] == "alive" and domain_hero is not None and domain_hero.sheet is not None:
                equipment = heroes_wire.resolve_hero_combat_equipment(domain_hero)
                accuracy_bonus = (
                    domain_hero.sheet.attributes.get("force")
                    + domain_hero.sheet.skills.get("bonk", 0)
                    + equipment["weapon"].accuracy_bonus
                    + equipment["equipment_accuracy_bonus"]
                )
                damage_bonus = equipment["weapon"].damage_bonus + equipment["equipment_damage_bonus"]
                for eid in sorted(living_enemy_ids):
                    legal_attacks.append(
                        {
                            "type": "attack",
                            "target_id": eid,
                            "accuracy_bonus": accuracy_bonus,
                            "weapon_die_faces": equipment["weapon"].die_faces,
                            "damage_bonus": damage_bonus,
                        }
                    )
            heroes_wire_data[hid] = {
                "hp": h["hp"],
                "max_hp": h["max_hp"],
                "life_state": h["life_state"],
                "position": h["position"],
                "reaction_available": h["reaction_available"],
                "legal_attacks": legal_attacks,
            }

        return {
            "encounter_id": encounter.encounter_id,
            "status": encounter.status,
            "combat_round": encounter.combat_round,
            "current_actor_id": encounter.current_actor_id,
            "initiative_order": initiative_order,
            "heroes": heroes_wire_data,
            "enemies": {
                eid: {"name": e["name"], "hp": e["hp"], "max_hp": e["max_hp"], "alive": e["alive"], "position": e["position"]}
                for eid, e in encounter.enemies.items()
            },
            "threat_budget": dict(encounter.threat_budget),
        }

    @staticmethod
    def _neutral_puzzle_snapshot(puzzle: Any) -> dict[str, Any]:
        """Domain PuzzleRoomState -> a viewer-agnostic wire-safe dict. Never
        includes `solution`/`accepted_solutions` (contract: never serialized
        in any projection) -- stacks_projections.project_puzzles() does the
        remaining per-viewer filtering of `private_clues`."""

        return {
            "instance_id": puzzle.instance_id,
            "template_id": puzzle.template_id,
            "difficulty": puzzle.difficulty,
            "objects": [o.to_dict() for o in puzzle.objects],
            "items": [dict(i) for i in puzzle.items],
            "solved": puzzle.solved,
            "forced": puzzle.forced,
            "attempts_used": puzzle.attempts_used,
            "attempt_limit": puzzle.attempt_limit,
            "hints_revealed": [
                {"fallback": fallback, "accessible": accessible}
                for fallback, accessible in puzzle.hint_steps[: puzzle.hints_used]
            ],
            "private_clues": {
                hero_id: [
                    {
                        "clue_id": cid,
                        "fallback": puzzle.clue_text[cid][0],
                        "accessible": puzzle.clue_text[cid][1],
                    }
                    for cid in clue_ids
                ]
                for hero_id, clue_ids in puzzle.private_clue_assignments.items()
            },
        }

    def events_since(self, state: RunState, viewer: str | None, since_revision: int) -> list[Event]:
        return _events_since(state, viewer, since_revision)

    def apply(self, state: RunState, command: Command) -> ApplyResult:
        key = (command.hero_id or "", command.idempotency_key)
        prior = state._applied.get(key)
        if prior is not None:
            return ApplyResult(events=prior.events, revision=prior.revision, replayed=True)

        if command.type != "join_run" and command.expected_revision != state.revision:
            raise CommandError("stale_revision", legal_actions=self.legal_actions(state, command.hero_id))

        try:
            domain_type = DomainCommandType(command.type)
        except ValueError:
            raise CommandError("schema_error", message="unknown_command_type")

        run_id = state.run_id
        domain_state = self._domain_states[run_id]
        rng = self._rngs[run_id]
        seq = self._seqs[run_id]

        if domain_type == DomainCommandType.JOIN_RUN:
            if not command.hero_id:
                raise CommandError("schema_error", message="missing_hero_id")
            display_name = str(command.payload.get("display_name", "")).strip()
            if not display_name:
                raise CommandError("schema_error", message="missing_display_name")
            self._names[(run_id, command.hero_id)] = display_name[:DISPLAY_NAME_MAX_CHARS]
            payload = dict(command.payload)
        elif domain_type == DomainCommandType.MOVE:
            payload = self._resolve_move_payload(state, command)
        else:
            payload = dict(command.payload)

        domain_command = DomainCommand(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            run_id=run_id,
            type=domain_type,
            hero_id=command.hero_id,
            encounter_id=command.encounter_id,
            expected_revision=domain_state.revision,
            payload=payload,
        )

        try:
            result = domain_reducer.apply(domain_command, domain_state, rng, viewer=command.hero_id, seq=seq)
        except DomainCommandError as exc:
            raise CommandError(
                exc.code.value, legal_actions=self.legal_actions(state, command.hero_id), message=exc.message
            ) from exc

        self._domain_states[run_id] = result.state
        self._seqs[run_id] = result.next_seq

        self._sync_heroes(state, result.state)
        self._sync_rooms(state, result.state)
        wire_events = self._translate_events(state, result.events)

        state.revision += 1
        state.event_log.extend(wire_events)
        state._applied[key] = _IdemRecord(events=tuple(wire_events), revision=state.revision)
        return ApplyResult(events=tuple(wire_events), revision=state.revision, replayed=False)

    # -- wire payload <-> domain payload translation ------------------------

    def _resolve_move_payload(self, state: RunState, command: Command) -> dict[str, Any]:
        # The client sends {"to_room_id": ...} (core/commands.js moveCommand);
        # the real engine's move command takes {"direction": ...}. Resolve the
        # direction from the current wire map so the client contract never
        # has to change. If the hero/room can't be resolved yet, fall through
        # unchanged and let domain validation raise unknown_target naturally.
        hero = state.heroes.get(command.hero_id or "")
        if hero is None:
            return dict(command.payload)
        room = state.rooms.get(hero.room_id)
        to_room_id = command.payload.get("to_room_id")
        direction = None
        if room is not None:
            for d, connector in room.connectors.items():
                if connector.state == "open" and connector.target_room_id == to_room_id:
                    direction = d
                    break
        if direction is None:
            raise CommandError("illegal_action", legal_actions=self.legal_actions(state, command.hero_id))
        return {"direction": direction}

    # -- domain state -> wire state sync (mechanical fields only; wire-only
    # fields like Hero.name/ready/connected/private_clue and Room.secrets are
    # adapter-owned and preserved across syncs) -----------------------------

    def _sync_heroes(self, state: RunState, domain_state: DomainRunState) -> None:
        for hero_id, dh in domain_state.heroes.items():
            wh = state.heroes.get(hero_id)
            if wh is None:
                state.heroes[hero_id] = Hero(
                    hero_id=hero_id,
                    name=self._names.get((state.run_id, hero_id), hero_id),
                    room_id=dh.room_id,
                    energy=dh.energy,
                    max_energy=dh.max_energy,
                    hp=dh.hp,
                    max_hp=dh.max_hp,
                    conscious=dh.conscious,
                    alive=dh.alive,
                    life_state=dh.life_state,
                )
            else:
                wh.room_id = dh.room_id
                wh.energy = dh.energy
                wh.max_energy = dh.max_energy
                wh.hp = dh.hp
                wh.max_hp = dh.max_hp
                wh.conscious = dh.conscious
                wh.alive = dh.alive
                wh.life_state = dh.life_state

    def _sync_rooms(self, state: RunState, domain_state: DomainRunState) -> None:
        if domain_state.map is None:
            return
        state.required_rooms = domain_state.map.required_rooms
        state.maximum_rooms = domain_state.map.maximum_rooms
        for room_id, dr in domain_state.map.rooms.items():
            connectors: dict[str, Connector] = {}
            for direction, dconnector in dr.connectors.items():
                wire_cstate = _WIRE_CONNECTOR_STATE[dconnector.value]
                target = None
                if dconnector.value == "open":
                    dx, dy = _DOMAIN_DELTA[direction.value]
                    target = f"room_{dr.x + dx}_{dr.y + dy}"
                connectors[direction.value] = Connector(state=wire_cstate, target_room_id=target)
            for direction_value in ("north", "east", "south", "west"):
                connectors.setdefault(direction_value, Connector(state="none"))

            wr = state.rooms.get(room_id)
            if wr is None:
                state.rooms[room_id] = Room(
                    room_id=room_id,
                    x=dr.x,
                    y=dr.y,
                    connectors=connectors,
                    family=dr.family,
                    subtype=dr.subtype,
                    discovered=dr.discovered,
                    entered=dr.entered,
                    required=dr.required,
                )
            else:
                wr.connectors = connectors
                wr.family = dr.family
                wr.subtype = dr.subtype
                wr.discovered = dr.discovered
                wr.entered = dr.entered
                wr.required = dr.required

    # -- domain events -> wire events (contract S3/S4) -----------------------

    def _translate_events(self, state: RunState, domain_events: tuple[DomainEvent, ...]) -> list[Event]:
        events: list[Event] = []
        pending_energy = 0
        for de in domain_events:
            if de.type == DomainEventType.MAP_GENERATED:
                continue
            if de.type == DomainEventType.ENERGY_SPENT:
                pending_energy = de.payload["amount"]
                continue

            if de.type == DomainEventType.HERO_JOINED:
                hero_id = de.actor_hero_id
                name = self._names.get((state.run_id, hero_id), hero_id)
                events.append(
                    self._wire_event(state, de, "hero_joined", payload={"hero_id": hero_id, "name": name})
                )
            elif de.type == DomainEventType.HERO_MOVED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "hero_moved",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "from_room_id": de.payload["from_room_id"],
                            "to_room_id": de.payload["to_room_id"],
                            "energy_spent": pending_energy,
                        },
                    )
                )
                pending_energy = 0
            elif de.type == DomainEventType.ROOM_BREACHED:
                events.extend(self._translate_room_breached(state, de, pending_energy))
                pending_energy = 0
            elif de.type == DomainEventType.CONNECTOR_OBSERVED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "connector_observed",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "direction": de.payload["direction"],
                            "target_room_id": de.payload["target_room_id"],
                        },
                    )
                )
                pending_energy = 0
            elif de.type == DomainEventType.ROOM_INSPECTED:
                events.append(self._translate_room_inspected(state, de))
                pending_energy = 0
            elif de.type == DomainEventType.CHECK_RESOLVED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "check_resolved",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "dc": de.payload["dc"],
                            "roll": de.payload["chosen_die"],
                            "total": de.payload["total"],
                            "margin": de.payload["margin"],
                            "outcome": de.payload["outcome"],
                            "natural_20": de.payload["natural_20"],
                            "natural_1": de.payload["natural_1"],
                            "success": de.payload["margin"] >= 0,
                            "energy_spent": pending_energy,
                        },
                    )
                )
                pending_energy = 0
            elif de.type == DomainEventType.MYSTERY_PUZZLE_INSTANTIATED:
                events.append(self._translate_puzzle_instantiated(state, de))
            elif de.type == DomainEventType.PRIVATE_CLUE_REVEALED:
                events.append(self._translate_private_clue_revealed(state, de))
            elif de.type == DomainEventType.PUZZLE_OBJECT_INSPECTED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "object_inspected",
                        visibility="private",
                        visible_to=de.payload["viewer_hero_id"],
                        payload={
                            "object_id": de.payload["object_id"],
                            "role": de.payload["role"],
                            "fallback": de.payload["fallback"],
                            "accessible": de.payload["accessible"],
                            "revealed_clues": de.payload["revealed_clues"],
                        },
                    )
                )
            elif de.type == DomainEventType.PUZZLE_HINT_REVEALED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "puzzle_hint_revealed",
                        visibility="party",
                        payload={
                            "hint_index": de.payload["hint_index"],
                            "fallback": de.payload["fallback"],
                            "accessible": de.payload["accessible"],
                        },
                    )
                )
            elif de.type == DomainEventType.PUZZLE_SOLUTION_ACCEPTED:
                events.append(
                    self._wire_event(
                        state, de, "puzzle_solved", payload={"attempts_used": de.payload["attempts_used"]}
                    )
                )
            elif de.type == DomainEventType.PUZZLE_SOLUTION_REJECTED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "puzzle_solution_rejected",
                        payload={
                            "attempts_used": de.payload["attempts_used"],
                            "attempt_limit": de.payload["attempt_limit"],
                            "forced": de.payload["forced"],
                        },
                    )
                )
            elif de.type == DomainEventType.PUZZLE_FORCE_PROGRESS:
                events.append(
                    self._wire_event(state, de, "puzzle_force_progress", payload={"reason": de.payload["reason"]})
                )
            elif de.type == DomainEventType.ROOM_REVEALED_BY_EFFECT:
                events.append(
                    self._wire_event(
                        state, de, "room_revealed_by_effect", payload={"room_id": de.payload["room_id"]}
                    )
                )
            elif de.type == DomainEventType.EFFECT_ENERGY_SPENT:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "effect_energy_spent",
                        visibility="party",
                        payload={"hero_id": de.actor_hero_id, "amount": de.payload["amount"]},
                    )
                )
            elif de.type == DomainEventType.FACT_EMITTED:
                events.append(
                    self._wire_event(state, de, "fact_emitted", payload={"fact_id": de.payload["fact_id"]})
                )
            elif de.type == DomainEventType.TURN_SUBMITTED:
                events.append(self._wire_event(state, de, "turn_passed", payload={"hero_id": de.actor_hero_id}))
            elif de.type == DomainEventType.WORLD_ROUND_ADVANCED:
                refreshed = [h.hero_id for h in state.heroes.values() if h.alive and h.conscious]
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "world_round_advanced",
                        payload={"world_round": de.payload["next_round"], "refreshed_hero_ids": refreshed},
                    )
                )
                state.world_round = de.payload["next_round"]
            elif de.type == DomainEventType.CONFLICT_ENCOUNTER_STARTED:
                events.append(self._translate_conflict_event(state, de, "conflict_encounter_started"))
            elif de.type == DomainEventType.CONFLICT_TURN_RESOLVED:
                events.append(self._translate_conflict_event(state, de, "conflict_turn_resolved"))
            elif de.type == DomainEventType.CONFLICT_ENCOUNTER_ENDED:
                events.append(self._translate_conflict_event(state, de, "conflict_encounter_ended"))
            elif de.type == DomainEventType.JOINED_CONFLICT_ROOM:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "joined_conflict_room",
                        visibility="party",
                        payload={"hero_id": de.payload["hero_id"], "room_id": de.payload["room_id"]},
                    )
                )
        return events

    def _translate_conflict_event(self, state: RunState, de: DomainEvent, wire_type: str) -> Event:
        """docs/INFINITE_STACKS_CONTRACTS.md §5.3: `combat_events` (raw
        backend.lan_playground.combat event dicts) pass through unchanged so
        the client can fold enemy-intent telegraphs and §12.5 check receipts
        the same way it folds `domain.reducer.project()`'s own event log."""
        encounter_snapshot = ConflictEncounterState.from_dict(de.payload["encounter"])
        domain_state = self._domain_states[state.run_id]
        payload: dict[str, Any] = {
            "room_id": de.payload["room_id"],
            "encounter": self._neutral_conflict_snapshot(encounter_snapshot, domain_state.heroes),
            "combat_events": de.payload["combat_events"],
            "hero_updates": de.payload["hero_updates"],
        }
        if "outcome" in de.payload:
            payload["outcome"] = de.payload["outcome"]
        return self._wire_event(state, de, wire_type, payload=payload)

    def _translate_room_breached(self, state: RunState, de: DomainEvent, energy_spent: int) -> list[Event]:
        hero_id = de.actor_hero_id
        from_room_id = de.payload["from_room_id"]
        to_room_id = de.payload["to_room_id"]
        face = de.payload["d8_face"]
        family = de.payload["family"]
        room = state.rooms[to_room_id]
        direction = self._direction_between(state, from_room_id, to_room_id)

        events = [
            self._wire_event(
                state,
                de,
                "die_rolled",
                payload={"roller_hero_id": hero_id, "value": face, "family": family, "target_room_id": to_room_id},
            ),
            self._wire_event(
                state,
                de,
                "room_revealed",
                payload={
                    "room_id": to_room_id,
                    "x": room.x,
                    "y": room.y,
                    "family": family,
                    "from_room_id": from_room_id,
                    "from_direction": direction,
                },
            ),
            self._wire_event(
                state,
                de,
                "hero_moved",
                payload={
                    "hero_id": hero_id,
                    "from_room_id": from_room_id,
                    "to_room_id": to_room_id,
                    "energy_spent": energy_spent,
                },
            ),
        ]
        return events

    def _translate_room_inspected(self, state: RunState, de: DomainEvent) -> Event:
        hero_id = de.actor_hero_id
        return self._wire_event(
            state, de, "object_inspected", payload={"hero_id": hero_id, "room_id": de.room_id}
        )

    def _translate_puzzle_instantiated(self, state: RunState, de: DomainEvent) -> Event:
        domain_state = self._domain_states[state.run_id]
        room = domain_state.map.rooms[de.payload["room_id"]] if domain_state.map else None
        objects = [o.to_dict() for o in room.puzzle.objects] if room is not None and room.puzzle is not None else []
        return self._wire_event(
            state,
            de,
            "puzzle_instantiated",
            payload={
                "room_id": de.payload["room_id"],
                "instance_id": de.payload["instance_id"],
                "template_id": de.payload["template_id"],
                "difficulty": de.payload["difficulty"],
                "objects": objects,
            },
        )

    def _translate_private_clue_revealed(self, state: RunState, de: DomainEvent) -> Event:
        hero_id = de.payload["viewer_hero_id"]
        clues = de.payload["clues"]
        hero = state.heroes.get(hero_id)
        if hero is not None and clues:
            hero.private_clue = " ".join(c["fallback"] for c in clues)
        return self._wire_event(
            state, de, "private_clue_assigned", visibility="private", visible_to=hero_id, payload={"clues": clues}
        )

    def _direction_between(self, state: RunState, from_room_id: str, to_room_id: str) -> str | None:
        room = state.rooms[from_room_id]
        for direction, connector in room.connectors.items():
            if connector.state == "open" and connector.target_room_id == to_room_id:
                return direction
        return None

    def _wire_event(
        self,
        state: RunState,
        de: DomainEvent,
        wire_type: str,
        *,
        payload: dict[str, Any],
        visibility: str = "public",
        visible_to: str | None = None,
    ) -> Event:
        return Event(
            event_id=state.next_event_id(),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=de.caused_by,
            actor_hero_id=de.actor_hero_id,
            room_id=de.room_id,
            type=wire_type,
            visibility=visibility,
            visible_to=visible_to,
            payload=payload,
        )
