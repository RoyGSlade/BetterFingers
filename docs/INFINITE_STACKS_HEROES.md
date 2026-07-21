# Heroes package -- wave 3 (board task #11)

Standalone character-creation + deck/inventory package:
`backend/lan_playground/heroes/**`. Same discipline as `combat/` (wave 2):
zero I/O, zero imports of `domain`/`systems`/`stacks_*.py`, randomness only
through an injected structural Protocol. Domain/reducer wiring is wave 4 --
nothing in this package is called from `stacks_engine.py`, `domain/`, or
`systems/` yet.

## 1. Module map

```text
heroes/
  rng.py          HeroesRNG Protocol (roll_d20/randint/choice/shuffled) --
                   structurally identical to combat.rng.CombatRNG, satisfied
                   unmodified by the real domain.rng.StacksRNG.
  creation.py      §11.1: DiceRoll, Attributes, DerivedStats, HeroSheet.
  backgrounds.py   §11.3: apply a background from pack data; SignatureCharge.
  deck.py          §13.2: DeckState, build_starting_deck, draw, play_card,
                   safe_rest_reshuffle, recover_exhausted_card.
  inventory.py     §13.6: InventoryState, single-owner pickup, drop/trade,
                   BodyLoot.
  cards.py         §5/§13.3: compile a card's effects to LIVE ops; the
                   build-time gate `deck.build_starting_deck` uses.
```

## 2. Content pack data is passed in, never loaded

No module in `heroes/` imports `content.schemas` or `content.loader` at
runtime (only `TYPE_CHECKING`-gated hints for editor/type-checker support).
Every function that needs a background/card/item definition takes it as a
parameter -- callers load the real pack once
(`content.loader.load_core_pack()`) and pass `pack.backgrounds[id]` /
`pack.cards[id]` / `pack.items[id]` in. This mirrors `combat/intents.py`,
which builds its own combatants from a passed-in `content.schemas.Enemy`
without importing the schema module for anything but a type hint.

Structural "Like" Protocols (`backgrounds.BackgroundLike`, `cards.CardLike`,
`inventory.ItemLike`, ...) document the exact fields each module reads, so a
caller can pass either a real `content.schemas.*` dataclass instance or an
equivalent duck-typed stand-in (e.g. in a unit test) with no adapter code.

## 3. Character creation (§11.1, `creation.py` + `backgrounds.py`)

```text
dice = creation.roll_attribute_dice(rng)                 # 4 visible d4s, one call
attrs = creation.assign_attributes(dice, {                # player assigns one die per attribute
    "force": dice.values[0], "finesse": dice.values[1],
    "insight": dice.values[2], "presence": dice.values[3],
})
attrs = backgrounds.apply_background_bonus(attrs, background)  # +1, capped at 5
derived = creation.compute_derived_stats(attrs)
# derived.max_hp = 8 + 2*Force
# derived.defense = 10 + Finesse + equipment_defense_bonus (default 0 at creation)
# derived.initiative_modifier = Finesse   (the modifier combat's d20 roll adds to)
# derived.carry_slots = 4 + Force
```

`roll_attribute_dice` is deterministic under a seeded `HeroesRNG`: the same
seed always produces the same four values in the same order, which is what
the visible-dice UI replays.

`ATTRIBUTE_NAMES`/`SKILL_NAMES` in `creation.py` are literal-duplicated from
`combat.models` (not imported) so `HeroSheet`'s field names line up for a
straight field-copy into `combat.models.HeroCombatant`/`Attributes` in wave 4,
without heroes depending on combat at runtime.

## 4. Backgrounds (§11.3, `backgrounds.py`)

- `apply_background_bonus(attributes, background)` -- +1 to
  `background.attribute_bonus`, capped at 5.
- `starting_skill_ranks(background)` / `starting_item_ids(background)` --
  thin pass-throughs, kept as named functions so callers don't reach into
  pack-object internals directly.
- `initial_signature_charge(background)` -- signature abilities are modeled
  as a `SignatureCharge(ability_id, frequency, charges_remaining, max_charges)`.
  Every §11.3 frequency (`once_per_floor`/`once_per_room`/`once_per_fight`)
  currently grants exactly 1 charge. `.spend()` raises
  `SignatureChargeError` at zero; `.refreshed()` is the hook wave-4 domain
  calls at the boundary the frequency names (new floor/room/fight) -- this
  package does not know when those boundaries occur.
