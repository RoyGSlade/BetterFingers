# Shops package -- wave 4 (board task #15)

Standalone shop economy + run-summary package: `backend/lan_playground/shops/**`.
Same discipline as `combat/` (wave 2) and `heroes/` (wave 3): zero I/O, zero
imports of `domain`/`systems`/`stacks_*.py`/`heroes`/`combat`/`content`,
randomness only through an injected structural Protocol. Domain/reducer
wiring is wave 5 -- nothing in this package is called from `stacks_engine.py`,
`domain/`, or `systems/` yet.

## 1. Module map

```text
shops/
  rng.py          ShopsRNG Protocol (roll_d20/randint/choice/shuffled) --
                   structurally identical to combat.rng.CombatRNG /
                   heroes.rng.HeroesRNG, satisfied unmodified by the real
                   domain.rng.StacksRNG.
  models.py        §9.6: MerchantPersona, Rumor, RelationshipComplication,
                   ShopService, InventoryListing, ShopArchetype (authored
                   shape), ShopInstance (seeded runtime shape), ShopperState
                   (wallet + held items + Wear, this package's own pure
                   economy state -- not heroes.inventory.InventoryState).
  seeding.py        instantiate_shop(archetype, rng) -> ShopInstance:
                   guaranteed inventory always seeds in; rotating_pool draws
                   rotating_slots items deterministically from the RNG.
  economy.py        Pure pricing: buy_price, sell_price, repair_price,
                   identify_price, treatment_price, total_wealth. The single
                   place ECON-001 (see §3 below) is proven.
  services.py        Pure transactions: attempt_buy/sell/repair/identify/treat,
                   each `(archetype, instance, shopper[, item_id]) ->
                   (TransactionResult, new_instance, new_shopper)`.
  run_summary.py     RUN-001 groundwork: fold_run_summary(event_log) -> stats
                   dict. See §4 below -- this is not shop-specific, it just
                   lives in this package per board task #15's scope.
```

## 2. Content pack data is passed in, never loaded

No module in `shops/` (`models.py`/`economy.py`/`services.py`/`seeding.py`/
`run_summary.py`) imports `content.schemas` or `content.loader` at runtime --
this mirrors `heroes/`. `ShopArchetype` (the authored shape) is constructed
by `shops/content_loader.py`'s `load_shops()`, not by anything in the pure
economy modules reading YAML.

