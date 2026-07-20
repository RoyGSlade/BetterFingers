# Infinite Stacks — Engine Contracts (v1)

> Authoritative schema for wave 1 (golden-floor slice). Owned by the **engine** lane
> (`backend/lan_playground/domain/`, `backend/lan_playground/systems/`). Content and
> transport lanes build against this document. Corrections after this point are posted
> to the room as `urgent`.
>
> Source of truth for rules: `infinite_stacks.md` §7, §8, §12, §22.1-22.2, §22.4-22.5,
> §27 (Phases 1-2), §28, §32, §33.

## 1. ID conventions

All IDs are lowercase strings. Stable, globally unique within their type, never reused.

| ID | Format | Example |
|---|---|---|
| `run_id` | `run_<8 hex>` | `run_4f8a2c31` |
| `hero_id` | `hero_<slug>` (slug chosen at join, unique within a run) | `hero_bram` |
| `room_id` | `room_<x>_<y>` (map coordinates, deterministic) | `room_2_-1` |
| `encounter_id` | `enc_<8 hex>` | `enc_9d0b1e22` |
| `event_id` | monotonic `evt_<world_round>_<seq>` | `evt_3_0007` |
| `command_id` | caller-supplied UUID4 string (doubles as dedupe key alongside `idempotency_key`) | |
| `content_id` (packs) | `<pack>:<category>:<name>`, e.g. `core:room_subtype:hostile_auction` | |

Room coordinates are integers; `room_id` is derived, never randomly generated, so any
party member and the reducer agree on identity without a round trip.

## 2. Command envelope

```python
@dataclass(frozen=True)
class Command:
    command_id: str            # caller UUID4, for logging/dedupe
    idempotency_key: str        # stable key; replaying the same key is a no-op, returns prior result
    run_id: str
    hero_id: str | None         # None only for system/GM-less commands (none exist yet in wave 1)
    encounter_id: str | None    # set when the command targets an active encounter
    expected_revision: int      # RunState.revision the client believes is current
    type: str                   # e.g. "move", "breach", "observe", "inspect", "pass", "check"
    payload: dict                # command-specific fields, validated per `type`
```

`validate(command, state, viewer) -> accepted | CommandError`

- `CommandError` carries `code` (`stale_revision | illegal_action | not_your_turn |
  unknown_target | schema_error`) and, on `stale_revision` / `illegal_action`, a
  `legal_actions` summary for the viewer's current state (per §22.5 — never a bare
  server error).
- `expected_revision != state.revision` is **not automatically fatal**: if the command
  is idempotent-safe (same `idempotency_key` already applied) it returns the prior
  result; otherwise it is rejected with `stale_revision` and the legal-action summary.

Wave-1 command types (§33 slice): `join_run`, `move`, `breach`, `observe`, `inspect`,
`pass`, `check` (generic d20 check invocation used by exploration/interaction rules).

