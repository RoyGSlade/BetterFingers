"""The six §14.4 called maneuvers: -4 accuracy for one additional effect.

Enemies (and bosses) define which maneuvers they resist, convert, or expose
as a weakness via `EnemyCombatant.resists` / `.weaknesses` / `.converts`
(models.py). Hero defenders have no such table (heroes don't author
resist/convert/expose data), so maneuvers against a hero always resolve at
their plain effect.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .actions import AttackResult, TurnBudget, attack
from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant, HeroCombatant
from .rng import CombatRNG
from .statuses import apply_status

Combatant = HeroCombatant | EnemyCombatant

MANEUVER_ACCURACY_PENALTY = -4  # §32 default


@dataclass
class ManeuverResult:
    attack: AttackResult
    events: list[dict] = field(default_factory=list)
    resisted: bool = False
    weakness_triggered: bool = False
    converted_to: str | None = None
    secondary_effect: str | None = None

    @property
    def hit(self) -> bool:
        return self.attack.hit


def _hooks(defender: Combatant, maneuver: str) -> tuple[bool, bool, str | None]:
    resists = getattr(defender, "resists", ())
    weaknesses = getattr(defender, "weaknesses", ())
    converts = getattr(defender, "converts", {})
    return maneuver in resists, maneuver in weaknesses, converts.get(maneuver)


def _combatant_id(c: Combatant) -> str:
    return c.hero_id if isinstance(c, HeroCombatant) else c.instance_id


def _maneuver_event(combat_round, sequencer, caused_by, attacker_id, target_id, maneuver, outcome, payload) -> dict:
    full_payload = {"maneuver": maneuver, "outcome": outcome, **payload}
    return sequencer.emit(
        combat_round=combat_round,
        caused_by=caused_by,
        type=CombatEventType.MANEUVER_RESOLVED,
        actor_id=attacker_id,
        target_id=target_id,
        visibility=Visibility.PUBLIC,
        payload=full_payload,
    )


def disarm(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
) -> ManeuverResult:
    """Reduced damage; removes a held object on a hit (heroes only carry a
    trackable `held_item` this wave)."""
    resisted, weak, converted_to = _hooks(defender, "disarm")
    result = attack(
        attacker, defender, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=budget,
        accuracy_modifier=MANEUVER_ACCURACY_PENALTY, damage_multiplier=0.5, action_label="disarm",
    )
    events = list(result.events)
    secondary = None
    if result.hit and not resisted:
        if isinstance(defender, HeroCombatant) and defender.held_item is not None:
            secondary = defender.held_item
            defender.held_item = None
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "disarm", "disarmed" if secondary else "no_item_to_remove",
                {"weakness_triggered": weak, "converted_to": converted_to, "item_removed": secondary},
            )
        )
    elif result.hit and resisted:
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "disarm", "resisted", {},
            )
        )
    return ManeuverResult(
        attack=result, events=events, resisted=resisted, weakness_triggered=weak,
        converted_to=converted_to, secondary_effect=secondary,
    )


def trip(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
) -> ManeuverResult:
    """Reduced damage; inflicts Prone on a hit."""
    resisted, weak, converted_to = _hooks(defender, "trip")
    result = attack(
        attacker, defender, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=budget,
        accuracy_modifier=MANEUVER_ACCURACY_PENALTY, damage_multiplier=0.5, action_label="trip",
    )
    events = list(result.events)
    secondary = None
    if result.hit and not resisted:
        secondary = "prone"
        events.extend(
            apply_status(
                defender, "prone", combat_round=combat_round, sequencer=sequencer, caused_by=caused_by,
                actor_id=attacker.hero_id, target_id=_combatant_id(defender),
            )
        )
    elif result.hit and resisted:
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "trip", "resisted", {},
            )
        )
    return ManeuverResult(
        attack=result, events=events, resisted=resisted, weakness_triggered=weak,
        converted_to=converted_to, secondary_effect=secondary,
    )


def drive_back(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
    push_distance: int = 2,
) -> ManeuverResult:
    """Full damage; moves the target (or changes engagement position) on a hit."""
    resisted, weak, converted_to = _hooks(defender, "drive_back")
    result = attack(
        attacker, defender, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=budget,
        accuracy_modifier=MANEUVER_ACCURACY_PENALTY, action_label="drive_back",
    )
    events = list(result.events)
    secondary = None
    if result.hit and not resisted:
        distance = push_distance * (2 if weak else 1)
        from_position = defender.position
        defender.position += distance
        secondary = f"pushed_{distance}"
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "drive_back", "pushed",
                {"from_position": from_position, "to_position": defender.position, "weakness_triggered": weak},
            )
        )
    elif result.hit and resisted:
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "drive_back", "resisted", {},
            )
        )
    return ManeuverResult(
        attack=result, events=events, resisted=resisted, weakness_triggered=weak,
        converted_to=converted_to, secondary_effect=secondary,
    )


def break_object(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
    component: str = "body",
) -> ManeuverResult:
    """Damages armor, a shield, an enemy-defined body part, or an
    environmental object -- `component` names the enemy-defined target
    (content-authored; this wave just carries the label through)."""
    resisted, weak, converted_to = _hooks(defender, "break")
    result = attack(
        attacker, defender, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=budget,
        accuracy_modifier=MANEUVER_ACCURACY_PENALTY,
        damage_multiplier=(2.0 if weak else 1.0),
        action_label="break",
    )
    events = list(result.events)
    if result.hit:
        outcome = "resisted" if resisted else "broken"
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "break", outcome, {"component": component, "weakness_triggered": weak},
            )
        )
    return ManeuverResult(
        attack=result, events=events, resisted=resisted, weakness_triggered=weak,
        converted_to=converted_to, secondary_effect=component if result.hit else None,
    )


def crushing_blow(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
) -> ManeuverResult:
    """Adds one weapon die of damage; exposes the attacker on failure."""
    resisted, weak, converted_to = _hooks(defender, "crushing_blow")
    result = attack(
        attacker, defender, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=budget,
        accuracy_modifier=MANEUVER_ACCURACY_PENALTY,
        bonus_damage_dice=0 if resisted else 1,
        action_label="crushing_blow",
    )
    events = list(result.events)
    secondary = None
    if not result.hit:
        attacker.exposed_until_next_turn = True
        secondary = "exposed"
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "crushing_blow", "attacker_exposed", {},
            )
        )
    elif resisted:
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "crushing_blow", "resisted", {},
            )
        )
    return ManeuverResult(
        attack=result, events=events, resisted=resisted, weakness_triggered=weak,
        converted_to=converted_to, secondary_effect=secondary,
    )


RATTLE_CONDITIONS = ("frightened", "provoked", "distracted")
TRACKED_RATTLE_STATUSES = ("frightened",)  # the others are scene tags, not §16.4-tracked statuses


def rattle(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
    condition: str = "frightened",
    target_can_understand: bool = True,
) -> ManeuverResult:
    """Replaces physical damage with Frightened, Provoked, or Distracted,
    only when the target can understand or read the action."""
    if condition not in RATTLE_CONDITIONS:
        raise ValueError(f"rattle condition must be one of {RATTLE_CONDITIONS}, got {condition!r}")
    resisted, weak, converted_to = _hooks(defender, "rattle")

    result = attack(
        attacker, defender, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=budget,
        accuracy_modifier=MANEUVER_ACCURACY_PENALTY, damage_multiplier=0.0, action_label="rattle",
    )
    events = list(result.events)
    secondary = None
    if result.hit and not target_can_understand:
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "rattle", "target_cannot_understand", {"condition": condition},
            )
        )
    elif result.hit and resisted:
        events.append(
            _maneuver_event(
                combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                "rattle", "resisted", {"condition": condition},
            )
        )
    elif result.hit:
        secondary = condition
        if condition in TRACKED_RATTLE_STATUSES:
            events.extend(
                apply_status(
                    defender, condition, combat_round=combat_round, sequencer=sequencer, caused_by=caused_by,
                    actor_id=attacker.hero_id, target_id=_combatant_id(defender),
                )
            )
        else:
            events.append(
                _maneuver_event(
                    combat_round, sequencer, caused_by, attacker.hero_id, _combatant_id(defender),
                    "rattle", "applied", {"condition": condition, "weakness_triggered": weak},
                )
            )
    return ManeuverResult(
        attack=result, events=events, resisted=resisted, weakness_triggered=weak,
        converted_to=converted_to, secondary_effect=secondary,
    )
