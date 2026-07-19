# The Lost Meaning -- Game Spec (board task #1)

A 1-4 player cooperative communication adventure built on the LAN
playground (`backend/lan_playground/`). Four fixed heroes -- each with a
persona, an ability, a distinct move deck, an exclusive signature move, and
a private per-encounter clue about the encounter's real (hidden) objective
-- face five absurd office-life encounters. Every round the rotating
Spotlight hero declares a move + target + desired outcome, teammates pledge
support, the Spotlight drafts a rough line that BetterFingers turns into
three candidate rewrites, the Spotlight edits and approves one message +
intent, teammates react (interpret/assist/challenge/protect), and the
engine resolves the round from a fully transparent modifier ledger plus one
seeded die -- no hidden state, no randomness outside that one die.

This document specifies the rules and the `Room`/`GameRegistry` contract
implemented in `backend/lan_playground/game.py` (tests in
`tests/test_lan_game_engine.py`, 59 tests, all passing). It is the frozen
interface for:

- **lost-meaning-server** (board task #2) -- wraps `GameRegistry`/`Room` in
  HTTP routes, mints/serves QR-joinable links, owns tokens-over-the-wire,
  calls the BetterFingers rewrite pipeline and feeds its output into
  `submit_variants()`.
- **lost-meaning-client** (board task #3) -- renders `public_state()` and
  posts player actions.

This replaces the prior Charm/Scheme/Bonk simultaneous-choice combat loop
(the old five-encounter engine with a shared hearts pool and a single
secret approach pick per round) entirely; nothing about that loop's method
names or phases survives.

## Design invariants

- **Pure engine.** `game.py` has zero FastAPI, network, or LLM imports. It
  is a plain, thread-safe, in-memory state machine -- fully unit-testable
  with no server/model boot required (mirrors `backend/lan_playground/security.py`).
- **Prose can never alter resolution.** Free text -- `desired_outcome`,
  rough/variant/approved text, `intent`, support/reaction `detail`, and any
  `set_flavor()` overlay -- is display-only and is never read by
  `resolve()`. Resolution only ever reads `move_id`/`target_id`/reaction
  `verb` fields (fixed enums) plus one seeded die. A game is exactly as
  fair with BetterFingers running as with the model completely offline and
  every rewrite falling back to three identical copies of the canonical
  text -- the deterministic model-free fallback.
- **Cards and clues are transparent, secrets are scoped, not hidden by
  default.** A hero's move deck, signature move, ability, and persona are
  always public (`heroes[]`). The Spotlight's move/target/desired-outcome
  become public the instant they're declared (`current_action`) -- this is
  not a simultaneous hidden-choice game. Only two things are ever actually
  secret: (1) a hero's private clue, visible solely to that hero via `you`,
  and (2) support/reaction *content* (kind/verb/detail/move_id), which
  stays invisible to every viewer -- including the contributor's own
  future reads and the host -- until `resolve()` reveals it in
  `last_round`/`history`. Before that, only a boolean "have they gone yet"
  (`heroes[].submitted_current_step`) is visible. The Spotlight's own
  rough-text/variants/approved-text-in-progress are visible only to that
  Spotlight's own viewer (`you.draft`), not even to the host.
- **No secrets leak.** `Room.public_state()` never includes any player's
  token.
- **Solo and disconnects are always playable.** Heroes are fixed (see
  below) and always all four are "in play" every game. Any hero slot with
  no human controller -- never claimed, or claimed by a player who is
  currently disconnected -- is played by small, deterministic,
  seed/round-derived companion logic, so a 1-player game (or a game where
  someone drops mid-round) always has all four heroes acting and the room
  never stalls waiting on a human who isn't there. Autoplay runs
  synchronously inside every phase-transitioning call (including
  `disconnect()`), so a companion's pending step is always filled before
  any human could ever observe it as merely "pending."
- **Deterministic seed.** Each room shuffles the first four of five
  encounters' order from an integer seed (`random.Random(seed).shuffle`);
  the Red-Tape Dragon always occupies the final stop. The one die rolled
  per round is also seed-derived (`random.Random(seed * 1_000_003 +
  encounter_index)`), so a given seed reproduces an identical run --
  useful for tests and for `replay(seed=...)`.

## The four heroes

Heroes are fixed -- there is no character-creation or selection step.
`Room.join()` binds each new player to the next open slot in this order:

| Order | Hero | Persona | Ability | Deck | Signature move |
|---|---|---|---|---|---|
| 0 | Bram Correctly | Overly-formal municipal clerk who fights bureaucracy with more bureaucracy, kindly | **Steady Hand** -- playing Precision Bonk or The Unimpeachable Memo as Spotlight reduces that round's backfire damage by 1 | Empathic Mirror, Precision Bonk, Cross-Reference | The Unimpeachable Memo (scheme) |
| 1 | Nadia Quickwit | Fast-talking dispute-resolution specialist, sharp and a little chaotic | **Loophole Sense** -- her own challenge reaction gets +1 extra | Loophole with Consequences, Disarming Honesty, Cross-Reference | The Airtight Rebuttal (scheme) |
| 2 | Otis Barnstorm | Blunt, warm-hearted forklift-driver-turned-negotiator | **Follow-Through** -- as Spotlight playing his weakness school, +1 extra | Precision Bonk, Smash the Right Thing, Improvised Bonk | The One True Thump (bonk) |
| 3 | Ilona Softword | Gentle, empathetic mediator, a master of tone | **Read the Room** -- her own protect reaction reduces damage by 2 instead of 1 | Empathic Mirror, Defend the Speaker, Disarming Honesty | The Perfect Pause (charm) |

The Spotlight rotates by `encounter_index % 4`, i.e. hero 0, 1, 2, 3, 0
across the five rounds -- hero 0 gets a second turn in round 4 (the
Red-Tape Dragon). Any slot beyond the number of humans who joined (or
belonging to a currently-disconnected player) is a **companion**: deterministic,
round-derived choices (its deck move at `encounter_index % len(deck)`,
first listed target, a fixed canned line for support/draft, and a
round-derived reaction verb) so the game is always fully playable solo.

## Moves (schools remain Charm/Scheme/Bonk, cards are distinct)

| Move | School | Reaction affinity |
|---|---|---|
| Empathic Mirror | charm | assist, interpret |
| Disarming Honesty | charm | assist, challenge |
| Cross-Reference | scheme | interpret |
| Loophole with Consequences | scheme | challenge |
| Precision Bonk | bonk | (none -- pure Spotlight card) |
| Defend the Speaker | bonk | protect |
| Smash the Right Thing | bonk | (none -- pure Spotlight card) |
| Improvised Bonk | bonk | assist, protect |
| *(signature, one per hero)* The Unimpeachable Memo / The Airtight Rebuttal / The One True Thump / The Perfect Pause | scheme / scheme / bonk / charm | interpret+challenge / challenge / (none) / protect+assist |

Any move may be played as the Spotlight's primary action regardless of its
`verbs` tag -- the tag only matters when an ally *cites* a move while
reacting (see "Card synergy" below). A hero's available moves are always
their 3-card deck plus their one exclusive signature move (never reused by
anyone else); decks are not consumed or drawn from -- every hero's full kit
is available every round.

## The five encounters

Same five absurd office-life encounters as before -- each weak to one
school, resistant to another (distinct), neutral to the third -- now each
also carries 2-3 named **targets** (one of them the actual `true_target`)
and one **private clue per hero**, asymmetric and truthful, hinting at
which target is real without stating it outright:

| Encounter | Weak to | Resistant to | True target |
|---|---|---|---|
| The Passive-Aggressive Troll | scheme | bonk | the toll ledger |
| The Goblin HR Department | charm | scheme | the tiny rubber stamp |
| The Suggestion-Box Mimic | bonk | charm | the hinge of its lid |
| The Bridge of Needlessly Complicated Riddles | charm | bonk | the gargoyle's mood |
| The Red-Tape Dragon *(final boss)* | scheme | charm | the filing cabinet's index |

The first four are shuffled by the room seed; the Dragon always occupies
the final stop. Clue text lives in `Encounter.clues: dict[hero_id, str]` --
see `backend/lan_playground/game.py` for exact wording.

## Phases

```
lobby -> spotlight_action -> ally_support -> spotlight_draft -> ally_reaction -> reveal -> ...(loop)... -> finished
                                                                                              |
                                                                                          replay() -> lobby
```

- **lobby** -- players `join()` (max 4; each bound to the next open hero
  slot). Host is whoever created the room. Host calls `start()`.
- **spotlight_action** -- the current Spotlight hero's controller calls
  `submit_spotlight_action(move_id, target_id, desired_outcome)`. If the
  Spotlight is a companion this round, the engine fills it immediately and
  the phase advances to `ally_support` with no call needed.
- **ally_support** -- every other active hero's controller calls
  `submit_support(kind, detail)` once (`kind` one of `clue`/`item`/`assist`/`reaction`).
  Companion allies are auto-filled immediately. Once everyone's in
  (`can_open_draft()`), the host calls `open_draft()`.
- **spotlight_draft** -- the Spotlight calls, in order,
  `submit_rough_text(text)`, then `submit_variants([v1, v2, v3])` (the
  transport layer's three BetterFingers rewrites, or three identical
  copies of the rough text as the deterministic offline fallback -- the
  engine never generates this prose itself), then
  `approve_message(chosen_text, intent)` (one of the variants, edited or
  not, plus a stated intent). Approval advances the phase to
  `ally_reaction`. If the Spotlight is a companion, all three steps happen
  automatically and instantly.
- **ally_reaction** -- every other active hero's controller calls
  `submit_reaction(verb, detail, move_id=None)` once (`verb` one of
  `interpret`/`assist`/`challenge`/`protect`; `move_id` optionally cites one
  of that hero's own moves for a synergy bonus). Companion allies are
  auto-filled immediately. Once everyone's in (`can_resolve()`), the host
  calls `resolve()`, which reveals everything and applies damage.
- **reveal** -- `resolve()` has just returned the round's full
  `round_record`. The host calls `advance()`. If that round brought hearts
  to 0, `resolve()` skips straight to **finished** (defeat) instead.
- **finished** -- victory (all 5 rounds survived) or defeat (hearts hit 0).
  Host may `replay()` to reset to a fresh **lobby**, same roster, reseeded.

## Resolution: the modifier ledger and the one seeded die

Every round, `resolve()` builds an ordered list of modifiers -- nothing is
ever computed and then hidden; every contributing fact appears in
`round_record["modifiers"]` as `{source, label, value, affects}`, where
`affects` is `"score"` or `"damage"`:

1. **School match** (`affects: score`) -- the Spotlight's move school vs.
   the encounter: `+3` weakness, `-3` resistant, `0` neutral.
2. **Target insight** (`affects: score`) -- `+1` if `target_id ==
   true_target`, else `0`.
3. **Spotlight abilities** (`affects: score`, only when eligible) --
   Otis's Follow-Through (+1, weakness match).
4. **Support contributions** (`affects: score`, one entry per ally) --
   `assist`/`item`/`clue` give `+1` each (clue also reveals that hero's
   clue text); `reaction` gives `0` (a free, no-effect contribution for a
   player who just wants to say something).
5. **Ally reactions** (one entry per ally, plus a possible card-synergy
   entry) -- `assist`/`interpret` give `+1` (`affects: score`; interpret
   also always reveals that hero's clue); `challenge` gives `+1` (`affects:
   score`) and is Nadia's own +1 extra (Loophole Sense) if she's the one
   challenging; `protect` gives `0` to score but `-1` (or `-2` for Ilona,
   Read the Room) `affects: damage`. Citing an owned move whose `verbs`
   include the chosen verb adds a further `+1` "card synergy" (`affects:
   score`).
6. **The die** (`affects: score`) -- `random.Random(seed * 1_000_003 +
   encounter_index).randint(1, 6) - 3`, i.e. -2..+3, recorded as both
   `die_roll` (the raw 1-6) and this modifier's value.
7. **Bram's Steady Hand** (`affects: damage`, only when eligible) -- `-1`
   when he's Spotlight playing Precision Bonk or The Unimpeachable Memo.
8. **Challenge risk** (`affects: damage`, only if the round is already a
   backfire) -- `+ (number of challenges)`, only added when `score < 0`.

Then:

```
score = sum(value for modifiers where affects == "score")
raw_damage = max(0, -score)
damage = max(0, raw_damage + sum(value for modifiers where affects == "damage"))
hearts = max(0, hearts - damage)
```

With exactly three mandatory allies contributing every round (every
support/reaction choice is worth `>=0` toward safety by design -- nothing
an ally can pick ever actively hurts the party), a well-supported,
correctly-targeted weakness play is always very safe. A resistant,
wrong-targeted play with unhelpful allies and a bad die roll can still
genuinely cost hearts -- the `+-3` base (not `+-1`) leaves real room below
the guaranteed floor of ally support for that to matter. See
`VictoryDefeatTests` in the test suite for a worked "guaranteed victory"
strategy and a searched "can genuinely cause defeat" seed.

## Identity and tokens

Unchanged from the prior contract: `Room.join(name)` -> `(player_id,
token)`; `token` is secret, returned once, and must be supplied on every
subsequent mutating call, checked with `secrets.compare_digest`.
`Room.verify_token(player_id, token) -> bool` is a read-only, never-raising
check. The first player to `join()` becomes host; host authority transfers
to the next active player if the host disconnects (unchanged from before).

## `Room` API (backend/lan_playground/game.py)

```python
class Room:
    room_id: str
    seed: int
    phase: Literal["lobby", "spotlight_action", "ally_support", "spotlight_draft",
                   "ally_reaction", "reveal", "finished"]
    hearts: int
    max_hearts: int
    host_id: str | None
    encounter_index: int

    def join(self, name: str) -> tuple[str, str]: ...            # (player_id, token)
    def disconnect(self, player_id: str, token: str) -> None: ...
    def reconnect(self, player_id: str, token: str) -> None: ...
    def verify_token(self, player_id: str, token: str) -> bool: ...

    def start(self, player_id: str, token: str) -> None: ...     # host only, lobby -> spotlight_action

    def submit_spotlight_action(
        self, player_id: str, token: str, move_id: str, target_id: str, desired_outcome: str
    ) -> None: ...                                                # current Spotlight hero's controller only

    def submit_support(self, player_id: str, token: str, kind: str, detail: str = "") -> None: ...
                                                                   # kind: clue|item|assist|reaction; any ally, once
    def can_open_draft(self) -> bool: ...
    def open_draft(self, player_id: str, token: str) -> None: ... # host only

    def submit_rough_text(self, player_id: str, token: str, text: str) -> None: ...      # Spotlight only
    def submit_variants(self, player_id: str, token: str, variants: list[str]) -> None: ...
                                                                   # Spotlight only; must be a list of EXACTLY 3
    def approve_message(self, player_id: str, token: str, chosen_text: str, intent: str) -> None: ...
                                                                   # Spotlight only -> ally_reaction

    def submit_reaction(
        self, player_id: str, token: str, verb: str, detail: str = "", move_id: str | None = None
    ) -> None: ...                                                # verb: interpret|assist|challenge|protect; any ally, once
    def can_resolve(self) -> bool: ...
    def resolve(self, player_id: str, token: str) -> dict: ...    # host only -> round_record

    def advance(self, player_id: str, token: str) -> None: ...                    # host only
    def replay(self, player_id: str, token: str, seed: int | None = None) -> None: ...  # host only

    def update_voice_profile(self, player_id: str, token: str, metadata: dict) -> None: ...
                                                                   # caller's own hero only, any phase
    def set_flavor(self, key: str, text: str) -> None: ...        # cosmetic overlay only, no auth
    def public_state(self, viewer_player_id: str | None = None) -> dict: ...
```

### `GameRegistry` API

```python
class GameRegistry:
    def create_room(self, host_name: str, seed: int | None = None) -> tuple[Room, str, str]: ...  # (room, host_player_id, host_token)
    def get(self, room_id: str) -> Room | None: ...
    def remove(self, room_id: str) -> None: ...
```

### Exceptions (all subclass `GameError`)

`RoomFullError`, `InvalidPhaseError`, `NotHostError`, `WrongTurnError` (not
the acting party for this step -- wrong hero for a Spotlight-only call, or
the Spotlight trying to submit an ally-only step), `UnknownPlayerError`,
`InvalidTokenError`, `AlreadySubmittedError`, `NotAllSubmittedError`,
`InvalidMoveError`, `InvalidTargetError`, `InvalidSupportKindError`,
`InvalidReactionVerbError`, `NoItemsRemainingError`, `InvalidVariantsError`.
The transport layer maps these to HTTP status codes as before (409 for
phase/already-submitted/not-all-submitted, 403 for host/turn/token errors,
404 for unknown player, 422 for invalid move/target/kind/verb/variants, 429
or 409 for no-items-remaining).

## `public_state(viewer_player_id=None)` shape

```jsonc
{
  "room_id": "room_AbC123",
  "phase": "ally_reaction",
  "hearts": 2, "max_hearts": 3,
  "host_id": "p_xyz",
  "spotlight_hero_id": "nadia_quickwit",
  "players": [                      // human accounts only -- token-bearing identities
    {"player_id": "p_xyz", "name": "Roy", "is_host": true, "active": true, "hero_id": "bram_correctly"}
  ],
  "heroes": [                        // always exactly 4 -- public character sheets, always visible to everyone
    {
      "hero_id": "bram_correctly", "name": "Bram Correctly", "persona": "...",
      "ability_name": "Steady Hand", "ability_description": "...",
      "deck": [{"id": "empathic_mirror", "name": "Empathic Mirror", "school": "charm", "verbs": ["assist", "interpret"], "description": "..."}, "..."],
      "signature_move": {"id": "unimpeachable_memo", "name": "The Unimpeachable Memo", "school": "scheme", "verbs": ["interpret", "challenge"], "description": "..."},
      "player_id": "p_xyz", "is_companion": false, "active": true,
      "items_remaining": 1, "voice_calibrated": false,
      "submitted_current_step": true
    }
  ],
  "round_index": 1, "total_rounds": 5,
  "encounter": {"id": "goblin_hr_department", "name": "The Goblin HR Department", "flavor": "...", "targets": ["the lunch-break form", "the compliance seminar sign-up", "the tiny rubber stamp"]},
  "current_action": null,           // or {hero_id, move, target_id, desired_outcome, approved_text, intent} once declared -- approved_text/intent null until approve_message()
  "last_round": null,               // or the most recent round_record (see below), including narration
  "history": [],                    // all prior round_records, oldest first
  "finished_victory": null,         // true | false | null
  "you": {                          // only present if viewer_player_id is a known player
    "player_id": "p_xyz", "is_host": true, "active": true, "hero_id": "bram_correctly",
    "private_clue": "The quill only signs what the ledger already allows.",
    "draft": null,                  // {rough_text, variants, approved_text, intent} ONLY if you == current Spotlight hero AND phase == spotlight_draft
    "voice_profile": {},            // your own hero's session-only metadata (utterance_count/confidence/calibrated), never another viewer's
    "items_remaining": 1,
    "pending_step": "submit_support" // convenience hint; see game.py's _pending_step_locked for the full state machine
  }
}
```

No entry above ever contains a `token`. No viewer -- including the
contributor -- ever sees support/reaction `kind`/`verb`/`detail`/`move_id`
before `resolve()`; only `submitted_current_step` is visible before that.
No viewer other than the Spotlight ever sees `draft` content, host
included.

### `round_record` shape (`resolve()` return value, and each entry of `last_round`/`history`)

```jsonc
{
  "round": 1,
  "encounter": {"id": "goblin_hr_department", "name": "...", "flavor": "...", "targets": [...]},
  "spotlight_hero_id": "nadia_quickwit",
  "action": {
    "hero_id": "nadia_quickwit", "move_id": "loophole_with_consequences", "move_name": "Loophole with Consequences",
    "school": "scheme", "target_id": "the tiny rubber stamp", "desired_outcome": "...",
    "approved_text": "...", "intent": "..."
  },
  "support": [{"hero_id": "otis_barnstorm", "name": "Otis Barnstorm", "kind": "assist", "detail": "..."}],
  "reactions": [{"hero_id": "ilona_softword", "name": "Ilona Softword", "verb": "protect", "detail": "...", "move_id": "defend_the_speaker"}],
  "true_target_id": "the tiny rubber stamp",
  "revealed_clues": [{"hero_id": "otis_barnstorm", "name": "Otis Barnstorm", "clue_text": "The form doesn't matter until it's stamped."}],
  "modifiers": [{"source": "school_match", "label": "...", "value": 3, "affects": "score"}, "..."],
  "die_roll": 4,
  "score": 5,
  "damage": 0,
  "hearts_before": 3, "hearts_after": 3,
  "narration": ""                  // overlaid live at read time from set_flavor(f"narration:{round}", ...); "" until the transport layer sets it
}
```

`revealed_clues` only ever includes heroes who *voluntarily* exposed their
clue (via support `kind="clue"` or reaction `verb="interpret"`) -- the
Spotlight's own clue, and any ally who did neither, never appears.

## Persona/LLM rewrite integration point

`game.py` never calls an LLM. The transport layer generates three
BetterFingers rewrites of the Spotlight's rough text and calls
`submit_variants([v1, v2, v3])` (or, offline / for a companion Spotlight,
three identical copies of the rough text -- the deterministic model-free
fallback baked into the engine itself for companions). For narration, call

```python
room.set_flavor(f"narration:{round_index}", narration_text)
```

**after** `resolve()` for that round -- `public_state()` overlays this onto
`last_round`/`history` at read time (`_round_record_public_locked`), so it
can only ever describe facts already recorded in that round's
`round_record`; it is never read by `resolve()` and cannot influence a
score that has already been computed. `room.set_flavor(f"encounter:{id}",
text)` similarly overlays an encounter's cosmetic `flavor` line (works
before or after resolution, same as before). If the model is offline or
`set_flavor()` is never called, every encounter/round renders its plain
canonical text and the game is identical in outcome.

## Session-only voice-learning metadata

`update_voice_profile(player_id, token, metadata)` accepts exactly three
bounded scalar keys -- `utterance_count` (int, clamped 0-9999), `confidence`
(float, clamped 0.0-1.0), `calibrated` (bool) -- for the caller's own hero,
in any phase. Unknown keys are silently ignored; raw audio is never
accepted in any form, and nothing here is ever persisted to disk (this
module has no I/O, so the data lives only as long as the `Room` object
does). It is visible to its owner only via `you.voice_profile`; every other
viewer sees only a derived `voice_calibrated: bool` in that hero's public
`heroes[]` entry.
