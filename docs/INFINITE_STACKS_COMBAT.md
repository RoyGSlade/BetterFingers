# Infinite Stacks — Combat Contracts (wave 2, updated wave 4)

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
    equipment_defense_bonus, equipment_accuracy_bonus, equipment_damage_bonus,
    weapon, hp, life_state (ALIVE|DOWNED|STABLE|DEAD),
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

## 5. Attack math (§14.3) and the equipment-modifier input contract (§13, task #14)

```text
attack_total = d20 (or adv/disadv-resolved) + attribute_score + skill_rank
             + weapon.accuracy_bonus + attacker.equipment_accuracy_bonus
             + accuracy_modifier (e.g. -4 for a maneuver)
hit = attack_total >= defender.defense   # defense = 10 + Finesse + equipment_defense_bonus
damage = weapon_die_roll(s) + weapon.damage_bonus + attacker.equipment_damage_bonus
       + extra_damage_bonus  (only rolled/applied on a hit)
```

`actions.attack()` also accepts `damage_multiplier` and `bonus_damage_dice`,
reused by `maneuvers.py` (e.g. Disarm/Trip halve damage, Crushing Blow adds
one extra weapon die) so the roll math lives in exactly one place. A
maneuver/attack that resolves to **zero** damage (Rattle "replaces physical
damage") never calls `lifecycle.apply_damage` and never emits
`damage_applied` -- no HP or death-check side effects from a hit that
deals no damage.

**Equipment-modifier inputs (published early to the room, task #14).**
`weapon.accuracy_bonus`/`weapon.damage_bonus`/`weapon.die_faces` (existing,
wave 2) and two wave-4 additions on `HeroCombatant` --
`equipment_accuracy_bonus: int = 0` and `equipment_damage_bonus: int = 0`
(non-weapon item/accessory bonuses, e.g. a ring or gloves, parallel to the
existing `equipment_defense_bonus`) -- are the only equipment inputs
`attack()` reads. All four are **verified concrete values**, never raw wire
numbers: `systems/combat_wire.hero_combatant_from_state(hero, *,
attributes=None, skills=None, weapon=None, equipment_defense_bonus=0,
equipment_accuracy_bonus=0, equipment_damage_bonus=0)` accepts an
already-built `Weapon`/already-verified ints as keyword arguments (every one
optional, defaulting to today's flat zero-modifier/default-weapon
behavior). Whoever resolves a source id to a concrete value (the domain lane
that owns hero-sheet/inventory) calls this constructor with the resolved
values; this function itself never accepts or resolves a raw item/source id
(per the wave-3 director ruling -- no unverified numeric modifier ever comes
from the wire).

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

## 7. Reactions (§14.5) and the mid-resolution interrupt window (task #14)

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

`dodge()`/`block()`/`protect()`/`counter()`/`escape()`/`set_prepared_trigger()`/
`execute_prepared_trigger()` are unchanged, standalone, and still directly
callable (that's how `escape` and `prepared_trigger` work, and how a caller
can offer a reaction outside an attack entirely). What's new this wave is
that `actions.attack()` can invoke Block/Dodge/Protect/Counter genuinely
*mid-resolution* instead of forcing a caller to reconstruct
`incoming_attack_total`/`incoming_damage`/`incoming_attack_margin` after the
fact from caller-supplied context:

```python
result = actions.attack(
    attacker, defender, attribute=..., skill=..., rng=..., combat_round=...,
    sequencer=..., caused_by=..., budget=...,
    reaction_hook=my_policy,          # Callable[[ReactionWindow], ReactionOutcome | None]
    protectors=[ally_a, ally_b],      # optional: heroes who could Protect `defender`
)
```

`attack()` rolls the attack (and, on a hit, the provisional damage) exactly
as before, emits `attack_resolved`, and — if `defender` is a `HeroCombatant`
with a reaction available (or any `protectors` entry does) — calls
`reaction_hook(window)` before touching HP. `ReactionWindow` carries
`attacker`, `defender`, `protectors`, `hit`, `margin`, `incoming_attack_total`
(the attacker's resolved total, exactly what `dodge()` expects to oppose),
`provisional_damage` (0 on a miss), plus the shared `rng`/`combat_round`/
`sequencer`/`caused_by`. The hook is free to call `reactions.dodge/block/
protect/counter` directly (their signatures are unchanged) and packages the
result as a `ReactionOutcome(events, hit, damage, damage_target=None)`:
`hit=False` negates the attack (Dodge), a lower `damage` reduces it (Block),
`damage_target=<protector>` redirects it (Protect); `counter()`'s own nested
`attack()` call already applies its own damage internally, so a Counter
outcome just leaves the original attack's `hit`/`damage` as-is and folds the
counter-attack's events in. Returning `None` means no reaction was taken —
resolution proceeds exactly as if no hook had been passed, and the
reaction is **not** consumed. The hook decides policy; `attack()` only
guarantees the window opens at the right moment and that whatever the hook
returns is what actually lands. This mirrors `combat/encounter.py`'s
existing "combat doesn't decide tactics" split.

Coverage is at the pure-package level (`tests/test_stacks_combat.py`'s
`test_interrupt_window_*`): Block reduces damage and may flag item Wear,
Dodge negates a hit and repositions on success (and does nothing extra on
failure), Protect redirects HP loss to the protector, Counter fires only on
`margin <= -5` and lands its own attack on the original attacker, and the
window is never offered to a non-hero (enemy) defender or when no reaction
is available. `systems/combat.py::handle_combat_reaction` remains the
caller-supplied-context command path for Escape/Prepared Trigger (unrelated
to the pending-reaction window below).

### 7.1 Enemy attacks and the live pending-reaction window (wave 5, task #16)

Enemy attack-type intents (the `damage` op) now resolve through a real
§14.3 to-hit roll and open this same interrupt window live, in the domain.
Two new pure-package primitives in `combat/actions.py` make this possible
without a synchronous callback (the existing `reaction_hook` above assumes
an in-process decision, which a real network-connected player can't give):

- `resolve_enemy_attack(attacker: EnemyCombatant, defender, *, damage_amount,
  rng, ..., reaction_hook=None)` — §14.3 to-hit for an enemy: `d20 (+
  adv/disadv) + attacker.accuracy_bonus` vs `defender.defense`. Enemies
  carry no weapon dice (§12): damage on a hit is the flat, content-authored
  `amount` from the intent's `damage` op, unchanged from the wave-2
  contract. `reaction_hook=None` (default) resolves immediately, exactly
  like `attack()` with no hook — this is what pure-package/scripted callers
  (`tests/test_stacks_combat.py`'s `_run_simple_fight`) still use, so no
  window is offered there and behaviour stays deterministic.
- `reaction_hook=actions.PENDING_REACTION` (a sentinel) — opens the window
  when eligible and returns a `PendingAttack` (roll + provisional damage
  already resolved and baked into its `events`, replay-safe; damage not
  yet applied) instead of resolving. `resolve_pending_attack(pending,
  outcome)` finishes it later, given a `ReactionOutcome` or `None` to
  decline — this is what `systems/combat.py` uses.

`EnemyCombatant.accuracy_bonus` (default 0) is combat-package data, not a
content schema change (director ruling 2026-07-19, note-20's offered escape
hatch): `intents.build_enemy_combatant` assigns a per-`threat_tier` default
(minion +2 / standard +4 / specialist +6 / elite +8, `ACCURACY_BONUS_BY_TIER`
in `combat/intents.py`) — a documented default in the §32 spirit, same
pattern as `systems/combat.py`'s `_DEFAULT_BLOCK_AMOUNT`.

`combat/intents.py::resolve_intent_effects` gained `rng` (required only
when an op is `damage`) and `reaction_hook`/`protectors` (both optional, so
`apply_condition`/`move_target`/`emit_fact`-only intents are unaffected).
When a `damage` op pends, it returns `IntentEffectsResult(events, pending,
remaining_effects)` where `remaining_effects` is whatever ops came after
the paused one in that same intent (empty for every intent in the core
pack today, since none author more than one effect) — resumed later by
calling the function again with a synthetic `EnemyIntentDef` wrapping just
those ops, `id` set to the original intent's id so damage-source tagging
is unaffected.

**Domain wiring (`systems/combat.py`, `ConflictEncounterState.pending_reaction`).**
`_cascade_enemy_turns` (the auto-resolver for consecutive enemy turns)
stops the instant an intent's `damage` op opens an eligible window —
`current_actor_id` stays pinned to the attacking enemy (its turn isn't
over); every other combat command already rejects with "not your turn", and
`_active_encounter_room` now rejects up front with a clearer "encounter has
a pending reaction awaiting resolution" message. Other enemies later in the
same cascade simply wait, like a mid-swing pause.

The new `resolve_reaction` command (`{reaction_id, reaction:
"dodge"|"block"|"protect"|"counter"|"pass", new_position?, item_id?}` — no
numeric bonuses, same no-raw-wire-numbers rule as everywhere else) answers
it: the sender must be `pending.defender_id` (dodge/block/counter/pass) or
listed in `pending.protector_ids` (protect/pass); first valid command wins.
Block's amount, Dodge's opposed roll, and Counter's `permitted` (margin
`<= -5` is the sole, server-computed gate — no card/item system exists yet
to gate it further) are all server-derived exactly like every other combat
default in this file. `pass` — an explicit decline, a transport-layer
decision-timer expiry, or a disconnected hero's companion policy (§21.5) —
all resolve identically: full provisional damage lands and, per §14.5 ("the
reaction is not consumed" when nothing is taken), `reaction_available`
stays true. **There is no separate timeout/companion code path in the
reducer** — those are just other senders of the same `resolve_reaction`
command; the wall-clock decision timer lives entirely in the transport
layer (stacks-heroui's `stacks_api.py`), never in domain state.

**No deadlock, but genuinely no auto-resolve either (director ruling
2026-07-19).** `RunState.round_complete()` returns `False` while *any*
active encounter has a non-null `pending_reaction`, in addition to its
existing `submitted_turn` check — an early design that force-defaulted a
stale pending reaction at the round boundary was rejected specifically
because, in solo play (the most common case), the enemy cascade often runs
in the exact command that already satisfies every other `round_complete()`
condition; auto-resolving there would mean the defending player never sees
a prompt. The correct guarantee is the reverse of what "no deadlock" first
suggests: the window **genuinely stays open** — including across what
would otherwise be a world-round boundary — until a `resolve_reaction`
command answers it, and the reducer makes no promise that one ever will.
**A headless/scripted consumer that opens a window and never sends
`resolve_reaction` stalls by design** — no different from ordinary
exploration, where nothing auto-passes a silent player either. Real
deployments must always have something answering: a live player, or the
transport layer's timer/companion policy per §21.4/§21.5, both ordinary
senders of the same command.

Tests: `tests/test_stacks_combat.py::test_interrupt_window_*` (unchanged,
pure-package, synchronous hooks) plus `resolve_enemy_attack`/pending-attack
coverage; `tests/test_stacks_conflict.py`'s dedicated pending-reaction
section (block/dodge/protect/counter/pass, the round_complete() guard for a
solo last-submitter, and the headless-stalls-by-design case) drives the
real command/reducer path end to end.

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
documented default in the spirit of §32, revisit through playtesting).
`statuses.py` itself still never touches HP directly, keeping it independent
of the Downed/death-check state machine — but as of wave 4 the tick is no
longer unapplied. `combat/encounter.py::tick_status_damage(encounter, *,
caused_by)` walks every living hero (id-sorted) then every living enemy
(id-sorted, deterministic order for replay) and, for each `bleeding`/
`burning` entry in `.statuses`, calls `lifecycle.apply_damage(...,
source="bleeding_tick"|"burning_tick")` — the same single HP seam every
other damage source uses, so "damage while Downed adds a death-check
failure" (§16.2) applies to a status tick exactly like an attack
(`tests/test_stacks_combat.py::test_tick_on_downed_hero_adds_death_check_failure`).
`combat/encounter.py::advance_round` calls `tick_status_damage` at the
combat-round boundary (right after the new round's `combat_round_started`
event, before the Downed-hero death-check cadence), so both
`systems/combat.py::build_round_advance_combat_events` and
`systems/turns.py::build_round_advance_events` (which calls it whenever a
world round advances) pick the tick up automatically — no changes were
needed in either wiring file beyond this doc, since `advance_round` was
already the single round-boundary seam both call through.

## 12. What's out of scope this wave

Reducer/transport wiring (turning combat events into `RunState` mutations
and wire projections) is wave-3 scope per the director's wave-2 board note.
Injuries (§16.5) and sicknesses (§16.6) are separate systems this package
doesn't implement — `lifecycle.revive` flags `injury_risk` in its payload
when reviving without proper supplies but does not create an Injury object.
Cards/items beyond a flat `Weapon`/`held_item` (§13) aren't modeled; called
maneuvers and reactions accept plain numeric/boolean parameters (e.g.
`counter`'s `permitted: bool`) rather than resolving card legality
themselves. Wave 5 (task #16) closed the two items previously listed here
(live `reaction_hook` wiring, enemy to-hit rolls) — see §7.1. Still out of
scope: called maneuvers/reactions still don't resolve card/item legality
(counter's `permitted` stays a server-computed `margin <= -5` gate, not a
card check), and Escape/Prepared Trigger still go through the older
caller-supplied-context `combat_reaction` command rather than the pending-
reaction window (they aren't attack-interrupt reactions).
