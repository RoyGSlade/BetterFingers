# LAN Playground: Spellcheck & Sorcery (boards #33, #40)

This tool started as a small persona-rewrite demo (board #33) and was
evolved into a hardened, ephemeral 1-4 player LAN party game host (board
#40): **Spellcheck & Sorcery**. A friend opens a link or scans a QR code on
your home network, joins your room, and plays a short humor-forward co-op
adventure -- BetterFingers' local model quietly polishes each player's move
text for flavor, with a deterministic fallback if it's unavailable, so the
game is never blocked on it. Game rules, the full state machine, and the
`Room`/`GameRegistry` engine contract live in `docs/LAN_GAME_SPEC.md`; this
document covers running the server, the security model, and the HTTP room
API.

The `/api/rewrite`, `/api/personas`, etc. persona-playground endpoints from
board #33 still exist underneath (the game reuses the same LLM/persona
wiring), but the served page (`index.html`/`app.js`/`style.css`) is now the
game client, not the old rewrite-comparison UI.

**What this is not**: no microphone, no text-to-speech, no audio of any
kind. Nothing is saved -- there's no history, no localStorage, and no
request content, move text, or model output is ever logged. It never
exposes anything to the public internet by itself, and it never opens a
firewall or router port for you.

## Prerequisites

- BetterFingers' Python environment set up (same venv used for `server.py`
  and the test suite).
- The local LLM sidecar reachable (normally started by `server.py` /
  `llm_engine.py` as usual). If it isn't running, the playground still
  starts and serves the page -- rewrite requests just come back with a
  "model not available" message instead of hanging.

## Quick start (same machine only)

```bash
python3 tools/lan_playground.py
```

This binds to `127.0.0.1` only -- nothing outside this machine can reach
it. It prints a URL with a one-time access code baked in, e.g.:

```
BetterFingers LAN Playground -- Spellcheck & Sorcery
  bind:         127.0.0.1:8850
  open:         http://127.0.0.1:8850/?code=AbCdEf...
  access code:  AbCdEf...
```

Open that URL in a browser on the same machine.

## Playing with friends (QR join)

Once you're on `--lan` (below) and have created a room in the browser, the
lobby screen shows a QR code alongside the room code and link. It's
generated entirely locally -- no internet service, no external QR API --
by `backend/lan_playground/qr.py`, which renders a scannable SVG from a
vendored, dependency-free QR matrix encoder (see
`backend/lan_playground/_vendor/qrenc/NOTICE.md`). Scanning it opens the
join page with the LAN address, room code, and access code pre-filled via
the URL; the page reads those query parameters once and immediately strips
them from the visible address bar so they don't linger in browser history.

## Sharing it with friends on your home network

Pass `--lan` explicitly -- it is off by default and required for any
non-loopback bind:

```bash
python3 tools/lan_playground.py --lan
```

The tool detects this machine's private-network address(es) and prints a
ready-to-share link per address, plus the access code:

```
BetterFingers LAN Playground -- Spellcheck & Sorcery
  bind:         0.0.0.0:8850
  open:         http://192.168.1.42:8850/?code=AbCdEf...
  access code:  AbCdEf...
```

Send that link (or the address + access code) only to people on your own
home network. Anyone with the link and code can use the playground while
the process is running; there is no way to revoke a single guest's access
short of restarting with a new code.

**Windows** (same commands, from an Anaconda/venv prompt or PowerShell):

```powershell
python tools\lan_playground.py
python tools\lan_playground.py --lan
```

### Firewall

`--lan` only changes what this process listens on -- it does **not** touch
your OS firewall or router. If friends still can't connect, you may need to
allow inbound connections to the chosen port (default `8850`) for `python`
on your LAN-facing network profile. This tool will never do that for you
automatically.

## Stopping it

Press `Ctrl+C` in the terminal running the tool (works the same on Linux,
macOS, and Windows). It shuts down immediately; nothing persists between
runs.

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. Only loopback values work without `--lan`. |
| `--lan` | off | Opt in to binding `0.0.0.0` so LAN devices can connect. |
| `--port` | `8850` | Port to listen on. |
| `--access-code` | generated | Use a specific code instead of a random one. Also settable via `BETTERFINGERS_LAN_ACCESS_CODE`. |
| `--generate-timeout` | `75` | Seconds to wait for a rewrite before giving up. |
| `--max-concurrency` | `2` | Max rewrites processed at once (protects the local model from pile-ups). |
| `--rate-limit-per-min` | `12` | Max rewrite requests per client per minute. |

## How the page works

- **Create or join**: the host creates a room and shares its QR/link; up to
  three friends join from their phones or computers.
- **Play**: each hero secretly picks Charm, Scheme, or Bonk and types one
  short move. The deterministic game engine scores the card; BetterFingers
  only rewrites the sentence into persona-flavored narration.
- **Reveal**: after every active player submits, the cards and funny lines
  reveal together. A resistant choice costs the shared party one heart.
- **Adventure**: survive five shuffled communication monsters to win. The
  host advances rounds and can replay from the finale.
- **Fallback**: if the local model is unavailable or misses its eight-second
  flavor budget, the original move appears immediately and play continues.
