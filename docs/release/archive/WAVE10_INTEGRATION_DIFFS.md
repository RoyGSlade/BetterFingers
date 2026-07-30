# Wave 10 integration diffs — controller, Stream Deck, and the workflow run executor

Everything in Wave 10 is written and tested. This document lists the edits to
**integration-owned files** that Wave 10 did not make itself, in the order they
should be applied. Until they land, the Wave 10 modules exist and are covered by
their own suites, but the routes are not mounted and the controller loop does not
run — which is the intended degraded state, not a broken one: every surface
reports itself unavailable rather than pretending.

Integration-owned files touched here: `server.py` only.

Everything else in the list below (Electron main, preload, the renderer, the
route allowlist, `electron.vite.config.js`) **has already landed** and is
recorded here so the reviewer can see the whole chain in one place.

---

## D-1 — mount the input routes (`server.py`)

Beside the existing `app.include_router` lines at the end of `server.py`:

```python
from backend.api.routes import input_devices as input_devices_routes
app.include_router(input_devices_routes.router)
```

Without this, `/input/*` and `/stream-deck/*` 404. `features/gameSetupWizard.js`
then reports "Game setup is not reachable in this build" and the Stream Deck
plugin's keys show ALERT — both honest.

---

## D-2 — wire the dispatcher to the SAME contracts the keyboard uses (`server.py`)

This is the deliverable-1 requirement made concrete. Each handler below must be
the *same* function the corresponding HTTP route calls, not a private copy — the
whole point is that a controller press and a dashboard click are one code path.

```python
from backend.services.input_dispatch import InputActionDispatcher, InputActionHandlers

_INPUT_DISPATCHER = InputActionDispatcher(InputActionHandlers(
    # Capture. These are the functions POST /runtime/recording/* call.
    begin_dictation=start_recording_runtime,
    end_dictation=stop_recording_runtime,
    toggle_dictation=toggle_recording_runtime,
    # Command capture is SEPARATE from dictation (deliverable 1). Until a
    # dedicated command-capture entry point exists, leave these two unset:
    # the dispatcher then reports `unavailable`, the setup UI greys the action
    # out, and nothing silently starts a dictation when a user asked for a
    # command. See the OPEN ITEMS section.
    #   begin_command=...,
    #   end_command=...,
    cancel_capture=lambda: cancel_active_capture(),
    # The latest draft. Same helpers /voice-commands/execute reaches.
    read_latest=lambda: speak_text_aloud((latest_draft() or {}).get("final_text", "")),
    copy_latest=lambda: copy_text_to_clipboard((latest_draft() or {}).get("final_text", "")),
    inject_latest=lambda: deliver_latest_draft(),
    # Settings the user could have flipped in the app anyway.
    activate_application_profile=lambda pid: app_context_service().set_override(pid),
    # The panic button. The SAME function POST /runtime/emergency-stop calls.
    emergency_stop=emergency_stop_runtime,
    # Workflows are NOT run here. This asks the renderer to take the Wave 9
    # approval path; the Electron main process does the running. See D-4.
    request_workflow=lambda wid: broadcast_status_threadsafe(
        "workflow_requested", {"workflow_id": wid},
    ),
))
input_devices_routes.set_dispatcher(_INPUT_DISPATCHER)
```

`activate_persona` and `activate_writing_preset` are deliberately absent — see
OPEN ITEMS.

**Why lambdas rather than direct references for some of these:** the runtime
helpers take arguments the dispatcher does not have (a draft id, a text body).
The lambda supplies the "latest" part and nothing else; if it ever grows a
decision, that decision belongs in the runtime function where the dashboard path
would see it too.

---

## D-3 — run the controller loop (`server.py`)

```python
from backend.services.controller_engine import ControllerEngine, PygameEventSource
from backend.stores.controller_bindings import ControllerBindingStore

_CONTROLLER_STORE = ControllerBindingStore()

def _resolve_controller_bindings(device_key):
    # The application-profile layer is read live, so switching profile mid-game
    # takes effect on the next press with nobody rebuilding the engine.
    profile_id = app_context_service().current().get("profile_id", "")
    profile = AppProfileStore().get(profile_id) or {}
    return _CONTROLLER_STORE.resolve(device_key, profile.get("bindings"))

_CONTROLLER_ENGINE = ControllerEngine(
    _INPUT_DISPATCHER.dispatch,
    _resolve_controller_bindings,
    debounce_ms=_CONTROLLER_STORE.read()["debounce_ms"],
)
input_devices_routes.set_capture_source(_CONTROLLER_ENGINE)
```

and a poll loop on the existing input thread (`hotkey_manager` already owns one):

```python
source = PygameEventSource(_CONTROLLER_ENGINE, pygame_module=_pygame_or_none())
source.refresh_devices()
while running:
    for event in pygame.event.get():
        source.handle(event)
    _CONTROLLER_ENGINE.tick()      # fires deferred presses
    time.sleep(0.005)
```

`_pygame_or_none()` must return `None` when pygame has no joystick support
compiled in. `PygameEventSource.available` is then `False` and every method is a
no-op — the engine stays importable and the routes stay honest.

