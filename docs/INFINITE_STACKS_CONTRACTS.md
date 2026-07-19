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
                                   # full wave-1 vocabulary: EventType in domain/events.py
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

## 5. Content-effect interface -- NOT YET IMPLEMENTED THIS WAVE

Corrected 2026-07-19: this section previously claimed handlers shipped for
`reveal_room` and `spend_energy`. That was wrong -- as of this wave `backend/lan_playground/
systems/` has **no effect-op dispatcher or handler of any kind**; grep confirms zero
references to `reveal_room`, `grant_check`, `spend_energy`, or `emit_fact` anywhere in
`domain/` or `systems/`. Board task #1's acceptance criteria (state/commands/events/
reducer + map/Energy/world-round systems) does not require this interface, so it was
correctly out of scope for wave-1 engine work -- but the doc should not have claimed it
existed. Treat the shape below as a **design placeholder for a future wave**, not a
callable contract:

```yaml
# NOT IMPLEMENTED -- design sketch only, no code binds to this yet.
- op: reveal_room          # exposes a connector's target room
  args: {connector: north}
- op: grant_check           # trigger a d20 check via systems/checks.py
  args: {attribute: insight, skill: read, dc: 11}
- op: spend_energy
  args: {amount: 1}
- op: emit_fact             # authored fact available to book/prose pipeline later
  args: {fact_id: string}
```

Content packs should NOT assume any of these ops are wired to the reducer yet. If your
lane needs one exercised end to end this wave, post an `urgent` request to `stacks-engine`
before building on top of it.

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

## 10. What's out of scope this wave

Combat, cards, inventory, puzzles, shops, books — stubs only where the effect-op
interface above needs a placeholder. Engine only guarantees the golden-floor slice:
join, split, move, breach (with visible d8 + subtype), observe, inspect, Energy
spend/refresh, world-round advance, and deterministic replay.
