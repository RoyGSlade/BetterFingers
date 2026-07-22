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

import functools
import random
import uuid
from typing import Any

from backend.lan_playground.content import loader as content_loader
from backend.lan_playground.domain import reducer as domain_reducer
from backend.lan_playground.domain.commands import Command as DomainCommand
from backend.lan_playground.domain.commands import CommandError as DomainCommandError
from backend.lan_playground.domain.commands import CommandType as DomainCommandType
from backend.lan_playground.domain.events import Event as DomainEvent
from backend.lan_playground.domain.events import EventType as DomainEventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import AVATAR_COLORS, AVATAR_IDS, ConflictEncounterState
from backend.lan_playground.domain.state import HeroState as DomainHeroState
from backend.lan_playground.domain.state import RunState as DomainRunState
from backend.lan_playground.heroes.cards import NonLiveEffectOpError as _NonLiveEffectOpError
from backend.lan_playground.heroes.cards import compile_card_effect_ops as _compile_card_effect_ops
from backend.lan_playground.heroes.creation import ATTRIBUTE_NAMES as _HERO_ATTRIBUTE_NAMES
from backend.lan_playground.shops import content_loader as shop_content_loader
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

# Wave-6 addition (board task #21, playtest A5): derived display countdown
# for the active-effects tray, posted to the collab room 2026-07-20 --
# until_end_of_turn has effectively "0 more rounds" left (it expires before
# the round ever advances), until_end_of_round has exactly 1, and
# until_end_of_encounter isn't a round count at all (None -- client shows
# "until fight ends").
_ACTIVE_EFFECT_ROUNDS_REMAINING = {
    "until_end_of_turn": 0,
    "until_end_of_round": 1,
    "until_end_of_encounter": None,
}


@functools.lru_cache(maxsize=1)
def _core_pack():
    # Mirrors systems/heroes_wire.py's own cached loader -- this module never
    # mutates the pack, just re-serializes it for the wire, so a second cache
    # of the same immutable ContentPack is cheap and keeps this module from
    # depending on heroes_wire's private helper.
    return content_loader.load_core_pack()


@functools.lru_cache(maxsize=1)
def _core_shops():
    # Mirrors systems/shops_wire.py's own cached loader (docs/
    # INFINITE_STACKS_CONTRACTS.md §5.5): a shop room only persists
    # {archetype_id, stock} (domain.state.RoomState.shop); everything else in
    # the wire snapshot (persona/services/prices/rumor/complication) is a
    # static lookup from the same archetype dict shops_wire.py already uses.
    return shop_content_loader.load_core_shops()


def _prose_wire(prose: Any) -> dict[str, str]:
    return {"fallback": prose.fallback, "accessible": prose.accessible}


def _background_wire(background: Any) -> dict[str, Any]:
    ability = background.signature_ability
    return {
        "id": background.id,
        "name": background.name,
        "fallback": background.prose.fallback,
        "accessible": background.prose.accessible,
        "attribute_bonus": background.attribute_bonus,
        "skill_ranks": dict(background.skill_ranks),
        "starting_item_ids": list(background.starting_item_ids),
        "signature_ability": {
            "id": ability.id,
            "name": ability.name,
            "fallback": ability.prose.fallback,
            "accessible": ability.prose.accessible,
            "frequency": ability.frequency,
        },
    }


def _card_is_live_at_creation(card: Any) -> bool:
    # heroes.deck.build_starting_deck's build-time gate (docs/
    # INFINITE_STACKS_HEROES.md §7): a card referencing any effect op outside
    # this wave's LIVE set cannot be compiled into a starting deck yet. The
    # character-builder picker must only offer cards that will actually pass
    # create_hero, not surprise the player with a schema_error after they've
    # already filled in a name and rolled dice.
    try:
        _compile_card_effect_ops(card)
    except _NonLiveEffectOpError:
        return False
    return True


