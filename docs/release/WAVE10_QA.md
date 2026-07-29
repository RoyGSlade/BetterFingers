# Wave 10 QA — what is proven, how, and what is not

Gate 10 is "controller and Stream Deck are first-class input paths". The honest
reading of that on this hardware is: **the logic is qualified, the devices are
not.** No controller and no Stream Deck exist on any machine this project has
been developed or tested on. This document says which is which, per property,
so nobody has to infer it from a green suite.

## How to run everything in this wave

```bash
# Backend — binding resolution, timing, dispatch, stores, routes
.venv/bin/python -m pytest -q \
  tests/test_input_actions.py \
  tests/test_input_dispatch.py \
  tests/test_controller_bindings.py \
  tests/test_controller_engine.py \
  tests/test_stream_deck_config.py \
  tests/test_input_device_routes.py \
  tests/test_app_profiles_store.py

# Electron main + renderer — the executor, the plugin protocol, the wizard
cd app && npm run test:unit

# Renderer QA on the PRODUCTION composition root (needs a build)
cd app && BF_QA_UI=signal-desk-prod node tests/qa/run.mjs wave10-input
cd app && BF_QA_UI=signal-desk-prod node tests/qa/run.mjs wave9-actions
```

`wave9-actions` is in the list because Wave 10 changed how the workflow builder
runs a workflow: it now goes through the main-process executor rather than
calling `POST /workflows/run` itself, and the stub grew a
`POST /workflows/run/record` route to match.

---

## Deliverable by deliverable

### 1. Required actions through the same internal contracts

| Property | Proven by | Status |
|---|---|---|
| Every required action id exists and is bindable | `test_input_actions.py` | **qualified** |
| Dictation and command capture are separate bindings | `test_input_actions.py`, `test_controller_bindings.py::test_coverage_*`, wizard `canRecordCommand` gate | **qualified** |
| Each id reaches exactly one existing contract | `test_input_dispatch.py::test_every_required_action_reaches_its_contract` | **qualified (logic)** — the *binding* of handlers to `server.py`'s runtime functions is integration-owned; see WAVE10_INTEGRATION_DIFFS.md D-2 |
| An unwired action reports `unavailable`, not silent success | `test_input_dispatch.py` | **qualified** |
| Release halves cannot be bound directly | `test_input_actions.py`, `test_controller_bindings.py` | **qualified** |

**Not landed:** `command.begin`/`command.end` and the two settings-activation
actions have no backend handler to bind to yet. They report `unavailable`. See
WAVE10_INTEGRATION_DIFFS.md OPEN ITEMS 1 and 2.

### 2. Per-application bindings

| Property | Proven by | Status |
|---|---|---|
| Three layers fold most-specific-first, PER ACTION | `test_controller_bindings.py::test_layers_fold_per_action_not_per_layer` | **qualified** |
| A game profile rebinding one action cannot unbind the panic button | same | **qualified** |
| The application layer uses Wave 7's reserved slot, not a second table | `test_app_profiles_store.py::test_the_per_application_layer_speaks_the_shared_action_vocabulary` | **qualified** |
| A Wave 7 `record_toggle` migrates rather than being dropped | `test_app_profiles_store.py` | **qualified** |
| The device layer survives switching profile | `test_controller_bindings.py::test_device_layer_only_applies_to_that_device` | **qualified** |

### 3. Game setup wizard

| Property | Proven by | Status |
|---|---|---|
| Seven steps, each gated on the previous | `gameSetupWizard.test.mjs`, QA `the-wizard-starts-at-detect-...` | **qualified** |
| No controller found says what to do | QA `no-controller-found-says-what-to-do` | **qualified** |
| Recording a binding waits for release, so a chord records as a chord | `test_controller_engine.py::test_capture_records_a_chord_as_a_chord` | **qualified** |
| Capture swallows even the emergency stop while listening | `test_controller_engine.py` | **qualified** |
| The anti-cheat warning cannot be skipped on the way to the risky mode | `gameSetupWizard.test.mjs`, QA `typing-into-a-game-requires-...` | **qualified** |
| Changing mode retracts the acknowledgement | `gameSetupWizard.test.mjs` | **qualified** |
| **The test step can never fire a real send** | `test_input_dispatch.py::test_the_rehearsal_dispatcher_can_never_fire_anything` (parametrised over EVERY id), `gameSetupWizard.test.mjs`, QA `the-test-step-cannot-send-anything` | **qualified** |
| Save is dead until the test has run | `gameSetupWizard.test.mjs`, QA `save-is-dead-until-the-test-has-run` | **qualified** |