Wave-2 additions (board task #5, Mystery Chamber puzzle rooms -- §9.1, §10):
`inspect_object` `{object_id: str}`, `submit_solution` `{solution: list[str]}`,
`request_hint` `{}`. All three require the acting hero to be in a room with an
active `RoomState.puzzle` (`illegal_action` otherwise). `submit_solution`/
`request_hint` also reject with `illegal_action` once the puzzle is `solved`
or `forced`.

## 3. Event envelope

```python
@dataclass(frozen=True)
class Event:
    event_id: str
    run_id: str
    world_round: int
    caused_by: str               # command_id that produced this event
    actor_hero_id: str | None
    room_id: str | None
    type: str                    # e.g. "hero_moved", "room_breached", "energy_spent", ...
                                   # full vocabulary: EventType in domain/events.py (wave-1
                                   # exploration/checks + wave-2 puzzle/effect-op additions, §5 below)
    visibility: Visibility        # PUBLIC | PRIVATE(hero_id) | PARTY (all current-run heroes)
    payload: dict
```

- Events are the only source of state mutation. `reduce(state, event) -> new_state` is
  pure and total for every event type the reducer emits: it never mutates the `state`
  argument, always returns a distinct `RunState`. Callers (transport reconnect
  snapshots, replay, tests) may keep a reference to a prior state across `apply()`
  calls without it changing underneath them.
- `handle(command, state, rng) -> tuple[Event, ...]` is the only place allowed to draw
  from `rng`. Events store the *results* of randomness (e.g. rolled family, d20 result),
  never a re-rollable seed fragment, so replay never touches the RNG stream twice for
  the same event.
- Replay contract: given the run's initial seed and the ordered event log, re-running
  `reduce` over all events from `RunState.initial(seed)` MUST produce a state whose
  `state_hash()` (stable hash over the dataclass tree, excluding non-authoritative
  fields like cached projections) matches the live state's hash at every world-round
  boundary.

## 4. Visibility / projection rules

`project(state, viewer) -> ProjectedView`

- `viewer` is `hero_id` or `None` for a spectator/system view (no private data).
- A hero's own `HeroState` (Energy, HP, position, inventory placeholders) is always
  visible to that hero.
- Other heroes' positions, discovered-room status, and public room content are visible
  to everyone in the run (shared map, per §21.3).
- `RoomState.secrets` (private clue assignments, undiscovered hazards, anything gated
  by `SecretField.viewer_scope`) is stripped unless `viewer` is in the authorized scope.
- `PRIVATE(hero_id)` events project only into that hero's view; `PARTY` events project
  into every current hero's view; `PUBLIC` events project into all viewers including
  spectators.
- Content packs never author raw prose into public projections — they author facts;
  presentation (LLM prose) is looked up by content hash and is not part of replay state
  (§20, §22.1).

## 5. Content-effect interface -- LIVE as of wave 2 (board task #5, stacks-effects)

All four wave-1-authored ops now have real, wired handlers in
`backend/lan_playground/systems/effects.py` (`dispatch()`), reachable through the
reducer via `systems/puzzles.py`'s Mystery Chamber success/failure consequences.
`content/schemas.py`'s `KNOWN_OPS` marks all four `OpStatus.LIVE`.

```yaml
- op: reveal_room          # exposes a connector's target room (marks discovered=True;
  args: {connector: north} # no-op if no room exists at that coordinate at all -- it does
                            # NOT require an existing DOOR connector, since it's meant to
                            # unlock exposure beyond ordinary §7.1 connectivity)
- op: grant_check           # resolves a real d20 check via systems/checks.py (flat
  args: {attribute: insight, skill: read, dc: 11}  # attribute_score=0/skill_rank=0 --
                            # no hero-sheet attributes exist yet, Phase 3 is still out of
                            # scope; attribute/skill args are recorded on the event for a
                            # future hero-sheet lookup, not applied as bonuses yet)
- op: spend_energy          # deducts from the acting hero, clamped at 0 (never negative)
  args: {amount: 1}
- op: emit_fact             # appends fact_id to RunState.facts (deduplicated), the seam
  args: {fact_id: string}   # the future book/prose pipeline (§18.4) reads from
```

Each op emits its own domain `EventType`: `reveal_room` -> `ROOM_REVEALED_BY_EFFECT`,
`spend_energy` -> `EFFECT_ENERGY_SPENT`, `grant_check` -> `CHECK_RESOLVED` (reuses the
existing check-resolution event/applier), `emit_fact` -> `FACT_EMITTED`. `dispatch()`
silently skips any op without a registered handler (defense in depth -- content
validators are what actually guarantee only a known op reaches it), so it stays
forward-compatible as later ops graduate from `PLANNED` to `LIVE` without a flag day.

Cards/items/conditions/enemies are not wired into gameplay yet (combat/inventory are
out of scope this wave too -- see §10 below), so in practice `dispatch()` is only
exercised by `systems/puzzles.py` today. Any future caller reuses it unchanged.

### 5.1 Mystery Chamber puzzle rooms (§9.1, §10)

On breach into a `mystery_chamber` room (d8 == 1), `exploration.handle_breach` calls
`systems/puzzles.py`'s `build_instantiate_events`, which instantiates a real, seeded
`content.puzzles.ordering_sequence` instance (the only puzzle template with a generator
this wave; all `mystery_chamber` subtypes get the same template for now) and stores it
on `RoomState.puzzle` (`domain/state.py`'s `PuzzleRoomState`).

New domain event types: `MYSTERY_PUZZLE_INSTANTIATED` (PUBLIC -- objects only, no clue
text, no solution), `PRIVATE_CLUE_REVEALED` (PRIVATE, payload
`{"viewer_hero_id": hero_id, "clues": [...]}`), `PUZZLE_OBJECT_INSPECTED` (PRIVATE),
`PUZZLE_HINT_REVEALED` (PARTY), `PUZZLE_SOLUTION_ACCEPTED` / `PUZZLE_SOLUTION_REJECTED`
(PUBLIC), `PUZZLE_FORCE_PROGRESS` (PUBLIC, `reason: "hints_exhausted"|"attempts_exhausted"`).

Asymmetric distributed clues (§10.3 #8): the four §10.2 objects are anchor / key /
contradiction / red_herring. Anchor, contradiction, and red_herring are single shared
facts -- any hero physically in the room who inspects one sees the same text. Key is a
*pool* of clue fragments (the ordering chain's individual `immediately_before` facts):
the breaching hero claims the first fragment immediately as part of breaching (exactly
one `private_clue_assigned` wire event, preserving the wave-1 wire contract
tests/test_stacks_api.py hard-codes); every other hero claims their own
never-claimed fragment the first time *they* `inspect_object` the key object while
standing in the room. No single hero's view ever contains the full key chain once more
than one hero has claimed a fragment.

Solution checking is validator-owned (§10.1, §20.2): `submit_solution` only ever
compares the caller's answer against `instance.accepted_solutions` -- never re-solved,
never seen by the LLM. Hints escalate through `instance.hint_steps` (3 steps); calling
`request_hint` a fourth time is how the party accepts §10.4's defined consequence and
force-progresses. Every wrong `submit_solution` -- and hint exhaustion -- dispatches the
instance's `failure_events` through `systems/effects.py` (fail-forward, never
"nothing happens"); a correct submission dispatches `success_events` the same way.
Exhausting `attempt_limit` wrong guesses force-progresses identically to hint exhaustion.

### 5.2 Wire projection shape (`StacksEngineAdapter.project()`)

`project(state, viewer)`'s returned dict gains a top-level `"puzzles"` key:
`{room_id: {instance_id, template_id, difficulty, objects: [{id, role, fallback,
accessible}], items: [{item_id, fallback, accessible}], solved, forced, attempts_used,
attempt_limit, hints_revealed: [{fallback, accessible}], your_private_clues: [{clue_id,
fallback, accessible}]}}`.

`hints_revealed` and `your_private_clues` are both viewer-filtered by
`stacks_projections.project_puzzles()`: empty for a spectator (`viewer is None`);
`your_private_clues` contains only clues assigned to that specific hero_id, never any
other hero's fragment. `solution` and `accepted_solutions` are never present in this
dict at all (stripped before `stacks_engine.py` ever builds the neutral snapshot) --
they exist only in internal domain state (`PuzzleRoomState`), never in any projection.

`items` (wave-3 addition, director-directed 2026-07-19 17:30) is the orderable-item
catalog `submit_solution`'s `{solution: [item_id, ...]}` refers to -- PUBLIC (visible
even to a spectator, unlike `hints_revealed`/`your_private_clues`), since without item
ids on the wire no client can ever construct a valid solve (clue prose only names items
by fiction). Always emitted in a fixed lexicographic-by-`item_id` order that is
independent of the shuffled `solution`/`accepted_solutions` order -- the item list
itself leaks nothing about the answer. `content.puzzles.ordering_sequence` is the only
puzzle template this wave; `systems/puzzles.py` builds `items` from `instance.solution`
(the set of ids, not the order) at instantiation time, same coupling the module
docstring already documents.

Known open item (per director, 2026-07-19 16:30): stacks-ui's wave-2 fixtures
(`tests/fixtures/stacks_ui/puzzle_mystery_chamber.json`) were authored before this
section landed and use a different field vocabulary (`puzzle.objects/private_clue/
shared_notes/hints`). This section is the authoritative engine projection shape; the
fixture/selector reconciliation is a follow-up pass at wave close, not a reason to
reshape this projection.

### 5.3 Conflict-room wire projection (wave 3, stacks-conflict)

`project(state, viewer)` gains a top-level `"conflict"` key, parallel to `"puzzles"`:

```
{room_id: {
    encounter_id, status: "active"|"victory"|"party_wiped", combat_round,
    current_actor_id: combatant_id | null,
    initiative_order: [combatant_id, ...],      # already alive-filtered ("active order")
    heroes: {hero_id: {hp, max_hp, life_state, position, reaction_available}},
    enemies: {instance_id: {name, hp, max_hp, alive, position}},
    threat_budget: {total_living_heroes, floor_danger, corruption_modifier,
                    objective_modifier, total},
}}
```

No hidden combat state leaks: no `resists`/`weaknesses`/`converts` tables, no
un-telegraphed enemy intent, no `skills`/`attributes`/`statuses` detail beyond what a
player needs. Enemy intent and §12.5 check receipts are not persistent snapshot
fields -- they fold from the per-command `combat_events` list embedded in each
`conflict_turn_resolved` / `conflict_encounter_started` / `conflict_encounter_ended`
wire event (raw `backend.lan_playground.combat` event dicts, §1 envelope of
docs/INFINITE_STACKS_COMBAT.md), the same "project by folding the event log" pattern
`domain.reducer.project()` already uses for `RunState`. `hero.life_state` is exactly
`"alive"|"downed"|"stable"|"dead"`; `heroes[]`'s existing `conscious`/`alive` booleans
stay in sync with it (`HeroState.sync_life_state`) so older client code keeps working
unchanged.

### 5.4 Heroes wiring (wave 4, stacks-herowire, board task #13)

`backend.lan_playground.heroes/**` (pure, accepted wave 3,
docs/INFINITE_STACKS_HEROES.md) is now wired into the domain reducer via
`systems/heroes_wire.py`. `HeroState` gains `pending_dice`, `sheet`
(`heroes.creation.HeroSheet`), `deck` (`heroes.deck.DeckState`), `inventory`
(`heroes.inventory.InventoryState`), and `signature_charge`
(`heroes.backgrounds.SignatureCharge`) -- embedded directly (domain now has a
one-way dependency on `heroes/`, the same pattern `systems/combat.py` already
has on `combat/`). All five are `None`/empty until a hero completes creation;
every pre-wave-4 code path (heroes created via plain `join_run` alone, e.g.
existing puzzle/conflict fixtures) is completely unaffected.

New `CommandType` members: `roll_attribute_dice`, `create_hero`, `play_card`,
`draw_cards`, `safe_rest`, `pickup_item`, `drop_item`, `trade_item`,
`recover_body_loot`. New `EventType` members: `attribute_dice_rolled`,
`hero_created`, `card_drawn`, `card_played`, `deck_reshuffled`,
`signature_charge_refreshed`, `item_picked_up`, `item_pickup_rejected`,
`item_dropped`, `item_traded`, `body_loot_recovered`.

- **Creation** is two commands: `roll_attribute_dice` (rolls and stores four
  visible d4s on `pending_dice`, for the dice-animation UI) then `create_hero`
  (`{name, background_id, attribute_assignment, general_card_ids,
  persona_card_id, equipment_card_ids?}`) which assigns attributes, applies
  the background bonus, builds the starting deck through
  `heroes.deck.build_starting_deck` (the build-time LIVE-op gate stays --
  `NonLiveEffectOpError`/`DeckError` surface as `schema_error`), draws an
  opening hand of 4, and seeds inventory from the background's starting
  items. Because `build_starting_deck` shuffles (an RNG draw), the
  `hero_created` event carries the fully resolved sheet/deck/inventory/charge
  as dicts -- replay never re-draws RNG, matching the `MYSTERY_PUZZLE_
  INSTANTIATED` precedent for any RNG-consuming step. `draw_cards`/`play_card`
  are pure deterministic slices with no RNG draw of their own, so their
  events carry only the minimal replay input (count / card_id) and their
  appliers just re-call the same `heroes.deck` function.
- **Card play** (`play_card`) compiles a card's effects to LIVE ops and
  dispatches them through `systems/effects.py`, exactly like Mystery Chamber
  puzzle consequences. If the card has a `check`, it resolves through
  `systems/checks.py` using the hero's **real** `sheet.attributes`/
  `sheet.skills` (the seam `effects.py`'s `grant_check`/`checks.py`'s
  `handle_check` still hardcode `0`/`0` for -- see §5 above -- `play_card` is
  where a real hero-sheet lookup first lands). `safe_rest` reshuffles the
  deck and refreshes a `once_per_floor` signature charge if the hero has one.
- **Signature charges** (`heroes.backgrounds.SignatureCharge`, §11.3) refresh
  at three boundaries: room (`systems/exploration.py`'s `handle_breach` calls
  `heroes_wire.build_room_boundary_refresh_events` for the breaching hero),
  safe rest (`once_per_floor`, folded into `safe_rest` above), and fight
  (`heroes_wire.build_fight_boundary_refresh_events`, published for
  `systems/combat.py`'s encounter-start handler to call and fold into its own
  event tuple -- no live caller yet this wave).
- **Inventory** (`pickup_item`/`drop_item`/`trade_item`/`recover_body_loot`):
  `RoomState` gains `ground_items` (`item_instance_id -> item_id`, items
  available for pickup) and `item_claims` (`item_instance_id -> hero_id`, the
  single-owner contest ledger `heroes.inventory.attempt_pickup` needs).
  `HeroState.carried_item_ids` (the wave-1 §13.6 placeholder) is kept as a
  synced mirror of `inventory.items` on every mutation here, so
  `systems/combat.py`'s existing permanent-death body-loot transfer (which
  reads/clears `carried_item_ids` directly) needed zero changes.
  `recover_body_loot` is the "ally recovers a dead hero's items" half of
  §13.6 -- it reads `RoomState.body_item_ids`, respects the recovering
  hero's real carry slots, and is the wave-4 caller of the
  `heroes.inventory.hero_died_with_items` bridge concept (the death-side
  transfer into `body_item_ids` predates this wave in `systems/combat.py`).
- **Combat equipment seam**: `systems/heroes_wire.resolve_hero_combat_equipment
  (hero: HeroState) -> dict` resolves real `Attributes`/skills/`Weapon`/
  equipment bonuses from `hero.sheet` + `hero.inventory` + content-pack item
  data (never a raw wire number, per the wave-3 director ruling), shaped as
  kwargs for `systems/combat_wire.hero_combatant_from_state` (equipment seam
  published by stacks-combat-depth, wave 4 board task #14). Returns `{}` for
  a hero with no completed creation, preserving today's flat defaults.
  `content.schemas.Item` gained four optional fields for this:
  `weapon_die_faces`/`weapon_damage_bonus`/`weapon_accuracy_bonus` (only
  meaningful when `"weapon" in tags`) and `passive_defense_bonus`.
- **Legal-attacks catalog on the wire**: `StacksEngineAdapter.
  _neutral_conflict_snapshot`'s per-hero dict gains `legal_attacks`, a list
  of `{type: "attack", target_id, accuracy_bonus, weapon_die_faces,
  damage_bonus}` per living enemy, built from the hero's real
  `force`+`bonk` skill rank and `resolve_hero_combat_equipment`'s weapon --
  never a client-suppliable number. Empty for a hero with no completed
  character creation.

### 5.5 Shops wiring (wave 5, stacks-shopwire, board task #18)

`backend.lan_playground.shops/**` (pure, accepted wave 4,
docs/INFINITE_STACKS_SHOPS.md) is now wired into the domain reducer via
`systems/shops_wire.py`. Breaching a `shop` room (d8 == 6) instantiates a
seeded `shops.models.ShopInstance` from a randomly-chosen core-pack archetype
and stores it on `RoomState.shop` -- embedded directly (domain now has a
one-way dependency on `shops/`, the same pattern already established for
`heroes/`/`combat/`). `HeroState` gains `gold` (`int`, starts at
`domain.state.STARTING_GOLD == 20`, decided as data this wave), `item_wear`
(`dict[item_id, int]`), `identified_item_ids` (`tuple[str, ...]`), and
`active_condition_ids` (`tuple[str, ...]`, §16.4-16.5 persistent statuses/
injuries) -- all plain fields on the existing hero dict, no new privacy
scope (gold/wear/identification/conditions are exactly as visible as HP,
per §21.3's "every hero is visible to every party member").

New `CommandType` members: `shop_buy`/`shop_sell`/`shop_repair`/
`shop_identify` (payload `{item_id: str}`), `shop_treat` (payload
`{condition_id: str, treatment_id: str}`). New `EventType` members:
`shop_instantiated`, `shop_item_bought`, `shop_item_sold`,
`shop_item_repaired`, `shop_item_identified`, `shop_condition_treated`,
`shop_transaction_rejected` (uniform rejection event across all five
actions, payload `{action, reason, item_id}` -- mirrors `item_pickup_
rejected`'s "always tell the caller why" discipline). `shop_treat`
dispatches the condition's real `content.schemas.Condition.treatments[]`
effects through `systems/effects.py` (see below) alongside its own
transaction event -- a successful treat therefore emits *two* events
(`shop_condition_treated` + whatever the treatment's effects produce, always
`condition_removed` for every core-pack condition today).

**Wire projection requirement (not yet built -- stacks-heroui's file):**
`project(state, viewer)` should gain a top-level `"shops"` key, parallel to
`"puzzles"`/`"conflict"`:

```
{room_id: {
    archetype_id: str, name: str,
    persona: {name, tagline, tone},
    services: [str, ...],                 # "buy"|"sell"|"repair"|"identify"|"treat"
    listings: [{item_id, buy_price, stock}],   # only items actually in RoomState.shop.stock
                                                # (guaranteed + drawn rotating -- never the
                                                # full rotating_pool candidate set, which
                                                # would leak this shop's unseeded alternates)
    sell_price_ratio: float, repair_cost_per_wear: int,
    identify_price: int, treatment_price: int,
    rumor: {text, accessible_text},
    relationship_complication: {description, accessible_text},
}}
```

All of the above is PUBLIC (§9.6: "Prices are authoritative game data",
visible to any party member who has entered the room) -- the *only* dynamic
part is `listings[].stock`, which changes as `shop_buy`/`shop_sell` events
land; everything else is a static lookup from `shops.content_loader.
load_core_shops()[archetype_id]` and never needs re-deriving from an event.
`RoomState.shop` itself only stores `{archetype_id, stock}} `; the adapter
looks up the rest from the same cached archetype dict `systems/shops_wire.py`
already uses (`shops.content_loader.load_core_shops()`), so nothing new
needs loading.

### 5.6 Server-side clue sharing (wave 5, stacks-shopwire, board task #18)

New `CommandType.share_clue` (payload `{clue_id: str}`): the acting hero must
already own `clue_id` in their own `PuzzleRoomState.private_clue_assignments`
(the same per-hero ledger `inspect_object` populates, §5.1 above) or the
command is `illegal_action`. New `EventType.clue_shared` (`PARTY`
visibility), payload `{clue_id, fallback, accessible}`. `RunState` gains
`party_shared_clues: dict[room_id, tuple[clue_id, ...]]`.

**Wire projection requirement (not yet built -- stacks-heroui's file):**
the puzzles projection block (§5.2) should add a `party_shared_clues: [{clue_id,
fallback, accessible}]` list per room, sourced from `RunState.
party_shared_clues[room_id]` cross-referenced against `PuzzleRoomState.
clue_text` for the prose -- PUBLIC to every current hero (unlike
`your_private_clues`, which stays owner-scoped). A hero's *unshared* private
clues are completely unaffected; sharing only ever adds to this list, never
removes from `private_clue_assignments`.

## 6. Core state aggregates (wave-1 subset of §22.4)

Corrected 2026-07-19 to match `backend/lan_playground/domain/state.py` exactly --
the previous version listed a `pending_turns` dict and a 4-state `ConnectorState`
that never existed in code.

```python
RunState:
    run_id: str
    seed: int
    revision: int
    world_round: int
    chapter_floor_index: int
    heroes: dict[hero_id, HeroState]
    map: MapState | None          # rooms dict + required/maximum room bookkeeping

HeroState:
    hero_id: str
    room_id: str
    energy: int                   # 0-5, refreshed at round boundary
    max_energy: int                # 5 (§8.1); present for future modifiers
    hp: int                        # not exercised meaningfully until Phase 4; present for shape
    max_hp: int
    conscious: bool
    alive: bool
    submitted_turn: bool           # this hero's §8.2 "passed or submitted" gate flag
    movement_locked: bool          # set True after a breach; cleared at round refresh

RoomState:
    room_id: str
    x: int
    y: int
    connectors: dict[Direction, ConnectorState]   # NONE | DOOR (unbreached) | OPEN (breached/entered)
    family: str | None            # set once the d8 has been rolled for this room
    subtype: str | None
    discovered: bool               # observed to exist; content not necessarily rolled
    entered: bool                  # breached: family/subtype rolled, room instantiated
    required: bool                 # counts toward required_rooms
    is_entrance: bool
    is_exit: bool

MapState:
    required_rooms: int
    maximum_rooms: int
    entrance_room_id: str
    exit_room_id: str
    rooms: dict[room_id, RoomState]
    used_subtypes: dict[family, list[subtype]]   # for §7.2 "varied subtypes on repeat"
```

There is no `pending_turns` map -- the §8.2 round-completion gate reads
`HeroState.submitted_turn` directly (`RunState.round_complete()` in `state.py`).

`MapState.required_rooms = min(6 + chapter_floor_index, 12)`,
`maximum_rooms = required_rooms + 3` (§7.3).

## 7. Energy table (§8.1, enforced in `systems/turns.py`)

| Action | Energy |
|---|---:|
| Move to a discovered adjacent room | 1 |
| Breach and enter an unexplored room | 3 |
| Observe through an open connector | 1 |
| Inspect / search / pick up / operate simple object | 1 |
| Pass | 0 |

World round refreshes to 5 Energy for every hero only after every living, conscious
hero has `HeroState.submitted_turn == True` (set by a `pass` command; this engine's
reading of "submitted a turn, passed, or timed out" per §8.2 -- any other exploration
action keeps the round open for that hero). Breaching ends movement for that hero's
turn (further non-move Energy spend inside the room is legal in the same turn if no
encounter interrupts, per §8.1).

## 8. Room family roll (§7.2)

`room_generation.py` rolls a d8 with the seeded RNG, records the raw die face in the
event payload (client displays it unmodified), and separately selects a deterministic
legal subtype for that family + room context. The die face itself is never altered by
subtype selection.

| d8 | Family |
|---:|---|
| 1 | mystery_chamber |
| 2 | passage |
| 3 | study |
| 4 | wild_place |
| 5 | conflict |
| 6 | shop |
| 7 | social_encounter |
| 8 | anomaly |

## 9. Determinism / RNG contract

`rng.py` exposes a single injectable, seedable stream (`StacksRNG`, wraps
`random.Random`) with named draw methods (`roll_d8`, `roll_d20`, `choice`, `shuffle`)
so every draw is logged as an explicit call site. `handle()` receives the RNG and is
the only caller. No other module (including `checks.py` and `room_generation.py` at
the point they need randomness) constructs its own `Random` instance — they receive
the shared `StacksRNG` from `handle`.

## 10. What's out of scope

Combat, cards, inventory, shops, books remain unwired this wave too (combat is a
standalone package, `backend/lan_playground/combat/**`, per docs/INFINITE_STACKS_COMBAT.md
-- reducer wiring for it is wave 3). Wave-1 engine guarantees the golden-floor slice:
join, split, move, breach (with visible d8 + subtype), observe, inspect, Energy
spend/refresh, world-round advance, and deterministic replay. Wave 2 (board task #5)
added real Mystery Chamber puzzle rooms and the four §5 effect ops on top of that --
see §5/§5.1/§5.2 above.
