"""Enemy intent telegraphs (§14.6), data-driven from
content/packs/core/enemies.yaml.

This is the one module in the combat package allowed to import
backend.lan_playground.content -- read-only, for loading authored enemy/
intent data. It never imports domain/systems, and it builds its own
`EnemyCombatant`/`EnemyIntentDef` rather than depending on
content.schemas.Enemy directly, so the rest of the combat package (and its
tests) stay decoupled from the content lane's authoring schema.

Selection is deterministic: intents whose trigger is already true beat the
`"always"` fallback, first-authored-order wins among ties. Nothing here
consumes randomness -- "players should make tactical decisions based on
intent rather than memorize hidden scripts" (§14.6) requires that the
telegraphed intent be the intent that actually executes.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import actions
from .events import CombatEventType, EventSequencer, Visibility
from .lifecycle import apply_damage
from .models import EnemyCombatant, HeroCombatant
from .rng import CombatRNG
from .statuses import apply_status

# §14.3 to-hit accuracy for enemy attack-type intents, keyed by threat_tier.
# No accuracy field is authored in content/packs/core/enemies.yaml yet (wave-5
# director ruling 2026-07-19: combat-package data rather than a content
# schema change) -- a documented default in the §32 spirit, same pattern as
# systems/combat.py's `_DEFAULT_BLOCK_AMOUNT`. Revisit through playtesting.
ACCURACY_BONUS_BY_TIER = {
    "minion": 2,
    "standard": 4,
    "specialist": 6,
    "elite": 8,
}
DEFAULT_ACCURACY_BONUS = 4  # unrecognised/future tiers fall back to "standard"


@dataclass(frozen=True)
class EnemyIntentDef:
    id: str
    trigger: str
    effects: tuple[dict, ...]     # [{"op": str, "args": dict}, ...] per content Effect.compile()
    counterplay: str
    telegraph_text: str
    accessible_text: str


@dataclass
class IntentEffectsResult:
    """Return shape for `resolve_intent_effects`. `pending`/`remaining_effects`
    are set only when a `damage` op opened a live reaction window
    (`reaction_hook=actions.PENDING_REACTION`) -- processing of this intent's
    remaining effect ops (if any come after the one that paused) stops at
    that point; the caller resumes them once the window resolves."""

    events: list[dict]
    pending: "actions.PendingAttack | None" = None
    remaining_effects: tuple[dict, ...] = ()


def build_enemy_combatant(
    enemy_def,
    *,
    instance_id: str,
    initiative_bonus: int = 0,
    converts: dict[str, str] | None = None,
    accuracy_bonus: int | None = None,
) -> tuple[EnemyCombatant, tuple[EnemyIntentDef, ...]]:
    """Build a combat-owned `EnemyCombatant` + its intent list from a real
    `content.schemas.Enemy` (e.g. `content.loader.load_core_pack().enemies["goblin_bruiser"]`).

    `converts` has no equivalent in the content schema yet (§14.4 "resist,
    convert, or expose" -- only resist/weakness are authored today) so it is
    supplied by the caller (test/encounter setup), defaulting to none.
    `accuracy_bonus` defaults to the tier-keyed §14.3 table above; pass an
    explicit value to override (test setup only today).
    """
    combatant = EnemyCombatant(
        instance_id=instance_id,
        def_id=enemy_def.id,
        name=enemy_def.name,
        family=enemy_def.family,
        max_hp=enemy_def.hp,
        defense=enemy_def.defense,
        threat_cost=enemy_def.threat_cost,
        threat_tier=enemy_def.threat_tier.value,
        initiative_bonus=initiative_bonus,
        accuracy_bonus=(
            accuracy_bonus
            if accuracy_bonus is not None
            else ACCURACY_BONUS_BY_TIER.get(enemy_def.threat_tier.value, DEFAULT_ACCURACY_BONUS)
        ),
        resists=tuple(enemy_def.resists),
        weaknesses=tuple(enemy_def.weaknesses),
        converts=dict(converts or {}),
    )
    intents = tuple(
        EnemyIntentDef(
            id=i.id,
            trigger=i.trigger,
            effects=tuple(e.compile() for e in i.effects),
            counterplay=i.counterplay,
            telegraph_text=i.prose.fallback,
            accessible_text=i.prose.accessible,
        )
        for i in enemy_def.intents
    )
    return combatant, intents


def select_intent(intents: tuple[EnemyIntentDef, ...], facts: frozenset[str]) -> EnemyIntentDef:
    conditional_matches = [i for i in intents if i.trigger != "always" and i.trigger in facts]
    if conditional_matches:
        return conditional_matches[0]
    always_matches = [i for i in intents if i.trigger == "always"]
    if always_matches:
        return always_matches[0]
    raise ValueError("no enemy intent matches the current facts and there is no 'always' fallback")


def telegraph_intent(
    enemy: EnemyCombatant,
    intent: EnemyIntentDef,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> list[dict]:
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.INTENT_TELEGRAPHED,
            actor_id=enemy.instance_id,
            visibility=Visibility.PUBLIC,
            payload={
                "intent_id": intent.id,
                "telegraph_text": intent.telegraph_text,
                "accessible_text": intent.accessible_text,
                "counterplay": intent.counterplay,
            },
        )
    ]


def resolve_intent_effects(
    intent: EnemyIntentDef,
    enemy: EnemyCombatant,
    target: HeroCombatant | None,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    rng: CombatRNG | None = None,
    reaction_hook=None,
    protectors: tuple[HeroCombatant, ...] = (),
) -> IntentEffectsResult:
    """Resolves an intent's compiled effect ops in order. A `damage` op is an
    attack-type effect (§14.3/task #16): it rolls to-hit through
    `actions.resolve_enemy_attack` -- requires `rng` -- and opens the same
    §14.5 reaction window a hero attack does. If `reaction_hook is
    actions.PENDING_REACTION` and the window is eligible, resolution stops
    at that op: the returned `IntentEffectsResult.pending` carries the
    unresolved window and `.remaining_effects` carries any ops after it in
    this same intent (empty tuple if none) -- resume them later by calling
    this function again with a synthetic `EnemyIntentDef` whose `effects`
    is `remaining_effects` (`id` should stay the original intent's id, so
    damage-source tagging is unaffected). All other ops (`apply_condition`,
    `move_target`, `emit_fact`) stay unconditional/op-based, no roll."""
    events: list[dict] = []
    for i, op_spec in enumerate(intent.effects):
        op = op_spec["op"]
        args = op_spec.get("args", {})
        if op == "damage":
            if target is None:
                raise ValueError(f"intent {intent.id!r} op 'damage' requires a target")
            if rng is None:
                raise ValueError(f"intent {intent.id!r} op 'damage' requires rng for the §14.3 to-hit roll")
            result = actions.resolve_enemy_attack(
                enemy, target, damage_amount=args["amount"], rng=rng, combat_round=combat_round,
                sequencer=sequencer, caused_by=caused_by, action_label=intent.id,
                reaction_hook=reaction_hook, protectors=protectors,
            )
            if isinstance(result, actions.PendingAttack):
                return IntentEffectsResult(
                    events=events + result.events, pending=result, remaining_effects=intent.effects[i + 1:],
                )
            events.extend(result.events)
        elif op == "apply_condition":
            if target is None:
                raise ValueError(f"intent {intent.id!r} op 'apply_condition' requires a target")
            events.extend(
                apply_status(
                    target, args["condition_id"], combat_round=combat_round, sequencer=sequencer,
                    caused_by=caused_by, actor_id=enemy.instance_id, target_id=target.hero_id,
                )
            )
        elif op == "move_target":
            if target is None:
                raise ValueError(f"intent {intent.id!r} op 'move_target' requires a target")
            from_position = target.position
            target.position += args["distance"]
            events.append(
                sequencer.emit(
                    combat_round=combat_round, caused_by=caused_by, type=CombatEventType.MOVED,
                    actor_id=enemy.instance_id, target_id=target.hero_id, visibility=Visibility.PUBLIC,
                    payload={"from_position": from_position, "to_position": target.position, "reason": intent.id},
                )
            )
        elif op == "emit_fact":
            events.append(
                sequencer.emit(
                    combat_round=combat_round, caused_by=caused_by, type=CombatEventType.ENEMY_ACTION_RESOLVED,
                    actor_id=enemy.instance_id, target_id=(target.hero_id if target else None),
                    visibility=Visibility.PUBLIC, payload={"op": "emit_fact", "fact_id": args["fact_id"]},
                )
            )
        else:
            raise ValueError(f"combat.intents cannot resolve unhandled effect op {op!r} (intent {intent.id!r})")
    return IntentEffectsResult(events=events)
