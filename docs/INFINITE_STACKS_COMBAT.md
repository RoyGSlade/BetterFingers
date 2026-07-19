# Infinite Stacks — Combat Contracts (wave 2)

> Authoritative schema for `backend/lan_playground/combat/**`. Standalone,
> pure, deterministic, rng-injected: zero I/O, zero LLM calls, and no import
> of `backend.lan_playground.domain` / `backend.lan_playground.systems`
> (that wiring is explicitly wave-3 scope per the director's wave-2 board
> note). `combat/intents.py` is the one exception -- it does a read-only
> import of `backend.lan_playground.content` to build enemy/intent data from
> `content/packs/core/enemies.yaml`.
>
> Source of truth for rules: `infinite_stacks.md` §14 (combat), §15 (threat
> budget), §16 (health/downed/death), §2 and §32 (locked defaults).
>
> Companion doc: `docs/INFINITE_STACKS_CONTRACTS.md` (engine/content/transport,
> wave 1 + wave-2 effects lane). This doc only covers combat.

## 1. Why a separate event envelope

`docs/INFINITE_STACKS_CONTRACTS.md` §3 scopes its `Event` envelope to a
`RunState` (`run_id` / `world_round`). Combat isn't wired into `RunState`
this wave, so `combat/events.py` defines its own envelope with the same
shape and the same guarantees, scoped to an encounter instead of a run:

```python
{
    "event_id": str,        # "cevt_<combat_round>_<seq>"
    "encounter_id": str,
    "combat_round": int,
    "caused_by": str,       # command/action id, or a policy-supplied label in tests
    "actor_id": str | None, # hero_id or enemy instance_id
    "target_id": str | None,
    "type": str,            # CombatEventType value
    "visibility": "public" | "party" | "private",
    "payload": dict,
}
```

When wave-3 wires combat into the reducer, the adapter is expected to carry
`encounter_id` / `combat_round` through unchanged into the run's event log
(deriving `run_id` / `world_round` from context) -- no field renaming
required on the combat side.

`CombatEventType` (see `combat/events.py` for the full enum): initiative and
round bookkeeping (`initiative_rolled`, `combat_round_started`,
`joiner_entered`), turn structure (`turn_started`, `moved`,
`quick_interaction_used`), resolution (`attack_resolved`, `damage_applied`,
`maneuver_resolved`, `reaction_resolved`), enemies (`intent_telegraphed`,
`enemy_action_resolved`, `enemy_defeated`), statuses (`status_applied`,
`status_escalated`, `status_consolidated`, `status_treated`), the death
state machine (`hero_downed`, `death_check_resolved`, `hero_stabilized`,
`hero_revived`, `hero_died`), threat (`threat_budget_calculated`,
`reinforcements_scheduled`, `reinforcements_arrived`,
`barricade_established`), and `encounter_ended`.

These are **mechanical fact events**, one layer below a UI projection. The
wave-2 UI lane's `state.combat` fixture shape
(`initiative_order` / `enemies` / `legal_actions` / `last_check_receipt`) is
a *projected view* derived by folding a combat event log into state --
exactly how `domain`'s `project()` derives a `ProjectedView` from
`RunState` in wave 1. That projection function is wave-3 scope; it did not
exist as of this doc.

## 2. RNG contract

`combat/rng.py` defines a `typing.Protocol` (`CombatRNG`) rather than
importing `domain.rng.StacksRNG`:

```python
class CombatRNG(Protocol):
    def roll_d20(self) -> int: ...
    def randint(self, a: int, b: int) -> int: ...
    def choice(self, seq: Sequence[T]) -> T: ...
    def shuffled(self, seq: Sequence[T]) -> list[T]: ...
```

`domain.rng.StacksRNG` already satisfies this structurally (verified by
`tests/test_stacks_combat.py::test_same_seed_produces_identical_event_sequence`,
which drives a full encounter through the real `StacksRNG`). Wave-3 wiring
can pass the run's `StacksRNG` straight into combat functions with zero
adapter code. Weapon/damage dice other than d20 (d4/d6/d8/rare d10) go
through the generic `randint(1, n)` rather than dedicated `roll_dN` methods
-- `combat/rng.py::roll_die(rng, faces)` is a thin helper for that.

## 3. Combatant models (`combat/models.py`)

Deliberately **not** `content.schemas.Enemy` / a persona/hero record: this
package needs fields those schemas don't carry (an attributes block for
enemies, per-enemy `converts` for called maneuvers) and shouldn't couple to
the content lane's authoring format. `combat/intents.py::build_enemy_combatant`
is the one bridge from a real `content.schemas.Enemy` to this shape.