**Layering, wave-5-corrected (board task #18):** wave 4 shipped
`load_shops()`/`check_shop_item_references()` on the *content* side
(`content/loader.py`/`content/validators.py`), because `content/schemas.py`
was off-limits to this lane that wave -- that produced a documented backwards
dependency edge, `content.loader -> shops.models`, the reverse of `heroes`'
"content never imports the package" story. Wave 5 moved the loading/
validation *entry point* into `shops/content_loader.py` instead of moving
`ShopArchetype`/`InventoryListing`/etc. into `content/schemas.py`: nothing
else on the content side ever consumed those dataclasses, so relocating the
entry point removes the edge with zero change to the ECON-001-proven
`economy.py`/`services.py`/`seeding.py` modules (1000-seed property test
untouched) and no Enum/dataclass duplication across packages. `content/
loader.py` and `content/validators.py` no longer import anything from
`shops/`; `shops/content_loader.py` is the only place the dependency now
runs, and it runs shops -> content (the same forward direction
`systems/heroes_wire.py` already uses for its own pack lookups), never the
reverse. Wave-5 domain/reducer wiring (`systems/shops_wire.py`) is the
runtime caller: it loads shop archetypes via `shops.content_loader.
load_core_shops()`, same as `heroes_wire.py`'s own `_core_pack()` cache.

`shops.content_loader.check_shop_item_references(shops, pack)` is the
CI-style cross-reference check (§23.2 "unknown ... item ... references"):
every `item_id` a shop's `guaranteed_inventory`/`rotating_pool` lists must
exist in `pack.items`, or it's an `unknown_reference` `Finding`.
`validate_core_pack_and_shops()` is the one-call entry point that validates
both together and raises `ValidationError` with every finding from either
half.

## 3. ECON-001: no shop-action sequence increases total wealth

infinite_stacks.md §6.2/§17.1 requires the shop economy to be loop-proof: no
combination of buying, selling, repairing, identifying, or treating can ever
net a player more wealth than they started with. This package proves it
structurally, not just by testing it (`tests/test_stacks_shops.py`'s
`test_no_action_sequence_increases_total_wealth` still runs it 1000 times as
a property test, seeds 1-1000):

- `economy.sell_price(archetype, item_id)` is derived **only** from that
  listing's `buy_price` and the archetype's `sell_price_ratio`, and is
  clamped `min(floor(buy_price * ratio), buy_price - 1)` so it is *strictly*
  below `buy_price` for every `buy_price >= 1`, regardless of how close to
  `1.0` a content author sets `sell_price_ratio` (also enforced at the data
  layer: `ShopArchetype.__post_init__` rejects `sell_price_ratio >= 1.0`).
- Wear and identification state never change `sell_price` -- repairing or
  identifying an item costs gold but never increases what it resells for.
- `economy.total_wealth(shopper, archetype) = shopper.gold + sum(sell_price(item) *
  count for held items this shop stocks)`.
- Per `services.py` transaction: `attempt_buy` strictly *decreases* wealth
  (pays `buy_price`, gains an asset worth only `sell_price < buy_price`);
  `attempt_sell` is wealth-*neutral* (gold gained exactly equals the
  liquidation value removed); `attempt_repair`/`attempt_identify`/
  `attempt_treat` are pure costs (wealth non-increasing, never a refund).

`services.py` never applies a transaction that would violate this -- there is
no code path where a service call increases `shopper.gold` without removing
an equal-or-greater amount of held-item liquidation value (sell), or that
grants gold at all for repair/identify/treat.

## 4. Run-summary fold (RUN-001 groundwork)

`run_summary.fold_run_summary(event_log)` is a pure fold over a **domain**
event log -- plain dicts shaped like `domain.events.Event.to_dict()`
(docs/INFINITE_STACKS_CONTRACTS.md §3: `{event_id, run_id, world_round,
caused_by, type, visibility, actor_hero_id, room_id, payload}`), never a
domain `Event` object and never anything from `systems/`. It returns:

```python
{
    "rooms_resolved": int,
    "fragments_recovered": int,
    "encounters_won": int,
    "encounters_lost": int,
    "heroes_downed": int,
    "heroes_dead": int,
    "items_gained": int,
    "items_lost": int,
    "puzzle_stats": {
        "instantiated": int, "solved": int, "rejected": int,
        "forced": int, "hints_used": int,
    },
}
```

Event types read (string values, per `domain/events.py`'s `EventType` and
docs/INFINITE_STACKS_CONTRACTS.md §3/§5.1/§5.3):

| stat | event `type` | notes |
|---|---|---|
| `rooms_resolved` | `room_breached` | counted once per distinct `room_id` (envelope field, falls back to `payload["to_room_id"]`) |
| `puzzle_stats.instantiated` | `mystery_puzzle_instantiated` | |
| `puzzle_stats.solved` | `puzzle_solution_accepted` | |
| `puzzle_stats.rejected` | `puzzle_solution_rejected` | |
| `puzzle_stats.forced` | `puzzle_force_progress` | |
| `puzzle_stats.hints_used` | `puzzle_hint_revealed` | |
| `encounters_won` / `encounters_lost` | `conflict_encounter_ended` | reads `payload["outcome"]` (`"victory"` / `"party_wiped"`, §5.3) |
| `heroes_downed` | `conflict_encounter_started` / `conflict_turn_resolved` / `conflict_encounter_ended` | derived: counts transitions *into* `life_state == "downed"` across `payload["hero_updates"]`, deduplicated per hero (no dedicated "hero downed" event exists yet) |
| `heroes_dead` | same three conflict event types | reads `payload["newly_dead_hero_ids"]`, deduplicated defensively |

Any `type` not in this table (including `hero_joined`, `hero_moved`,
`energy_spent`, `turn_submitted`, `world_round_advanced`, `check_resolved`,
`room_revealed_by_effect`, `effect_energy_spent`, `fact_emitted`,
`joined_conflict_room`, and any future/unknown type) is silently skipped --
`fold_run_summary` never raises on an event it doesn't recognize.
`tests/test_stacks_shops.py::test_run_summary_fold_tolerates_unknown_event_types`
locks this in.

**Known groundwork gaps, not bugs:** `fragments_recovered` is always `0` --
infinite_stacks.md's book/fragment system is Phase 8, out of scope through
at least wave 5, and no domain event carries fragment-recovery data yet.
`items_gained`/`items_lost` are always `0` for the same reason: item
pickup/drop/trade has no domain `EventType` yet as of this writing (the
herowire lane, board task #13, is wiring it into `domain`/`systems`
concurrently with this package this wave). Both are one-line additions to
`run_summary._HANDLERS` once their event types exist -- this module's
handler-table design is deliberately built so that lands without touching
`fold_run_summary` itself or any caller.

## 5. What's out of scope this wave

No domain/reducer wiring: nothing in `shops/` is reachable from a live run
yet. `ShopperState` is this package's own pure economy state (gold + held
item counts + Wear + identified-set) -- it is **not**
`heroes.inventory.InventoryState` and wave 5 domain wiring is expected to
bridge the two (a hero's actual carried items stay owned by
`heroes.inventory`; a shop transaction's *economic* effect is what this
package computes). `attempt_treat` charges gold but has no hero-condition
model of its own -- wave 5 supplies which condition is being treated and
applies its cure effect via whatever mechanism `heroes`/`combat` already use
for conditions.
