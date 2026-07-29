# Stream Deck qualification — NOT QUALIFIED

**Status: unqualified. No Stream Deck hardware exists on any machine this
project has been developed or tested on.**

That sentence is the whole point of this file. The plugin code is real, the
protocol is covered by tests, and the BetterFingers side is covered by tests —
and none of that is evidence that a physical Stream Deck works, because nobody
has pressed one. This project's standing rule is that an unverified capability
says so, in the code (`stream_deck_config.qualification()`), in the UI (the
`GET /stream-deck/qualification` route), and here.

## What IS proven

| Property | Where |
|---|---|
| Every plugin action UUID maps to a real BetterFingers action id, and only to a bindable one | `tests/test_stream_deck_config.py`, `app/tests/streamDeckProtocol.test.mjs` |
| The manifest's action list and the Python namespace cannot drift apart | `tests/test_stream_deck_config.py::test_the_manifest_declares_exactly_our_actions` |
| A key press produces exactly one dispatch, with the action id read from the action UUID and not from settings | `app/tests/streamDeckProtocol.test.mjs` |
| A holdable key sends begin on keyDown and end on keyUp | same |
| A disconnect releases held state through BetterFingers' single release path | same, plus `tests/test_input_device_routes.py` |
| A key whose action belongs to another plugin is refused | both |
| The plugin holds no workflow definitions and cannot describe work | `app/tests/streamDeckProtocol.test.mjs::the plugin can only send ids...` |
| Pairing stores a fingerprint, never the token | `tests/test_stream_deck_config.py` |

## What is NOT proven

Everything that requires a device: that the Stream Deck software loads the
manifest at all, that the icons resolve, that `willAppear` arrives with the
coordinates shape assumed here, that the property inspector renders correctly in
the Stream Deck's embedded browser, that `showAlert`/`showOk` are visible enough
to be useful feedback, and that any of it survives a real unplug.

## Manual qualification steps

Run these on a machine with a Stream Deck. Record the result of every step;
a single failure means the status above stays as it is.

**Setup**

1. Build the icon set into `integrations/streamdeck/images/` (the manifest names
   `plugin`, `category`, and one per action). *Not shipped: this repository has
   no artwork for them, and shipping a manifest that points at missing images is
   one of the things this pass has to find out.*
2. Copy `integrations/streamdeck/` to
   `~/.local/share/elgato/StreamDeck/Plugins/com.betterfingers.streamdeck.sdPlugin/`
   (Linux) or the platform equivalent, and restart the Stream Deck software.
3. Start BetterFingers. Open Settings → Devices → Stream Deck and copy the
   pairing code.

**Qualification checks**

| # | Step | Expected |
|---|---|---|
| 1 | The BetterFingers category appears in the Stream Deck action list | 12 actions, each with its icon |
| 2 | Drag "Emergency stop" onto a key | BetterFingers' Stream Deck panel shows one mirrored key within a second |
| 3 | Open the key's property inspector, paste the pairing code | BetterFingers shows *paired* |
| 4 | Press the emergency-stop key while idle | key shows OK; BetterFingers logs `emergency.stop` |
| 5 | Start a recording from the dashboard, then press the emergency-stop key | recording ends |
| 6 | Switch the Stream Deck adapter OFF in BetterFingers, press an ordinary key | key shows ALERT, nothing happens |
| 7 | With the adapter still off, press the emergency-stop key | it still works — this is the one that must not regress |
| 8 | Bind "Hold to dictate", hold the key and speak, release | recording starts on press and ends on release |
| 9 | Hold the dictate key and **unplug the Stream Deck** mid-sentence | recording ends; the microphone is released; BetterFingers' audio indicator returns to idle |
| 10 | Plug the deck back in | keys reappear and work; BetterFingers shows the device connected again |
| 11 | Bind "Switch persona" with no persona chosen, press it | key shows ALERT; BetterFingers reports `needs_param` |
| 12 | Bind "Run a saved workflow" to a workflow that is saved but **not approved** | key shows ALERT; nothing launches |
| 13 | Approve that workflow in BetterFingers, press the key again | the workflow runs; the run history shows per-step codes |
| 14 | Delete the application the workflow launches, press the key again | key shows ALERT; nothing launches |
| 15 | Quit BetterFingers, press any key | key shows ALERT; the Stream Deck software does not hang or crash |
| 16 | Remove a key from the deck | BetterFingers' mirror drops that key |

**After a passing run**, update `QUALIFICATION_REASON` in
`backend/stores/stream_deck_config.py` and this file with the date, the deck
model, and the operating system — and only then. A partial pass is not a pass.
