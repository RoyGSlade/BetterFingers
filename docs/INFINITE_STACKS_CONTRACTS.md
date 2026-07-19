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
accessible}], solved, forced, attempts_used, attempt_limit, hints_revealed: [{fallback,
accessible}], your_private_clues: [{clue_id, fallback, accessible}]}}`.

`hints_revealed` and `your_private_clues` are both viewer-filtered by
`stacks_projections.project_puzzles()`: empty for a spectator (`viewer is None`);
`your_private_clues` contains only clues assigned to that specific hero_id, never any
other hero's fragment. `solution` and `accepted_solutions` are never present in this
dict at all (stripped before `stacks_engine.py` ever builds the neutral snapshot) --
they exist only in internal domain state (`PuzzleRoomState`), never in any projection.

Known open item (per director, 2026-07-19 16:30): stacks-ui's wave-2 fixtures
(`tests/fixtures/stacks_ui/puzzle_mystery_chamber.json`) were authored before this
section landed and use a different field vocabulary (`puzzle.objects/private_clue/
shared_notes/hints`). This section is the authoritative engine projection shape; the
fixture/selector reconciliation is a follow-up pass at wave close, not a reason to
reshape this projection.

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