- `bonus_carry_slots(background)` -- the Traveling Charlatan's "concealed
  item slot" (§11.3) has no field on `content.schemas.Background` yet
  (editing that schema is out of this wave's claimed files), so it is named
  explicitly in `CONCEALED_ITEM_SLOT_BONUS` rather than invented as a new
  generic schema field.

## 5. Deck lifecycle (§13.2, `deck.py`)

`build_starting_deck` enforces the exact §13.2 composition -- 4 background
cards, 2 selected general cards, 1 persona signature card, up to 2
equipment-granted cards -- and is the **build-time gate**: it calls
`cards.compile_deck_card_pool` on every card id before constructing the
`DeckState`. A card whose effects reference any op outside this wave's LIVE
set (see §7 below) raises `cards.NonLiveEffectOpError` immediately, before
the deck exists. This is why `content/packs/core/cards.yaml`'s
general/background/persona cards were authored (or converted) to be LIVE-only
this wave -- see the note at the top of that file.

```text
state = deck.build_starting_deck(hero_id, background_card_ids=[...4...],
                                  general_card_ids=[...2...],
                                  persona_card_id=..., card_lookup=pack.cards, rng=rng)
state = deck.draw(state, 4)
state = deck.play_card(state, card_id, pack.cards)   # -> discard or exhaust, per card.end_state
state = deck.safe_rest_reshuffle(state, rng)          # discard -> deck; exhausted untouched
state = deck.recover_exhausted_card(state, card_id)   # the "stronger recovery rule" -- explicit, opt-in
deck.reaction_cards_in_hand(state, pack.cards)        # cards flagged timing=reaction, playable off-turn
```

`draw` does not auto-reshuffle on an empty deck (§13.2 only reshuffles on a
safe rest); it simply returns fewer cards than requested if the deck runs dry.

## 6. Inventory (§13.6, `inventory.py`)

- `InventoryState(hero_id, carry_slots, items)` -- slot-based, not weight
  arithmetic. `used_slots`/`free_slots` sum `item_lookup[id].slot_cost`.
- `attempt_pickup(claims, item_instance_id=..., item_id=..., hero_id=..., inventory=..., item_lookup=...)`
  -- single-owner pickup. `claims` is caller-owned mutable state, one entry
  per contested *ground item instance* (not per item definition -- two heroes
  each finding their own copy of the same item is not a conflict; two heroes
  reaching for the same room object is). Returns `PickupResult(accepted, reason)`;
  `reason` is populated (`"already_claimed"` / `"insufficient_carry_slots"`)
  exactly when `accepted` is `False`, never silently dropped.
- `drop_item` / `trade_item` -- direct slot-checked transfers. Room adjacency
  for trades is the caller's job.
- `hero_died_with_items(inventory) -> BodyLoot` -- the §13.6 data hook: "a
  dead hero's carried items remain with the body." Wave-4 domain calls this
  at permanent death and persists the result onto the body object; this
  package never auto-transfers or destroys items.

## 7. Card -> effect-op compilation (`cards.py`)

```text
LIVE_EFFECT_OPS = {"reveal_room", "grant_check", "spend_energy", "emit_fact"}
```

Duplicated (not imported) from `content.schemas.KNOWN_OPS`'s current LIVE
set -- verified by
`tests/test_stacks_content.py::test_known_ops_marked_live_have_a_real_systems_handler`
to be exactly these four. If a future wave flips more ops to LIVE, this is
the one constant that needs to grow.

`compile_card_effect_ops(card)` walks every effect the card can produce (its
`base_effects`, plus all four §12.3 outcome branches if it has a `check`) and
raises `NonLiveEffectOpError` on the first non-LIVE op. `compile_deck_card_pool`
runs that over a whole set of card ids -- the function `deck.build_starting_deck`
calls as its gate.

## 8. Wave-4 bridge notes (for stacks-conflict / domain wiring)

- `creation.HeroSheet` field names (`attributes.force/finesse/insight/presence`,
  `skills: dict[str, int]`, `max_hp` via `.derived.max_hp`) are chosen to
  field-copy directly into `combat.models.HeroCombatant`/`Attributes`.
- `deck.DeckState` and `inventory.InventoryState` are plain immutable
  dataclasses (tuples, not lists, for the sequence fields) -- safe to embed
  directly in a future `HeroState` without a translation layer.
- `backgrounds.SignatureCharge.refreshed()` and
  `inventory.hero_died_with_items()` are explicit hooks with no caller yet in
  this wave; wave 4 domain owns *when* to call them (floor/room/fight
  boundaries, permanent death respectively).
- Nothing in this package spends real Exploration Energy or mutates real HP --
  `spend_energy`/`grant_check` effect ops only ever compile to the wire IR
  (`{"op": ..., "args": ...}`); dispatching them through `systems/effects.py`
  against a real `RunState` is wave-4's job, same as it already is for
  Mystery Chamber puzzle content (§5.1 of the contracts doc).