```python
Attributes(force, finesse, insight, presence)   # §11.1, ints
Weapon(die_faces, damage_bonus, accuracy_bonus)  # die_faces in {4,6,8,10}

HeroCombatant:
    hero_id, name, attributes, max_hp, skills: dict[str,int],
    equipment_defense_bonus, weapon, hp, life_state (ALIVE|DOWNED|STABLE|DEAD),
    stabilization_successes, death_failures, reaction_available,
    position, held_item, prepared_trigger, exposed_until_next_turn,
    statuses: dict[status_id, StatusInstance]
    # .defense == 10 + finesse + equipment_defense_bonus  (§11.1)
    # .initiative_bonus == finesse

EnemyCombatant:
    instance_id, def_id, name, family, max_hp, defense, threat_cost,
    threat_tier, initiative_bonus, hp, resists, weaknesses,
    converts: dict[maneuver_name, effect_id], alive, position, statuses
```

`StatusInstance(status_id, applied_round, rounds_remaining, escalated)`.
`rounds_remaining=None` means "lasts until treated/source removed" -- true
for every status in the initial nine (§16.4 gives each a treatment rule,
not a fixed tick-down duration).

## 4. Module map

| Module | §  | Owns |
|---|---|---|
| `initiative.py` | §14.1 | `d20+Finesse` roll, deterministic tie rules, combat-round/world-round sync, joiner integration at the next cycle |
| `actions.py` | §14.2-14.3 | `TurnBudget` (movement/quick interaction/main action, one each), `attack()` |
| `maneuvers.py` | §14.4 | The six called maneuvers at -4 accuracy, resist/weakness/convert hooks |
| `reactions.py` | §14.5 | Dodge/Block/Protect/Counter/Escape/Prepared Trigger, one reaction per round |
| `intents.py` | §14.6 | Enemy intent telegraph + effect resolution, data-driven from `content/packs/core/enemies.yaml` |
| `threat.py` | §15 | Threat budget formula, reinforcement scheduling/delay, barricade |
| `lifecycle.py` | §16.1-16.3 | HP mutation, Downed/Stable/Dead state machine, death checks, revival |
| `statuses.py` | §16.4 | The nine statuses, apply/escalate/consolidate/treat |
| `events.py` | -- | Event envelope + `EventSequencer` |
| `models.py` | -- | Shared dataclasses |
| `rng.py` | -- | `CombatRNG` protocol |
| `encounter.py` | -- | Round-progression/reinforcement-arrival/victory-defeat bookkeeping. Does **not** decide tactics -- that's a policy/command concern (wave 3 for real players; `tests/test_stacks_combat.py`'s scripted loop for this wave) |

Every module is well under the ~500-line cap (largest is `maneuvers.py` at
~345 lines).

## 5. Attack math (§14.3)

```text
attack_total = d20 (or adv/disadv-resolved) + attribute_score + skill_rank
             + weapon.accuracy_bonus + accuracy_modifier (e.g. -4 for a maneuver)
hit = attack_total >= defender.defense   # defense = 10 + Finesse + equipment
damage = weapon_die_roll(s) + weapon.damage_bonus + extra_damage_bonus  (only rolled/applied on a hit)
```