**How the rehearsal guarantee is enforced**, since it is the one the wave calls
out. Three independent mechanisms, because one is a promise:

1. The route answers a rehearsal press with `rehearsal_dispatcher()` — an
   `InputActionDispatcher` constructed with an **empty handler table**. There is
   no callable to reach, so there is no flag a later edit could invert. Asserted
   over every id in the vocabulary, including `emergency.stop`.
2. The wizard will not transmit `latest.inject` or `emergency.stop` at all.
3. The state machine cannot reach `saved` without the rehearsal, and cannot
   reach the rehearsal without the warning.

### 4. Stream Deck

| Property | Proven by | Status |
|---|---|---|
| Manifest actions == the bindable BetterFingers ids, both directions | `test_stream_deck_config.py::test_the_manifest_declares_exactly_our_actions` + `streamDeckProtocol.test.mjs` | **qualified** |
| A key's action comes from the plugin UUID, never from settings | both suites | **qualified** |
| The plugin owns no workflow definitions and cannot describe work | `streamDeckProtocol.test.mjs::the plugin can only send ids...` | **qualified** |
| Hold pairs: begin on keyDown, end on keyUp | `streamDeckProtocol.test.mjs` | **qualified (protocol)** |
| A disconnect releases held state through the shared path | `streamDeckProtocol.test.mjs`, `test_input_device_routes.py::test_a_deck_disconnect_releases_only_what_that_deck_held` | **qualified (protocol)** |
| Pairing stores a fingerprint, never the token | `test_stream_deck_config.py` | **qualified** |
| **A physical Stream Deck works** | nothing | **NOT QUALIFIED — no hardware** |

The 16-step manual pass is `integrations/streamdeck/QUALIFICATION.md`. No icons
ship; the manifest names image files this repository does not contain, and step 1
of that pass exists to find out.

### 5. Reliability

| Property | Proven by | Status |
|---|---|---|
| Debounce drops a bounce, keeps a deliberate second press | `test_controller_engine.py` (3 tests) | **qualified (logic)** |
| Debounce is per-token, so a chord is never mistaken for a bounce | same | **qualified (logic)** |
| Chord fires once per press, re-arms on release | same | **qualified (logic)** |
| Sequence fires inside its window, resets outside it | same | **qualified (logic)** |
| A longer binding pre-empts the shorter one inside it | same | **qualified (logic)** |
| An ordinary single button keeps zero latency | same | **qualified (logic)** |
| Emergency stop is never deferred | same | **qualified (logic)** |
| Axis hysteresis stops chatter at the threshold | same | **qualified (logic)** |
| Device loss releases held state through the SAME dispatcher | `test_controller_engine.py`, `test_input_dispatch.py::test_release_device_goes_through_dispatch_not_a_side_channel` | **qualified (logic)** |
| A release only affects the device that vanished | `test_input_dispatch.py::test_release_device_releases_only_that_device` | **qualified (logic)** |
| Reconnect keeps the same bindings (key from name, not instance id) | `test_controller_engine.py` (2 tests) | **qualified (logic)** |
| Emergency stop works from every supported device kind | `test_input_dispatch.py`, parametrised over `DEVICE_KINDS`, with everything else switched off | **qualified (logic)** |
| **Any of the above on a real controller** | nothing | **NOT QUALIFIED — no hardware** |

"Qualified (logic)" means: proven to the millisecond with pygame fully mocked
and a clock the test controls. That is a stronger statement about the algorithm
than a hardware run would be, and a weaker one about the product. Both are true.

### 6. Stores

| Property | Proven by | Status |
|---|---|---|
| Both stores live under the unified root, one file each | `test_controller_bindings.py`, `test_stream_deck_config.py` | **qualified** |
| A corrupt file degrades to "no bindings" rather than taking input down | both | **qualified** |
| `clear_all` removes the device fingerprint and the typed titles | both | **qualified** |
| Both declared to `data_categories` | Wave 6 (sup-privacy), personal tier, `in_export`; `user_text` differs per store — see note | **qualified — coordinated, see note** |

Note: `data_categories.py` and `data_paths.py` are Wave 6's. The two ids
(`controller_bindings`, `stream_deck_config`) were specified by this wave and
declared by Wave 6, including their `.bak-v<N>`/`.corrupt` migration siblings,
which `store_migration` writes beside every versioned store and which nothing was
previously declaring.