On shutdown, call `_CONTROLLER_ENGINE.release_all_devices(reason="shutdown")`.
It dispatches release halves through the ordinary dispatcher, which is how the
Wave 8 privacy lease and the audio broker get released (D-0026). **Do not add a
second release path.**

---

## D-4 — the workflow request → execute hop (renderer; LANDED)

`request_workflow` broadcasts `workflow_requested` with a workflow id. The
renderer's status listener turns that into:

```js
window.betterFingers.workflows.execute(workflowId)
```

which is the one typed channel. The main process re-fetches, re-validates through
`POST /workflows/run`, executes the approved steps and files the per-step codes.
A controller press, a Stream Deck press and the Run button in the workflow
builder all arrive at the same place.

**Status: the channel, the executor and the builder's Run button are landed and
tested.** The status-listener line that turns a `workflow_requested` broadcast
into an `execute` call is the only part still to write, and it depends on D-2's
broadcast existing.

---

## Already landed (recorded for the reviewer)

| File | Change |
|---|---|
| `app/src/main/workflowExecutor.js` | **new** — the run executor; the only caller of the launcher |
| `app/src/main/ipc.js` | one channel, `workflows:execute`, through `handleTrusted`; constructs the executor |
| `app/src/preload/preload.js` | `workflows.execute(workflowId)` |
| `app/electron.vite.config.js` | `workflowExecutor` added to main inputs (enforced by `viteMainInputs.test.mjs`) |
| `app/src/main/backendProxy.js` | `/input/*`, `/stream-deck/*` and `/app-context/profiles` allowlist entries |
| `app/src/renderer/api/backend.js` | `executeWorkflow`, `saveAppProfile`, the `/input/*` and `/stream-deck/*` adapters |
| `app/src/renderer/features/workflowBuilder.js` | Run now goes through the executor and reports what actually happened |
| `app/src/renderer/features/gameSetupWizard.js` | **new** — the seven-step wizard |
| `app/src/renderer/bootstrap/signalDeskApp.js` | mounts the wizard |
| `backend/api/routes/app_context.py` | `POST /app-context/profiles` (Wave 7 shipped reads only) |
| `backend/stores/app_profiles.py` | `BINDING_SLOTS` widened to the shared action ids; `record_toggle` migrates to `dictation.toggle` |
| `integrations/streamdeck/` | **new** — the plugin, its manifest, its property inspector, its qualification doc |

---

## OPEN ITEMS — landed vs designed

Stated plainly, because a wave that reports itself complete while three actions
report `unavailable` is the kind of claim this release exists to stop making.

### 1. Command capture has no backend entry point yet — DESIGNED, NOT LANDED

`command.begin` / `command.end` are first-class action ids, bindable, separately
bound, and covered by tests. What does not exist is a runtime function that
starts a capture whose transcript is routed to `voice_commands.parse_command`
rather than to the dictation pipeline. Today the closest thing is
`POST /voice-commands/execute`, which takes text that has *already* been
transcribed.

Until that function exists, D-2 leaves `begin_command`/`end_command` unset and
the dispatcher reports `unavailable`. That is visible to the user: the setup
wizard greys the action out and the Stream Deck key shows ALERT.

**This is the one deliverable-1 item that is not fully landed.** Everything
around it is — the separate binding, the separate id, the refusal to let one
button mean both — but pressing the command button on a real controller today
reports "BetterFingers cannot do that yet" rather than starting a command
capture.

### 2. `activate_persona` / `activate_writing_preset` — DESIGNED, NOT LANDED

Same shape, smaller. There is no activation *route* for either: selecting a
persona is a settings write the dashboard performs directly. The action ids
exist, the Stream Deck keys exist, the parameter validation exists, and the
handlers are unset, so both report `unavailable`. The executor has the same gap
for the matching workflow verbs (`workflowExecutor.js`'s `applySetting`).

### 3. Stream Deck is UNQUALIFIED — no hardware

No Stream Deck exists on any machine this project has touched. The plugin, the
protocol, the action mapping, the hold/release pairing and the disconnect
release are covered by tests against a fake WebSocket; none of that is evidence
that a physical deck works. The status is carried in
`stream_deck_config.qualification()`, served at `GET /stream-deck/qualification`,
and the 16-step manual pass is in `integrations/streamdeck/QUALIFICATION.md`.

No icons ship. The manifest names `images/*` files this repository does not
contain, and step 1 of the manual pass exists to discover that.

### 4. Controller hardware is UNQUALIFIED — no device

Same honesty. Every timing property (bounce, chord, sequence, pre-emption,
device loss, reconnect) is tested to the millisecond with pygame fully mocked,
which proves the logic and proves nothing about a driver. A live test on the
director's hardware is the outstanding item; `PygameEventSource` is the only
code a real device touches, and it is thirty lines of translation.

### 5. `latest.inject` depends on a `deliver_latest_draft` that D-2 assumes

D-2's `inject_latest` lambda names a helper that the integrator must point at
whatever the dashboard's "type this draft" path already calls. If no single
function exists, leave `inject_latest` unset rather than assembling one here —
an inject path that only the controller uses is exactly the second
implementation this wave's design exists to prevent.