`actions.attack()` also accepts `damage_multiplier` and `bonus_damage_dice`,
reused by `maneuvers.py` (e.g. Disarm/Trip halve damage, Crushing Blow adds
one extra weapon die) so the roll math lives in exactly one place. A
maneuver/attack that resolves to **zero** damage (Rattle "replaces physical
damage") never calls `lifecycle.apply_damage` and never emits
`damage_applied` -- no HP or death-check side effects from a hit that
deals no damage.

## 6. Called maneuvers and the resist/weakness/convert hooks (§14.4)

Each maneuver is `attack()` at `accuracy_modifier=-4` plus a maneuver-specific
secondary effect, gated by `EnemyCombatant.resists` / `.weaknesses` /
`.converts` (all keyed by maneuver name: `disarm`, `trip`, `drive_back`,
`break`, `crushing_blow`, `rattle`):

- **resisted** (`maneuver in enemy.resists`): the attack still rolls/hits/
  deals its (possibly reduced) damage, but the secondary effect (Prone,
  forced movement, disarm, etc.) is suppressed. An event still records the
  attempt with `outcome="resisted"`.
- **weakness** (`maneuver in enemy.weaknesses`): the secondary effect is
  amplified (Drive Back's push distance doubles, Break's damage multiplier
  doubles) and `weakness_triggered=True` is on the result/event.
- **convert** (`enemy.converts.get(maneuver)`): carried through on the
  result as `converted_to` for the caller to act on. `content.schemas.Enemy`
  has no authored `converts` field yet (only `resists`/`weaknesses` are
  authored today) -- `converts` is supplied by whoever builds the
  `EnemyCombatant` (test setup this wave; likely a future content field).

Content packs today only author `resists` / `weaknesses` (see
`content/packs/core/enemies.yaml` — none of the three current enemies use
them yet, but the `Enemy` dataclass already carries the tuples).

## 7. Reactions (§14.5)

One reaction per round: `HeroCombatant.reaction_available`, cleared by
`reactions.use_reaction()` and refreshed by `reactions.refresh_reaction()`.
`combat/encounter.py::advance_round` refreshes every living hero's reaction
at each round boundary (a documented simplification of "until the hero's
next turn" for this wave's scripted-turn orchestrator; a future
turn-by-turn command handler can call `refresh_reaction` at the exact start
of that hero's turn instead).

`Counter` is gated by `reactions.can_counter(margin, permitted)`: the
incoming attack must have missed by 5+ (`margin <= -5`) **and** a card/item
must grant permission (`permitted=True`, caller-supplied — combat doesn't
know about cards/items).

## 8. Enemy intents (§14.6)

`intents.build_enemy_combatant(enemy_def, instance_id=...)` turns a real
`content.schemas.Enemy` into an `EnemyCombatant` + tuple of
`EnemyIntentDef(id, trigger, effects, counterplay, telegraph_text,
accessible_text)`. `effects` is the compiled `{"op": ..., "args": ...}` IR
from `content.schemas.Effect.compile()` — the same vocabulary
`docs/INFINITE_STACKS_CONTRACTS.md` §5 describes. `intents.py` resolves
`damage`, `apply_condition`, `move_target`, and `emit_fact` (the ops the
core pack's three enemies actually use); any other op raises rather than
silently no-opping.

Selection (`intents.select_intent`) is **deterministic, not RNG-driven**:
a conditional intent whose `trigger` fact is already true beats the
`"always"` fallback; first-authored-order wins among ties. This is required
by §14.6 itself ("players should make tactical decisions based on intent
rather than memorize hidden scripts") — the telegraphed intent must be the
intent that executes.

## 9. Threat budget and reinforcements (§15)

```text
budget.total = 2 * total_living_heroes + floor_danger + corruption_modifier + objective_modifier
```

Always the **total living party**, never just the heroes physically present
(§2/§15.1) — `threat.calculate_threat_budget` takes `total_living_heroes`
as an explicit argument so the caller can't accidentally pass "heroes in
the room."

`threat.schedule_reinforcements` greedily affords enemies from a candidate
list against remaining budget and returns a `ReinforcementWave` with a
delayed `arrival_combat_round`, rather than dropping the full roster into
the room immediately — this is the mechanism behind §15.2's "at least one
retreat, barricade, hide, or delay route." `threat.delay_reinforcements`
lets a barricade/hide/delay action push a wave's arrival further out (e.g.
buying time for a rescuer to arrive at the next initiative cycle, §14.1 /
§15.3). `combat/encounter.py::arrive_due_reinforcements` folds an arrived
wave's enemies into the encounter and rolls their initiative via
`initiative.integrate_joiners`.

## 10. HP / Downed / Stable / Dead (§16.1-16.3)

```text
Healthy/Wounded -> Downed at 0 HP -> Stable (3 death-check successes, or an
                                             ally's correct aid directly)
                                  -> Revived (aid/item/ability/safe recovery)
Downed -> Dead after 3 death-check failures or an explicit fatal event
```

`lifecycle.apply_damage` is the **single** HP-mutation entry point every
other module (attacks, maneuvers, enemy intents, burning/bleeding ticks)
calls through, so "damage while Downed adds one death-check failure"
(§16.2) is enforced in exactly one place — including for a hero who is
`STABLE` (still unconscious at 0 HP; taking damage knocks them back to
`DOWNED` and adds a failure, since nothing in §16 suggests Stable is immune
to further harm). `lifecycle.death_check` is `d20 + Force vs 10`, called
once per round for each still-`DOWNED` hero (`encounter.run_downed_turn_checks`,
matching "at the beginning of a Downed hero's world turn").
`extra_failures` covers "a clearly tagged severe trap or execution may add
two failures" — the caller supplies the count; this module never invents
narrative severity.

## 11. Statuses (§16.4)

All nine (`bleeding`, `burning`, `frightened`, `confused`, `silenced`,
`sickened`, `exhausted`, `marked`, `prone`) are defined in
`statuses.STATUS_DEFINITIONS` with exactly one `primary_effect` and one
`treatment` string each. `MAX_TRACKED_STATUSES = 2`: `apply_status`
re-applying an already-active status **escalates** it (refreshes/extends,
tags `escalated=True`); applying a third distinct status while already at
the cap **consolidates** — the status applied longest ago
(`min(applied_round, status_id)`, fully deterministic) is replaced, and a
`status_consolidated` event names both the replaced and applied status.
`statuses.status_damage_amount(status_id)` exposes the `bleeding`/`burning`
per-tick damage figure (`1`, matching no explicit number in the spec — a
documented default in the spirit of §32, revisit through playtesting) for
whoever ticks end-of-round/post-action effects; `statuses.py` itself never
touches HP, keeping it independent of the Downed/death-check state machine.

## 12. What's out of scope this wave

Reducer/transport wiring (turning combat events into `RunState` mutations
and wire projections) is wave-3 scope per the director's wave-2 board note.
Injuries (§16.5) and sicknesses (§16.6) are separate systems this package
doesn't implement — `lifecycle.revive` flags `injury_risk` in its payload
when reviving without proper supplies but does not create an Injury object.
Cards/items beyond a flat `Weapon`/`held_item` (§13) aren't modeled; called
maneuvers and reactions accept plain numeric/boolean parameters (e.g.
`counter`'s `permitted: bool`) rather than resolving card legality
themselves.