- **Art**: the bundled storybook key art, fantasy map, move cards, and ending
  tableaux are served from a fixed filename allowlist and cached by each
  browser; the source art directory is never exposed as a static mount.

The access code is entered once per page load (or supplied via the `?code=`
link) and kept only in the page's in-memory JavaScript state -- it's never
written to localStorage, sessionStorage, cookies, or browser history.

## Security model (what's actually enforced)

- **Bind**: loopback by default; `--lan` is required for any other bind, and
  a non-loopback bind always requires an access code (generated if you
  don't supply one) -- reuses the same fail-closed policy `server.py` uses
  for its own startup (`server_security.validate_startup_security`).
- **Access code**: every `/api/*` call must present the code via the
  `X-Access-Code` header, checked with a constant-time comparison. The
  static page shell itself needs no code (it's just the empty UI).
- **Host/Origin checks**: requests with an unrecognized `Host` header, or a
  present `Origin` header that isn't one of this server's own bound
  addresses, are rejected before reaching any route.
- **CSRF**: there is no cookie-based auth and no CORS allow-list, so a
  cross-origin page cannot attach the required `X-Access-Code` header to a
  request the browser will actually deliver here.
- **Rate limit & concurrency**: each client IP is capped per minute
  (`--rate-limit-per-min`), and only a small number of rewrites run at once
  (`--max-concurrency`) -- both return `429` when exceeded.
- **Size limits**: input text, custom instructions, and persona names are
  all bounded; oversize requests are rejected with `422` before anything
  reaches the model.
- **Timeouts**: a rewrite that takes too long returns a `timeout` status
  instead of hanging.
- **No logging, no persistence**: the code that handles requests never
  imports `logging`; no request text, persona prompt, or model output is
  written to disk, a database, or any log. There is no results-polling
  endpoint -- each response is returned once and then forgotten.
- **No directory browsing**: the three static assets (`index.html`,
  `app.js`, `style.css`) are served by fixed, explicit routes, not a
  directory listing.

### Room API (`/api/game/*`, board #40)

Every game route sits behind the same site-wide `X-Access-Code` +
Host/Origin policy above -- room/player tokens are a *second*, per-room
layer on top, not a replacement:

- **Two-layer secrets**: the site-wide access code gates the whole app
  (as above); a short 8-character room code (`backend.lan_playground.rooms`,
  never the game engine's own long internal id) additionally gates which
  room a guest can join.
- **Per-player tokens, not slots**: `POST /api/game/rooms` and `.../join`
  each mint one high-entropy, secret token for the calling player
  (`X-Host-Token` / `X-Player-Token` on every later request). Tokens are
  looked up and checked with constant-time comparison
  (`backend.lan_playground.security.constant_time_equals`), and the engine
  (`game.py`) re-validates the token on every mutating call itself -- there
  is no "the transport layer already checked this" shortcut.
- **Host/player gating**: `start`/`advance`/`replay` require the caller's
  own token to belong to the room's *current* host (host succession-safe);
  `moves` requires any valid active player's token. Wrong caller -> `403`;
  bad/missing token -> `401`.
- **Bounded fields, capped rooms**: display names and move text are
  length-bounded (`422` if oversized/empty); room creation and join are
  separately rate-limited per client IP; a hard cap on concurrently live
  rooms returns `503` rather than growing memory unboundedly.
- **Idle-room expiry**: `backend.lan_playground.rooms.RoomManager` prunes
  rooms with no activity for 45 minutes (default) -- the pure game engine
  itself has no wall-clock concept, so this lives entirely in the
  transport layer.
- **Persona rewrite never blocks the game**: submitting a move kicks off a
  background, bounded-timeout text "polish" pass
  (`backend.lan_playground.rooms.MovePolisher`) using the same
  local-model plumbing as `/api/rewrite`. If the model is offline, errors,
  or simply hasn't finished by the time the round auto-resolves (once every
  active player has submitted), the round reveals each player's original
  raw move text instead -- the game's actual outcome (`successes` /
  `backfires` / `damage`) only ever depends on the fixed `approach` field
  a player chose, never on any text, polished or raw.

## What it reuses (no core logic duplicated)

- `backend.services.message_rescue.rescue_message` -- the same
  preservation-checked rewrite engine used by the desktop app's Message
  Rescue feature.
- `backend.services.rescue_llm_adapter.build_llm_call_fn` -- the same local
  LLM call adapter, talking to the same llama-server sidecar.
- `backend.services.personas.get_persona` / `list_builtin_persona_names` --
  the same persona store, restricted to built-ins for LAN guests.
- `server_security.validate_startup_security` -- the same loopback/opt-in
  policy `server.py` itself uses.

None of `server.py`, `utils.py`, or the Electron renderer are modified by
this feature.

## Running the tests

```bash
python3 -m pytest -q \
  tests/test_lan_playground_security.py tests/test_lan_playground_app.py tests/test_lan_playground_smoke.py \
  tests/test_lan_playground_qr.py tests/test_lan_playground_rooms.py tests/test_lan_game_api.py \
  tests/test_lan_game_engine.py tests/test_lan_game_static.py
```

All of these are model-free (fakes stand in for the persona store, LLM
call, and game engine wiring) except the smoke test, which opens a real
loopback socket but still never touches the real model or `server.py`.