def _card_wire(card: Any) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "fallback": card.prose.fallback,
        "accessible": card.prose.accessible,
        "accessible_text": card.accessible_text,
        "timing": card.timing.value,
        "range": card.range,
        "legal_targets": list(card.legal_targets),
        "required_state": list(card.required_state),
        "combination_tags": list(card.combination_tags),
        "end_state": card.end_state.value,
        "source": card.source,
        "live_at_creation": _card_is_live_at_creation(card),
    }


def _item_wire(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "fallback": item.prose.fallback,
        "accessible": item.prose.accessible,
        "slot_cost": item.slot_cost,
        "tags": list(item.tags),
    }


def _ability_wire(ability: Any) -> dict[str, Any]:
    # content.schemas.Ability (stacks-carddesign, packs/core/abilities.yaml,
    # board task #20). Static authored data only -- the per-hero dynamic part
    # (charges_remaining -> "available") is merged in from HeroState.abilities
    # by _neutral_hero_creation_snapshot below, never duplicated here.
    return {
        "id": ability.id,
        "name": ability.name,
        "fallback": ability.prose.fallback,
        "accessible": ability.prose.accessible,
        "trigger": ability.trigger,
        "frequency": ability.frequency,
        "source": ability.source,
    }


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

    def content_catalog(self) -> dict[str, Any]:
        """Static reference data for the character-builder screen (§11):
        background/card/item definitions. Never viewer-filtered -- every
        field here is authored content, not run state, so there is nothing
        to hide (contrast HeroSheet/deck/inventory below, which ARE run
        state and go through project()'s per-viewer privacy filter)."""

        pack = _core_pack()
        return {
            "backgrounds": {bid: _background_wire(b) for bid, b in sorted(pack.backgrounds.items())},
            "cards": {cid: _card_wire(c) for cid, c in sorted(pack.cards.items())},
            "items": {iid: _item_wire(i) for iid, i in sorted(pack.items.items())},
            # Wave-6 addition (board task #21/#20): empty until
            # ContentPack.abilities exists (forward-compatible getattr guard,
            # same pattern used throughout this module for optional fields).
            "abilities": {aid: _ability_wire(a) for aid, a in sorted(getattr(pack, "abilities", {}).items())},
            # Wave-6 addition (board task #21, playtest F1): the fixed,
            # server-validated avatar/color lists the character-builder
            # picker offers -- create_hero rejects anything outside these.
            "token_options": {"avatar_ids": list(AVATAR_IDS), "colors": list(AVATAR_COLORS)},
        }

    def project(self, state: RunState, viewer: str | None) -> dict[str, Any]:
        base = _project(state, viewer)
        domain_state = self._domain_states.get(state.run_id)
        puzzles_by_room: dict[str, Any] = {}
        conflict_by_room: dict[str, Any] = {}
        shops_by_room: dict[str, Any] = {}
        if domain_state is not None and domain_state.map is not None:
            for room_id, room in domain_state.map.rooms.items():
                if room.puzzle is not None:
                    shared_clue_ids = domain_state.party_shared_clues.get(room_id, ())
                    puzzles_by_room[room_id] = self._neutral_puzzle_snapshot(room.puzzle, shared_clue_ids)
                if room.encounter is not None:
                    conflict_by_room[room_id] = self._neutral_conflict_snapshot(room.encounter, domain_state.heroes)
                if room.shop is not None:
                    shop_snapshot = self._neutral_shop_snapshot(room.shop)
                    if shop_snapshot is not None:
                        shops_by_room[room_id] = shop_snapshot
                wire_room = base["rooms"].get(room_id)
                if wire_room is not None:
                    wire_room["ground_items"] = dict(room.ground_items)
                    wire_room["item_claims"] = dict(room.item_claims)
                    wire_room["body_item_ids"] = {k: list(v) for k, v in room.body_item_ids.items()}
        if domain_state is not None:
            for hero_id, dh in domain_state.heroes.items():
                wire_hero = base["heroes"].get(hero_id)
                if wire_hero is not None:
                    wire_hero.update(self._neutral_hero_creation_snapshot(dh, viewer))
        base["puzzles"] = _project_puzzles(puzzles_by_room, viewer)
        base["conflict"] = conflict_by_room
        base["shops"] = shops_by_room
        # J12 fix (docs/PLAYTEST_FINDINGS_2026-07-20.md): legal_actions was
        # previously only ever sent to the client inside a CommandError
        # payload, so a fresh join/reconnect/snapshot carried no legality
        # summary at all -- the map screen's buttons (and the hint line,
        # which reads the exact same client-side field) defaulted to fully
        # locked out until the player somehow triggered an illegal-action
        # error first, which the disabled buttons made impossible. project()
        # is the one function every delivery path (REST snapshot, WS
        # reconnect_summary) already funnels through, so folding the same
        # legal_actions() summary in here means every viewer of every
        # snapshot always gets a live, correct legality view -- no separate
        # round trip, no reliance on a prior error.
        base["legal_actions"] = self.legal_actions(state, viewer)
        return base

    @staticmethod
    def _neutral_hero_creation_snapshot(domain_hero: DomainHeroState, viewer: str | None) -> dict[str, Any]:
        """Domain HeroState's wave-4 fields (pending_dice/sheet/deck/
        inventory/signature_charge, docs/INFINITE_STACKS_CONTRACTS.md §5.4)
        -> a wire-safe per-hero dict, merged into project()'s heroes_view
        entry for every hero (not just the viewer's own -- attributes,
        skills, and deck COMPOSITION are public character-sheet info, same
        as any tabletop character sheet). The one field that stays private
        is `hand` (which cards are currently drawn vs still in the shuffled
        draw pile): populated only when `viewer == domain_hero.hero_id`, the
        same "own-viewer-only key" pattern `stacks_projections.project`
        already uses for `private_clue`. The draw pile's actual order is
        never serialized to anyone, owner included -- only its count."""

        pack_abilities = getattr(_core_pack(), "abilities", {})
        abilities_wire: list[dict[str, Any]] = []
        for ability_id, a in sorted(domain_hero.abilities.items()):
            adef = pack_abilities.get(ability_id)
            available = a.trigger == "manual" and (a.charges_remaining is None or a.charges_remaining > 0)
            abilities_wire.append(
                {
                    "id": ability_id,
                    "name": adef.name if adef is not None else ability_id,
                    "fallback": adef.prose.fallback if adef is not None else ability_id,
                    "accessible": adef.prose.accessible if adef is not None else ability_id,
                    "trigger": a.trigger,
                    "frequency": a.frequency,
                    "available": available,
                }
            )
        active_effects_wire = [
            {
                "id": e.effect_id,
                "name": e.label,
                "fallback": e.label,
                "accessible": e.label,
                "rounds_remaining": _ACTIVE_EFFECT_ROUNDS_REMAINING.get(e.duration),
                "source": e.source_id,
            }
            for e in domain_hero.active_effects
        ]

        entry: dict[str, Any] = {
            "pending_dice": list(domain_hero.pending_dice) if domain_hero.pending_dice else None,
            # Wave-5 shopwire additions (docs/INFINITE_STACKS_CONTRACTS.md §5.5):
            # PUBLIC, same visibility as hp/energy -- every hero has gold from
            # join_run onward, not just after character creation completes.
            "gold": domain_hero.gold,
            "item_wear": dict(sorted(domain_hero.item_wear.items())),
            "identified_item_ids": list(domain_hero.identified_item_ids),
            "active_condition_ids": list(domain_hero.active_condition_ids),
            # Wave-6 additions (board task #21, playtest A5/E1/F1): abilities
            # + active_effects shapes confirmed with stacks-facelift/
            # stacks-carddesign in the collab room 2026-07-20. avatar_id/color
            # are set once at create_hero (systems/heroes_wire.py validates
            # against AVATAR_IDS/AVATAR_COLORS) and PUBLIC like hp/gold.
            "abilities": abilities_wire,
            "active_effects": active_effects_wire,
            "avatar_id": domain_hero.avatar_id,
            "color": domain_hero.color,
        }
        sheet = domain_hero.sheet
        if sheet is None:
            entry.update(sheet=None, deck=None, inventory=None, signature_charge=None)
            return entry

        entry["sheet"] = {
            "hero_id": sheet.hero_id,
            "name": sheet.name,
            "background_id": sheet.background_id,
            "dice": list(sheet.dice.values),
            "attributes": {name: sheet.attributes.get(name) for name in _HERO_ATTRIBUTE_NAMES},
            "skills": dict(sheet.skills),
            "starting_item_ids": list(sheet.starting_item_ids),
            "derived": {
                "max_hp": sheet.derived.max_hp,
                "defense": sheet.derived.defense,
                "initiative_modifier": sheet.derived.initiative_modifier,
                "carry_slots": sheet.derived.carry_slots,
            },
        }

        deck = domain_hero.deck
        if deck is not None:
            owned_card_ids = sorted(set(deck.deck) | set(deck.hand) | set(deck.discard) | set(deck.exhausted))
            entry["deck"] = {
                "card_ids": owned_card_ids,
                "deck_count": len(deck.deck),
                "hand_count": len(deck.hand),
                "discard": list(deck.discard),
                "exhausted": list(deck.exhausted),
            }
            if viewer is not None and viewer == domain_hero.hero_id:
                entry["hand"] = list(deck.hand)
        else:
            entry["deck"] = None

        inv = domain_hero.inventory
        entry["inventory"] = {"carry_slots": inv.carry_slots, "items": list(inv.items)} if inv is not None else None

        charge = domain_hero.signature_charge
        entry["signature_charge"] = (
            {
                "ability_id": charge.ability_id,
                "frequency": charge.frequency,
                "charges_remaining": charge.charges_remaining,
                "max_charges": charge.max_charges,
            }
            if charge is not None
            else None
        )
        return entry

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

        # `pending_reaction` (wave-5 board task #16, stacks-enemyroll): not a
        # field on ConflictEncounterState yet -- getattr keeps this inert
        # (always None) until that lands, at which point it activates with no
        # further change here. Their posted shape: {reaction_id, attacker_id,
        # defender_id, protector_ids, hit, margin, incoming_attack_total,
        # provisional_damage, action_label, source_intent_id, remaining_effects}.
        pending_reaction = getattr(encounter, "pending_reaction", None)
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
            "pending_reaction": dict(pending_reaction) if pending_reaction else None,
        }

    @staticmethod
    def _neutral_puzzle_snapshot(puzzle: Any, shared_clue_ids: tuple[str, ...] = ()) -> dict[str, Any]:
        """Domain PuzzleRoomState -> a viewer-agnostic wire-safe dict. Never
        includes `solution`/`accepted_solutions` (contract: never serialized
        in any projection) -- stacks_projections.project_puzzles() does the
        remaining per-viewer filtering of `private_clues`/`party_shared_clues`.

        `shared_clue_ids` (docs/INFINITE_STACKS_CONTRACTS.md §5.6, wave 5,
        board task #18) is `RunState.party_shared_clues[room_id]` -- clue ids
        a hero has `share_clue`'d to the party. A hero's *unshared* private
        clues (`private_clues` below) are completely unaffected."""

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
            "party_shared_clues": [
                {"clue_id": cid, "fallback": puzzle.clue_text[cid][0], "accessible": puzzle.clue_text[cid][1]}
                for cid in shared_clue_ids
            ],
        }

    @staticmethod
    def _neutral_shop_snapshot(shop_instance: Any) -> dict[str, Any] | None:
        """Domain ShopInstance ({archetype_id, stock}) -> a viewer-agnostic
        wire-safe dict (docs/INFINITE_STACKS_CONTRACTS.md §5.5). Fully
        PUBLIC (§9.6: "Prices are authoritative game data") -- only
        `listings[].stock` is dynamic; everything else is a static lookup
        from the same cached archetype dict systems/shops_wire.py uses.
        `listings` only ever includes items actually in `shop_instance.stock`
        (guaranteed + drawn rotating), never the full `rotating_pool`
        candidate set -- that would leak this shop's unseeded alternates."""

        archetype = _core_shops().get(shop_instance.archetype_id)
        if archetype is None:
            return None
        persona, rumor, complication = archetype.persona, archetype.rumor, archetype.relationship_complication
        return {
            "archetype_id": archetype.id,
            "name": archetype.name,
            "persona": {"name": persona.name, "tagline": persona.tagline, "tone": persona.tone},
            "services": sorted(service.value for service in archetype.services),
            "listings": [
                {"item_id": item_id, "buy_price": archetype.listing_for(item_id).buy_price, "stock": count}
                for item_id, count in sorted(shop_instance.stock.items())
            ],
            "sell_price_ratio": archetype.sell_price_ratio,
            "repair_cost_per_wear": archetype.repair_cost_per_wear,
            "identify_price": archetype.identify_price,
            "treatment_price": archetype.treatment_price,
            "rumor": {"text": rumor.text, "accessible_text": rumor.accessible_text},
            "relationship_complication": {
                "description": complication.description,
                "accessible_text": complication.accessible_text,
            },
        }

    def events_since(self, state: RunState, viewer: str | None, since_revision: int) -> list[Event]:
        return _events_since(state, viewer, since_revision)

    def apply(self, state: RunState, command: Command) -> ApplyResult:
        return self._apply_with_viewer(state, command, viewer=command.hero_id)

    def apply_authoritative(self, state: RunState, command: Command) -> ApplyResult:
        """Server-originated command, submitted through the exact same
        validate/handle/reduce pipeline as any player command, but with
        viewer=None -- `domain.reducer.validate()` only enforces `viewer !=
        hero_id` when a viewer is given, so this is the one caller allowed to
        act on a hero's behalf. For the §21.4 reaction-timeout auto-pass
        (stacks-enemyroll's transport-injection spec, wave-5 board task #16)
        and §21.5 disconnected-companion actions -- both land in the normal
        command/event log, so replay holds with no special-casing anywhere
        else. Still goes through the same idempotency-key/expected-revision
        checks as any command; callers must supply a fresh idempotency_key
        per attempt."""

        return self._apply_with_viewer(state, command, viewer=None)

    def _apply_with_viewer(self, state: RunState, command: Command, *, viewer: str | None) -> ApplyResult:
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
            result = domain_reducer.apply(domain_command, domain_state, rng, viewer=viewer, seq=seq)
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
            elif de.type == DomainEventType.ATTRIBUTE_DICE_ROLLED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "attribute_dice_rolled",
                        payload={"hero_id": de.actor_hero_id, "dice": de.payload["dice"]},
                    )
                )
            elif de.type == DomainEventType.HERO_CREATED:
                events.extend(self._translate_hero_created(state, de))
            elif de.type == DomainEventType.CARD_DRAWN:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "card_drawn",
                        visibility="private",
                        visible_to=de.payload["viewer_hero_id"],
                        payload={
                            "hero_id": de.actor_hero_id,
                            "count": de.payload["count"],
                            "card_ids": de.payload["card_ids"],
                        },
                    )
                )
            elif de.type == DomainEventType.CARD_PLAYED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "card_played",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "card_id": de.payload["card_id"],
                            "target_hero_id": de.payload["target_hero_id"],
                            "target_enemy_id": de.payload["target_enemy_id"],
                            "check_receipt": de.payload["check_receipt"],
                            "end_state": de.payload["end_state"],
                        },
                    )
                )
            elif de.type == DomainEventType.DECK_RESHUFFLED:
                deck = de.payload["deck"]
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "deck_reshuffled",
                        visibility="private",
                        visible_to=de.payload["viewer_hero_id"],
                        payload={
                            "hero_id": de.actor_hero_id,
                            "deck_count": len(deck["deck"]),
                            "hand_count": len(deck["hand"]),
                            "discard": list(deck["discard"]),
                            "exhausted": list(deck["exhausted"]),
                        },
                    )
                )
            elif de.type == DomainEventType.SIGNATURE_CHARGE_REFRESHED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "signature_charge_refreshed",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "boundary": de.payload["boundary"],
                            "signature_charge": de.payload["signature_charge"],
                        },
                    )
                )
            elif de.type == DomainEventType.ITEM_PICKED_UP:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "item_picked_up",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_instance_id": de.payload["item_instance_id"],
                            "item_id": de.payload["item_id"],
                            "inventory": de.payload["inventory"],
                        },
                    )
                )
            elif de.type == DomainEventType.ITEM_PICKUP_REJECTED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "item_pickup_rejected",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_instance_id": de.payload["item_instance_id"],
                            "item_id": de.payload["item_id"],
                            "reason": de.payload["reason"],
                        },
                    )
                )
            elif de.type == DomainEventType.ITEM_DROPPED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "item_dropped",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_id": de.payload["item_id"],
                            "item_instance_id": de.payload["item_instance_id"],
                            "inventory": de.payload["inventory"],
                        },
                    )
                )
            elif de.type == DomainEventType.ITEM_TRADED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "item_traded",
                        payload={
                            "item_id": de.payload["item_id"],
                            "from_hero_id": de.payload["from_hero_id"],
                            "to_hero_id": de.payload["to_hero_id"],
                            "giver_inventory": de.payload["giver_inventory"],
                            "receiver_inventory": de.payload["receiver_inventory"],
                        },
                    )
                )
            elif de.type == DomainEventType.BODY_LOOT_RECOVERED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "body_loot_recovered",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "dead_hero_id": de.payload["dead_hero_id"],
                            "item_ids": de.payload["item_ids"],
                            "inventory": de.payload["inventory"],
                        },
                    )
                )
            elif de.type == DomainEventType.CONDITION_APPLIED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "condition_applied",
                        visibility="party",
                        payload={"hero_id": de.actor_hero_id, "condition_id": de.payload["condition_id"]},
                    )
                )
            elif de.type == DomainEventType.CONDITION_REMOVED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "condition_removed",
                        visibility="party",
                        payload={"hero_id": de.actor_hero_id, "condition_id": de.payload["condition_id"]},
                    )
                )
            elif de.type == DomainEventType.SHOP_INSTANTIATED:
                events.append(self._translate_shop_instantiated(state, de))
            elif de.type == DomainEventType.SHOP_ITEM_BOUGHT:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "shop_item_bought",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_id": de.payload["item_id"],
                            "gold_delta": de.payload["gold_delta"],
                            "new_gold": de.payload["new_gold"],
                            "new_stock": de.payload["new_stock"],
                            "inventory": de.payload["inventory"],
                        },
                    )
                )
            elif de.type == DomainEventType.SHOP_ITEM_SOLD:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "shop_item_sold",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_id": de.payload["item_id"],
                            "gold_delta": de.payload["gold_delta"],
                            "new_gold": de.payload["new_gold"],
                            "new_stock": de.payload["new_stock"],
                            "inventory": de.payload["inventory"],
                            "item_wear": de.payload["item_wear"],
                        },
                    )
                )
            elif de.type == DomainEventType.SHOP_ITEM_REPAIRED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "shop_item_repaired",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_id": de.payload["item_id"],
                            "gold_delta": de.payload["gold_delta"],
                            "new_gold": de.payload["new_gold"],
                            "item_wear": de.payload["item_wear"],
                        },
                    )
                )
            elif de.type == DomainEventType.SHOP_ITEM_IDENTIFIED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "shop_item_identified",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "item_id": de.payload["item_id"],
                            "gold_delta": de.payload["gold_delta"],
                            "new_gold": de.payload["new_gold"],
                            "identified_item_ids": de.payload["identified_item_ids"],
                        },
                    )
                )
            elif de.type == DomainEventType.SHOP_CONDITION_TREATED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "shop_condition_treated",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "condition_id": de.payload["condition_id"],
                            "treatment_id": de.payload["treatment_id"],
                            "gold_delta": de.payload["gold_delta"],
                            "new_gold": de.payload["new_gold"],
                        },
                    )
                )
            elif de.type == DomainEventType.SHOP_TRANSACTION_REJECTED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "shop_transaction_rejected",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "action": de.payload["action"],
                            "reason": de.payload["reason"],
                            "item_id": de.payload["item_id"],
                        },
                    )
                )
            elif de.type == DomainEventType.CLUE_SHARED:
                events.append(
                    self._wire_event(
                        state,
                        de,
                        "clue_shared",
                        visibility="party",
                        payload={
                            "hero_id": de.actor_hero_id,
                            "clue_id": de.payload["clue_id"],
                            "fallback": de.payload["fallback"],
                            "accessible": de.payload["accessible"],
                        },
                    )
                )
        return events

    def _translate_hero_created(self, state: RunState, de: DomainEvent) -> list[Event]:
        """§11/§13 creation completion. The domain HERO_CREATED event is
        PUBLIC and bundles the full resolved sheet/deck/inventory (including
        the opening hand) as a replay-safe snapshot -- but the wire must
        never broadcast a fresh hand's contents to every viewer (contract:
        hand is owner-only). Split here: one public event carrying the
        public character-sheet facts (attributes/skills/background/derived
        stats, deck COMPOSITION + pile counts, inventory, signature charge)
        and, only if the opening hand is non-empty, one private `hand_dealt`
        event visible solely to the hero who just finished creation --
        exactly the `_translate_private_clue_revealed` split-by-visibility
        pattern already used for Mystery Chamber clues."""

        hero_id = de.actor_hero_id
        sheet = de.payload["sheet"]
        deck = de.payload["deck"]
        owned_card_ids = sorted(set(deck["deck"]) | set(deck["hand"]) | set(deck["discard"]) | set(deck["exhausted"]))
        public_event = self._wire_event(
            state,
            de,
            "hero_created",
            payload={
                "hero_id": hero_id,
                "sheet": sheet,
                "max_hp": de.payload["max_hp"],
                "defense": de.payload["defense"],
                "deck": {
                    "card_ids": owned_card_ids,
                    "deck_count": len(deck["deck"]),
                    "hand_count": len(deck["hand"]),
                    "discard": list(deck["discard"]),
                    "exhausted": list(deck["exhausted"]),
                },
                "inventory": de.payload["inventory"],
                "signature_charge": de.payload["signature_charge"],
            },
        )
        events = [public_event]
        if deck["hand"]:
            events.append(
                self._wire_event(
                    state,
                    de,
                    "hand_dealt",
                    visibility="private",
                    visible_to=hero_id,
                    payload={"hero_id": hero_id, "hand": list(deck["hand"])},
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

    def _translate_shop_instantiated(self, state: RunState, de: DomainEvent) -> Event:
        domain_state = self._domain_states[state.run_id]
        room = domain_state.map.rooms[de.payload["room_id"]] if domain_state.map else None
        shop = self._neutral_shop_snapshot(room.shop) if room is not None and room.shop is not None else None
        return self._wire_event(
            state,
            de,
            "shop_instantiated",
            payload={"room_id": de.payload["room_id"], "shop": shop},
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
