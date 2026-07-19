# Spellcheck & Sorcery -- Game Spec (board #39)

A 1-4 player, humor-forward co-op card-board adventure built on the LAN
playground (`backend/lan_playground/`). The party shares 3 hearts and faces
five absurd office-life "encounters." Each round every player secretly picks
one of three approaches -- **Charm**, **Scheme**, or **Bonk** -- plus a
bounded one-line flavor move. The host reveals everyone's choice at once and
the engine resolves the round deterministically from the approaches alone.

This document specifies the rules and the `Room`/`GameRegistry` contract
implemented in `backend/lan_playground/game.py` (tests in
`tests/test_lan_game_engine.py`). It is the frozen interface for:

- **game-server-sonnet** (board #40) -- wraps `GameRegistry`/`Room` in HTTP
  routes, mints/serves QR-joinable links, owns tokens-over-the-wire.
- **game-client-sonnet** (board #41) -- renders `public_state()` and posts
  player actions.

## Design invariants

- **Pure engine.** `game.py` has zero FastAPI, network, or LLM imports. It
  is a plain, thread-safe, in-memory state machine -- fully unit-testable
  with no server/model boot required (mirrors `backend/lan_playground/security.py`).
- **Cosmetic prose cannot alter score.** Resolution reads only the fixed
  `approach` string (`"charm" | "scheme" | "bonk"`) a player submitted.
  Free-text `move_text` and any persona/LLM-rewritten flavor text
  (`Room.set_flavor()`) are display-only and are never inspected by
  `resolve()`. A game is exactly as fair with an LLM running as with the
  model completely offline and every line falling back to its canonical
  text -- this satisfies "playable without a model via deterministic
  fallback content" (see `progress.md`).
- **No secrets leak.** `Room.public_state()` never includes any player's
  token, and never includes another player's submitted approach/move_text
  for the round currently in progress -- only whether they've submitted.
  Choices become visible to everyone only after `resolve()` reveals them.
- **Disconnect never deadlocks.** If the host disconnects, the next active
  player (join order) is auto-promoted to host so someone can always drive
  the game. If everyone disconnects (solo host included), the room simply
  waits; the departed host keeps/reclaims the role on reconnect.
- **Deterministic seed.** Each room shuffles the 5 encounters' order from
  an integer seed (`random.Random(seed).shuffle`). Same seed -> same
  encounter order, every time -- useful for tests, and for a host who wants
  to reproduce a specific run via `replay(seed=...)`.

## Phases

```
lobby -> choosing -> reveal -> choosing -> reveal -> ... -> finished
  ^                                                             |
  '-------------------------- replay() -------------------------'
```

- **lobby** -- players may `join()` (max 4 active). Host is whoever
  created the room (`GameRegistry.create_room`'s first `join()`). Host
  calls `start()` to begin.
- **choosing** -- every active player secretly `submit_choice()`s an
  approach + move_text for the current encounter. Once every *active*
  player has submitted (`can_resolve()` is true), the host calls
  `resolve()`.
- **reveal** -- `resolve()` has just revealed everyone's choice for this
  round and applied hearts damage. The host calls `advance()` to continue.
  If that resolve brought hearts to 0, the room skips reveal and goes
  straight to **finished** (defeat) -- there is nothing left to advance to.
- **finished** -- either victory (all 5 encounters survived) or defeat
  (hearts hit 0). Host may `replay()` to reset to a fresh **lobby** with
  the same roster and a new deterministic seed.

## Approaches and combat resolution

Every encounter is weak to exactly one approach, resistant to exactly one
(different) approach, and neutral to the third:

| Approach | Effect when it matches the encounter's `weakness` | Effect when it matches the encounter's `resistant` | Effect when it's the `neutral` approach |
|---|---|---|---|
| any | +1 to `successes` | +1 to `backfires` | no effect (always safe) |

Per round:

```
damage = max(0, backfires - successes)
hearts = max(0, hearts - damage)
```

This is fully deterministic given the set of submitted approaches -- no
randomness, no hidden dice. Playing every encounter's `weakness` as a group
guarantees zero damage forever; playing its `resistant` as a group deals
damage equal to the number of players who did so, discounted 1-for-1 by
anyone who played the `weakness` instead. `neutral` is the "safe but does
nothing" fallback for an unsure player.

## The five encounters

| Encounter | Weak to | Resistant to | Neutral | Flavor |
|---|---|---|---|---|
| The Passive-Aggressive Troll | Scheme | Bonk | Charm | A bridge clerk with seventeen unchecked boxes. Out-file it; punching only creates another incident report. |
| The Goblin HR Department | Charm | Scheme | Bonk | Five goblins and nine clipboards. Warmth gets the lunch-break request stamped; schemes trigger a compliance seminar. |
| The Suggestion-Box Mimic | Bonk | Charm | Scheme | Reads anonymous feedback aloud and has far too many teeth. Charm only encourages it. |
| The Bridge of Needlessly Complicated Riddles | Charm | Bonk | Scheme | Every answer unlocks two more forks. Be pleasant to the gargoyles; force adds another approval layer. |
| The Red-Tape Dragon *(final boss)* | Scheme | Charm | Bonk | Forged from forms and filing cabinets. Out-procedure it; kindness triggers a mandatory survey. |

All five (weakness, resistant) pairs are distinct, so no two encounters
reward identical team strategy. The room seed shuffles the first four map
stops; the Red-Tape Dragon always occupies stop five.

## Identity and tokens

- `Room.join(name)` -> `(player_id, token)`. `player_id` is a public,
  stable identity (used in `public_state()`); `token` is a secret,
  returned exactly once, and must be supplied by the caller on every
  subsequent mutating call (`start`, `submit_choice`, `resolve`, `advance`,
  `replay`, `disconnect`, `reconnect`) and is checked with a constant-time
  comparison (`secrets.compare_digest`), matching the access-code pattern in
  `backend/lan_playground/security.py`.
- `Room.verify_token(player_id, token) -> bool` is a read-only check for
  GET-style "who am I" endpoints -- it never raises and never mutates
  state.
- The first player to `join()` an empty room becomes host
  (`GameRegistry.create_room` performs this join for you). Host authority
  transfers automatically if the host disconnects and another active
  player exists (see "Disconnect never deadlocks" above).

## `Room` API (backend/lan_playground/game.py)

```python
class Room:
    room_id: str
    seed: int
    phase: Literal["lobby", "choosing", "reveal", "finished"]
    hearts: int
    max_hearts: int
    host_id: str | None
    encounter_index: int

    def join(self, name: str) -> tuple[str, str]: ...          # (player_id, token)
    def disconnect(self, player_id: str, token: str) -> None: ...
    def reconnect(self, player_id: str, token: str) -> None: ...
    def verify_token(self, player_id: str, token: str) -> bool: ...

    def start(self, player_id: str, token: str) -> None: ...                    # host only
    def submit_choice(self, player_id: str, token: str, approach: str, move_text: str) -> None: ...
    def can_resolve(self) -> bool: ...
    def resolve(self, player_id: str, token: str) -> dict: ...                  # host only -> round_record
    def advance(self, player_id: str, token: str) -> None: ...                  # host only
    def replay(self, player_id: str, token: str, seed: int | None = None) -> None: ...  # host only

    def set_flavor(self, key: str, text: str) -> None: ...       # cosmetic overlay only
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

`RoomFullError`, `InvalidPhaseError`, `NotHostError`, `UnknownPlayerError`,
`InvalidTokenError`, `InactivePlayerError`, `AlreadySubmittedError`,
`NotAllSubmittedError`, `InvalidApproachError`. The transport layer maps
these to HTTP status codes (e.g. 409 for phase/already-submitted, 403 for
host/token errors, 404 for unknown player, 422 for invalid approach).

## `public_state(viewer_player_id=None)` shape

```jsonc
{
  "room_id": "room_AbC123",
  "phase": "choosing",
  "hearts": 2,
  "max_hearts": 3,
  "host_id": "p_xyz",
  "players": [
    {"player_id": "p_xyz", "name": "Roy", "is_host": true,  "active": true, "submitted": true},
    {"player_id": "p_abc", "name": "Dee", "is_host": false, "active": true, "submitted": false}
  ],
  "round_index": 2,
  "total_rounds": 5,
  "encounter": {"id": "suggestion_box_mimic", "name": "The Suggestion-Box Mimic", "flavor": "..."},
  "last_round": null,          // or the most recent round_record (see below)
  "history": [],               // all prior round_records, oldest first
  "finished_victory": null,    // true | false | null (still playing)
  "you": {                     // only present if viewer_player_id is a known player
    "player_id": "p_abc", "is_host": false, "active": true, "submitted": false
  }
}
```

No entry above ever contains a `token`. No entry for another player ever
contains their `approach` or `move_text` before that round's `resolve()`.

### `round_record` shape (returned by `resolve()`, also in `last_round`/`history`)

```jsonc
{
  "round": 2,
  "encounter": {"id": "suggestion_box_mimic", "name": "The Suggestion-Box Mimic", "flavor": "..."},
  "choices": [
    {"player_id": "p_xyz", "name": "Roy", "approach": "bonk", "move_text": "we stamp the box first"},
    {"player_id": "p_abc", "name": "Dee", "approach": "charm", "move_text": "we compliment its lovely teeth"}
  ],
  "successes": 1,
  "backfires": 1,
  "damage": 0,
  "hearts_before": 2,
  "hearts_after": 2
}
```

## Persona/LLM rewrite integration point

`game.py` never calls an LLM. The transport layer may run a persona rewrite
over an encounter's `flavor` or a player's `move_text` for display flavor,
then call:

```python
room.set_flavor(f"encounter:{encounter.id}", rewritten_encounter_blurb)
room.set_flavor(f"move:{player_id}:{room.encounter_index}", rewritten_move_line)
```

**Call `set_flavor()` before `resolve()`** for a given round if you want the
rewritten move text baked into that round's `round_record` -- `resolve()`
reads the overlay at reveal time. `set_flavor()` never touches `approach`
and cannot change `successes`/`backfires`/`damage`; if the LLM is offline or
`set_flavor()` is never called, every encounter/round renders its plain
canonical text and the game is identical in outcome.