**The two stores differ on `may_contain_user_text`, and the difference is
deliberate:**

* `controller_bindings` is `user_text=False`. Every field is a closed enum, a
  token/timing document, or a `normalize_param()`-bounded id. The persona and
  preset *names* a binding can reference are declared under their own
  categories, not this one.
* `stream_deck_config` is `user_text=True`, on Wave 6's rule that **any string
  the user typed with their own hands sets the flag**, regardless of length bound
  or field intent. The store holds a Stream Deck **key title** — 80 chars,
  nominally a label — but a deck full of keys titled after the people they
  message is a human-readable record of something the user wrote. Wave 10 raised
  the nuance and flagged it as `False`; Wave 6 owns the registry and ruled
  `True`. That ruling is the right one: the flag means "a human reading this file
  learns something the user wrote", not "this field holds prose".

### 7 / D-0027. The workflow run executor

| Property | Proven by | Status |
|---|---|---|
| The channel takes a workflow id and nothing else | `workflowExecutor.test.mjs` (3 tests, incl. a source-level assertion on the destructure) | **qualified** |
| The gate is consulted on EVERY run | `workflowExecutor.test.mjs` | **qualified** |
| No step runs on a refusal, a validation failure, a 404, or an unreachable backend | 4 tests | **qualified** |
| The executor is the only caller of the launcher | `workflowExecutor.test.mjs` — walks `src/main/*.js` | **qualified** |
| The channel is registered through `handleTrusted` | source assertion | **qualified** |
| No bare launch IPC exists | same walk + a check that `ipc.js` never calls `launcher.launch/focus/open` | **qualified** |
| Per-step codes are recorded, and nothing else is | `workflowExecutor.test.mjs` | **qualified** |
| Two presses do not run it twice | `workflowExecutor.test.mjs` | **qualified** |
| A partial run is never described as finished | `workflowBuilder.test.mjs` | **qualified** |
| An unimplemented verb is `refused`, not skipped | `workflowExecutor.test.mjs` | **qualified** |
| **A real application launches** | nothing in this wave | **NOT QUALIFIED** — the launcher itself is Wave 9's and carries its own status; the executor is tested against a fake spawn |

---

## Negative results worth recording

* **`DEFAULT_CHORD_WINDOW_MS` was dead code.** `_live_longer_windows` read the
  binding's `sequence_window_ms`, which `InputBinding` always populates (default
  400), so a chord deferred an ordinary single press by 400ms — unusable input
  lag in a game, for a chord the user may not even have been attempting. Chords
  now defer by 120ms; sequences still use the window the user chose.
  (`test_a_deferred_single_fires_when_the_longer_binding_does_not_arrive`.)

* **A binding row with no button silently claimed button 4.**
  `InputBinding.from_dict(None)` returns a binding on `button:4`, which is a
  sensible Wave 2 default and a dangerous one here: a profile row that merely
  named an action would take the user's button 4, and a Stream Deck row — which
  has no controller tokens at all — would grow a phantom gamepad binding. Such a
  row is now refused with a reason.
  (`test_a_binding_without_an_input_is_refused_not_defaulted`.)

* **The Stream Deck store could not read its own output.** `sanitize_device`
  read the grid from `payload["size"]` (the Stream Deck's shape) while the stored
  row keeps it flat, so a reload zeroed `columns`/`rows`; same for `device` vs
  `device_id` on a key. Both sanitisers now accept either shape, asserted by
  round-trip tests.

* **Wave 9's Run button told the truth about the gate and a lie about the run.**
  It said "Running the steps in the order shown above" while nothing in the
  product could perform a step. That message is now derived from the executor's
  summary and says "Partly done — 2 of 3 steps" when that is what happened.

---

## What a hardware pass would add

For the director's live run, in priority order. These are the assertions that no
amount of mocking can make:

1. Hold the dictation button, speak, release — recording starts and ends with the
   button.
2. **Unplug the controller mid-sentence.** The recording must end, the microphone
   must be released, and the audio indicator must return to idle. This is the
   D-0026 path; a mocked test proves the dispatch happens, not that the lease
   actually let go.
3. Plug it back in — the same bindings apply, without restarting the app.
4. Press the emergency stop while a recording is running, with the controller
   adapter switched off in settings. It must still work.
5. Press a bound chord ten times. Count the dispatches: ten, not eleven.
6. Press a single button bound alongside a chord that includes it. It must feel
   immediate, not laggy.
