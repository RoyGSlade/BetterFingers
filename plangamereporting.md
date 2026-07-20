# The Lost Meaning: Infinite Stacks — Progress Report

> Status report for the wave-based build of the game specified in
> `infinite_stacks.md`. This file records **what has shipped**. The remaining
> work is planned in `wavebasedgame.md`.
>
> Last updated: 2026-07-19 (end of wave 5).

## How the build is run

The game is built in **waves**: each wave is 3 parallel worker agents
(sonnet, high effort) in a shared collab room, coordinated by a director
session. Every wave follows the same discipline:

- **Disjoint file ownership** per lane; cross-lane edits are forbidden and
  contract questions go through room chat. One lane per wave is the
  "domain schema owner" whose posted vocabulary is authoritative.
- **Two-step delivery** for big systems: a pure standalone package one wave
  (zero engine imports, rng injected via a structural Protocol), domain
  wiring the next. `combat/`, `heroes/`, and `shops/` all followed this.
- **Independent verification**: the director re-runs every lane's suites
  before accepting, and closes each wave with a full-surface run (all
  stacks suites + architecture gates + the old game's suites).
- **One PR per wave**, stacked so each diff reviews as a single wave.

### PR chain

| PR | Branch | Contents |
|---|---|---|
| #65 | `feat/lost-meaning-game` | The earlier spotlight-loop game (superseded design, still shipped and untouched) |
| #66 | `feat/infinite-stacks-wave1` | Wave 1 — golden-floor foundations |
| #67 | `feat/infinite-stacks-wave2` | Wave 2 — live effects, real puzzles, combat core, screens |
| #68 | `feat/infinite-stacks-wave3` | Wave 3 — combat in the world, live client, heroes package (+ architecture-gate fixes) |
| #69 | `feat/infinite-stacks-wave4` | Wave 4 — heroes wired, combat depth, shops package |
| #70 | `feat/infinite-stacks-wave5` | Wave 5 — live reactions, hero UI, shops in the world (human-playable) |

Merge order is 65 → 66 → 67 → 68 → 69 → 70. Nothing from the old game
(`game.py`, `app.py`, `rooms.py`, `static/{index.html,app.js,style.css}`)
was modified in any wave.

### Verification totals at wave-5 close (director-run)

- Stacks surface + architecture gates: **1,423 passed + 442 subtests**
  (17 test suites)
- Old-game surface: **243 passed + 175 subtests**, zero regressions
- `node --check` clean on all client JS

---

## Wave 1 — Golden-floor foundations (PR #66)

Three lanes: engine, content, transport+client, plus a fourth integration
worker.

**Engine** (`backend/lan_playground/domain/`, `systems/`):
- Event-sourced core per §22.1: `validate / handle / reduce / project`,
  pure reducer (a real in-place-mutation bug was caught and fixed in
  audit), seeded RNG behind a single injectable wrapper, replay of
  seed + event log reproduces an identical state hash.
- Orthogonal tile-map generation — no overlapping rooms, exits always
  reachable, `required_rooms = min(6+floor, 12)` (+3 max), property-tested
  across 200 seeds × multiple floor indices.
- Visible-d8 room families (§7.2), 5-Energy world rounds with refresh only
  after every living conscious hero acts (§8), d20 checks with
  advantage/disadvantage cancellation and §12.3 outcome margins.
- `docs/INFINITE_STACKS_CONTRACTS.md` — the authoritative command/event/
  effect/projection contract all later lanes build against.

**Content** (`backend/lan_playground/content/`):
- Versioned schemas, strict YAML loader, CI-style validators (§23.2).
- Core pack: 4 backgrounds, 5 skills, cards, items, 6 conditions,
  3 enemies with threat costs and telegraphed intents.
- Ordering-sequence Mystery Chamber puzzle template with a seed-driven
  generator and an **independent** solver (never reads the stored
  solution), verified across 1,200 seeds.

**Transport + client** (`stacks_api/protocol/projections/engine.py`,
`static/src/`, `stacks.html`):
- Revisioned WebSocket protocol: idempotent command IDs, stale-revision →
  legal-action summary, viewer-filtered projections, reconnect snapshot +
  missed events, REST fallback. Split into 4 modules under the repo's
  500-line cap.
- Map-first client: fog of war, connector states, route preview, shared d8
  with reduced-motion mode, Energy pips; CSP-safe (no inline styles),
  render-from-state discipline.

**Integration**: the stub adapter was replaced with genuine delegation to
the real engine, and `tests/test_stacks_e2e.py` proves the §33 golden-floor
slice end to end (3-hero split, d8 verification, exact Energy accounting,
precise world-round boundary, reconnect snapshot parity, projection
privacy, seed determinism).

## Wave 2 — Live effects, real puzzles, combat core, screens (PR #67)

- **Effect ops went LIVE**: `systems/effects.py` + reducer wiring for the
  §5 authoring ops (`reveal_room`, `grant_check`, `spend_energy`,
  `emit_fact`); the content-side status flip and its regression test were
  updated in lockstep (the test now asserts every LIVE op has a real
  handler).
- **Real Mystery Chamber rooms** (`systems/puzzles.py`): breaching a d8=1
  room instantiates the seeded puzzle; asymmetric per-hero private clues
  (breacher gets one, others claim theirs by inspecting the key object);
  `inspect_object` / `submit_solution` / `request_hint` commands;
  validator-owned answers; 3-hint escalation then force-progress; every
  rejection fires a fail-forward consequence. Solutions never serialize
  into any projection.
- **Combat core** (`combat/`, pure standalone): initiative with
  deterministic ties, turn budget, attack math, all six §14.4 called
  maneuvers with resist/convert/expose hooks, all six §14.5 reactions,
  data-driven enemy intents, §15.1 total-party threat budget with
  reinforcement scheduling, Downed/death-check/permadeath lifecycle, nine
  statuses with cap-at-two escalation. Zero engine imports; Protocol-typed
  RNG structurally satisfied by the real `StacksRNG`.
- **Puzzle + combat screens**: room/puzzle/combat screens and
  card/check-receipt/status components, fixture-driven; enemy intent
  renders before action selection; the §12.5 factual check receipt renders
  before any narration.

## Wave 3 — Combat in the world, live client, heroes package (PR #68)

- **Conflict rooms are real** (d8=5): threat budget always sized from the
  *total living party* (§15.1), one combat round == one world round,
  distant heroes keep exploring or travel toward the fight and join at the
  next initiative cycle, barricade/delay routes exist for lone entrants.
- **Survival states persist**: Downed/Stable/Dead live on `HeroState`
  across rooms; in-room stabilize; a dead hero's items move to the room's
  body storage; defeated enemies stay dead (§4.1).
- **Director ruling — no client-supplied modifiers**: combat command
  payloads carry no raw numbers; every bonus is server-derived (or, since
  wave 4, resolved from verified source data). The cheat vector was closed
  before it ever shipped.
- **Solvable puzzles end-to-end**: the UI lane proved a valid solve was
  impossible to construct (item ids never reached the wire); the
  projection now exposes orderable items lexicographically (privacy test
  proves the order can't leak the answer) and the submission UI builds
  real `submit_solution` payloads from an item picker.
- **Live client**: normalization layer folding real room-keyed
  puzzle/conflict projections and events into the screens; live
  inspect/hint/submit round-trips; map shows life-state danger tiers and
  in-combat markers.
- **Heroes package** (`heroes/`, pure standalone): visible-4d4 creation
  with free assignment, four backgrounds, derived stats, deck lifecycle
  (draw/discard/Exhaust/reshuffle) with a build-time gate that loudly
  rejects cards referencing non-LIVE effect ops, slot inventory with
  single-owner pickup, signature-ability charges; attribute/skill names
  drift-guarded against `combat.models` by test. Pack expanded to 24
  cards / 20 items.
- **Architecture-gate fixes** (director): the repo's gates require package
  `__init__.py` files to be docstring-only or lazy `__getattr__`
  re-exports; two 0-byte inits got docstrings and the two eager content
  inits were converted to lazy re-exports.

## Wave 4 — Heroes wired, combat depth, shops package (PR #69)

- **Heroes live in the domain**: `roll_attribute_dice` → `create_hero`
  builds sheet + deck + inventory + signature charge on `HeroState`
  (replay-safe, single RNG-consuming step); `play_card` compiles through
  LIVE effect ops with real attribute/skill checks; safe-rest reshuffle;
  room/floor signature-charge refresh; `pickup_item` / `drop_item` /
  `trade_item` / `recover_body_loot` with single-owner ground claims.
- **Equipment reaches combat**: weapon/defense stats added to content
  items; `resolve_hero_combat_equipment()` resolves them into verified
  concrete values for `hero_combatant_from_state()`'s kwarg seam — the
  no-raw-wire-numbers ruling holds end to end. Per-hero `legal_attacks`
  catalog added to the conflict projection.
- **Combat depth** (closed board task #12): a true reaction interrupt
  window in `attack()` between hit-determination and damage-application
  (Block reduces damage + Wear, Dodge negates + repositions, Protect
  redirects, Counter on miss-by-5+) — unit-tested, but with **no live
  caller yet** because enemy actions have no to-hit roll (tracked as
  wave-5 task #16). End-of-round Bleeding/Burning ticks flow through the
  single HP seam; a tick on a Downed hero adds a death failure (tested).
- **Shops package** (`shops/`, pure standalone): seeded inventories,
  authoritative prices, buy/sell/repair/identify/treat services, economy
  anti-loop proven structurally *and* by a 1,000-seed property test (no
  action sequence can increase total wealth), run-summary fold over real
  recorded event logs, 2 shop archetypes in content with loader/validator
  support.
- **Cross-lane save**: herowire's new item fields broke the strict content
  loader mid-wave; test collection caught it, the director routed it, the
  file's owner fixed it, both lanes re-verified — ~1 minute of breakage.

## Wave 5 — Live reactions, hero UI, shops in the world (PR #70)

**The game became human-playable end to end this wave**: create a hero in
the browser, explore, solve a puzzle, fight with live reactions, shop,
finish a floor.

- **Enemy to-hit + live reaction interrupts** (closed task #16): enemy
  attack intents resolve through `attack()` (d20 + tier-keyed accuracy
  +2/+4/+6/+8 vs hero Defense) instead of flat damage; the wave-4
  interrupt window finally has a live caller. A pending reaction pauses
  resolution and **blocks the world round** — a director veto reshaped
  the original design, whose round-boundary auto-default would have
  silently eaten every reaction prompt in solo play. The defender answers
  via `resolve_reaction` (zero numeric fields); the transport's
  `ReactionAutoPass` timer injects a server-originated pass on expiry
  through the ordinary command log, so no wall-clock ever reaches the
  reducer and replay holds. Companion defaults for disconnected heroes
  use the same injection — no special code path.
- **Hero command surface + UI** (closed task #17): all wave-4 hero
  commands round-trip over WS/REST with hand-privacy projections
  (hand/draw order visible only to the owning viewer); one-screen
  character builder with visible 4d4 assignment; hand/deck/inventory
  panel; per-target combat buttons from the `legal_attacks` catalog;
  reaction-prompt UI gated to defender/protectors; a content-catalog
  endpoint marks LIVE-at-creation cards so the builder can never offer a
  card the build-time gate would reject. Also removed the last
  raw-numbers-from-the-wire violation (the old `combat_reaction`
  command).
- **Shops in the world** (closed task #18): d8=6 rooms instantiate seeded
  shops persisted on `RoomState`; `shop_buy/sell/repair/identify/treat`
  as domain commands bridging the pure `ShopperState` to real hero
  inventory and gold; `shop_treat` consumes gold and applies real
  condition treatments; server-side `share_clue` command with a
  `party_shared_clues` projection; layering cleanup done properly — shop
  content loading moved *into* `shops/content_loader.py`, and `content/`
  no longer imports `shops/`.
- **Wave note:** two workers completed their lanes but died (likely OOM
  during concurrent full-suite verification) before posting handoffs.
  The director audited both lanes against their acceptance criteria on
  disk, found them complete, implemented the one declared close-out item
  (the reaction timer + 3 unit tests), and closed the tasks. Recorded
  lesson: stagger final verification runs across lanes.

---

## Key design decisions on record (collab board notes)

1. `infinite_stacks.md` is canonical and supersedes the spotlight-loop
   game; the old game's files are never touched.
2. Engine contract doc is authoritative; corrections are posted urgently.
3. Effect ops were authoring-contract-only until real handlers existed —
   nothing ever claimed to be wired that wasn't.
4. The LLM decides nothing mechanical anywhere (no code path exists).
5. No client-supplied numeric modifiers, ever; server derives or verifies.
6. Package `__init__` files: docstring-only or lazy re-exports.
7. Pure-package-first, wire-next-wave is the default for new systems.
