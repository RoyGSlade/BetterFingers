# Wave 8A wiring — what landed, and the exact diffs for integration-owned files

Wave 8A is the first half of Gate 8: the audio settings split (D-0010) and the
single microphone owner (D-0013). Capture isolation (packages C/D) is the next
objective and depends on this landing.

This document is the contract between this wave and the integrator. Section 1
lists what is already in the tree and tested. Section 2 gives the exact,
line-level changes for the files this wave did **not** touch because another
lane owns them.

---

## 1. Landed and tested

### New modules

| Module | Package | What it owns |
|---|---|---|
| `audio_schema.py` | A | The `output_ducking` / `voice_privacy` blocks, their sanitizers, the one-shot forward migration from the legacy flat keys, and the legacy-key projection that keeps unported consumers working. |
| `audio_input_broker.py` | B | `AudioInputBroker` — one process-wide owner of the microphone, with subscriber registration, device-change handling, and explicit release-on-last-unsubscribe. |
| `wake_pretrigger.py` | F | `PreTriggerRing` (bounded in-memory pre-trigger audio, never persisted), `WakeHandoff`, and `build_command_capture_detector()` reusing the existing `audio_gate.TrailingSilenceDetector`. |
| `audio_status.py` | H | The capability and runtime-status vocabularies for voice privacy and wake, including `partially_restored` and `classifier_missing`. |

### Modified in place

| File | Package | Change |
|---|---|---|
| `recorder.py` | A, B | Subscribes to the broker instead of opening `sd.InputStream`; reads ducking through `audio_schema.output_ducking_of()`. |
| `wake_word.py` | B | `WakeListener` subscribes to the broker instead of opening its own stream. Its public API (`start`/`stop`/`is_listening`/`status`) is unchanged, so `routes_wake.py` needs no edit. |
| `injector.py` | E | Push-to-mute is driven by `voice_privacy.mode` via `audio_schema.effective_privacy_mode()` instead of the ambiguous `audio_ducking` flag. Behavior for every existing profile is unchanged. |

### Documentation

`docs/release/WAKE_MODEL_PROVENANCE.md` + `wake_model_provenance.json`
(package G), guarded by `tests/test_wake_model_provenance.py`.

### Behavior notes for the reviewer

- **The recorder now ignores chunks that arrive when it is not recording.**
  With a shared stream this matters: audio can be flowing for the wake
  listener while no recording is active, and appending it would silently
  extend the next clip.
- **`sd.InputStream` stream-status warnings moved** from `recorder.py`
  (`logging.warning`) to the broker (`logging.debug`). One stream, one place
  that reports over/underruns.
- **Device-contention policy.** The broker holds one device. `device=None`
  means "no preference" and never disturbs an open stream; an explicit
  preference that differs from the open device reopens for every subscriber.
  A failed switch restores the previously working device rather than leaving
  everyone stranded, and still reports the failure through `status()`.

---

## 2. Documented diffs — files this wave did not edit

### 2.1 `utils.py` (owned by the profile/settings lane)

Four changes. All are additive; none removes a legacy key, which is what keeps
old profiles loading with unchanged semantics.

**(a) Import** — near the existing imports:

```python
import audio_schema
```

**(b) `_profile_defaults()`** — beside the existing `audio_ducking` defaults
(~line 815). Keep the legacy keys: they are still written by
`project_legacy_audio_keys()` and still read by unported consumers.

```python
        "audio_ducking": False,
        "audio_ducking_level_percent": 18.0,
        "audio_ducking_fallback_return_percent": 100.0,
+       # D-0010: output ducking and input voice privacy are separate
+       # settings. The three keys above are the legacy projection of these
+       # two blocks and are kept in sync by audio_schema on every load/save.
+       "output_ducking": audio_schema.output_ducking_defaults(),
+       "voice_privacy": audio_schema.voice_privacy_defaults(),
```

**(c) `_sanitize_profile_values()`** — beside the existing
`cfg["audio_ducking"] = ...` line (~line 402):

```python
+   cfg["output_ducking"] = audio_schema.sanitize_output_ducking(cfg.get("output_ducking"))
+   cfg["voice_privacy"] = audio_schema.sanitize_voice_privacy(cfg.get("voice_privacy"))
```

**(d) A third unconditional value-level migration** — `migrate_audio_settings`
is unconditional and idempotent by construction, exactly like
`_migrate_controller_binding` and `_migrate_output_delivery`, and belongs in
the same four call sites rather than in `store_migration.py`'s version-gated
ladder (see the long comment in `load_profile` explaining why). Add both calls,
in this order, immediately after each existing
`_migrate_output_delivery(...)` call:

```python
        _migrate_controller_binding(migrated)
        _migrate_output_delivery(migrated)
+       audio_schema.migrate_audio_settings(migrated)
+       audio_schema.project_legacy_audio_keys(migrated)
```

The four sites are:

| Function | Context |
|---|---|
| `load_profile` | legacy `config.yaml` migration branch (~line 987) |
| `load_profile` | "Default profile does not exist yet" branch (~line 996) |
| `load_profile` | normal load branch (~line 1027) |
| `save_profile` | before `_sanitize_profile_values` (~line 1213) |

Order is load-bearing: migrate derives the blocks from the legacy keys, then
project writes the legacy keys back from the blocks. Running them the other way
round would clobber a user's new setting with a stale legacy value.

**Optional, and recommended:** `validate_profile_settings`'s hotkey-conflict
map (~line 1161) reads `data.get("voice_mute_key")`. It keeps working via the
projection, but reading the binding directly is clearer once (d) is in:

```python
-       "Voice Mute Key": data.get("voice_mute_key"),
+       "Voice Mute Key": audio_schema.voice_privacy_of(data)["mute_binding"],
```

**Verification for this diff:** `tests/test_profile_migration.py`,
`tests/test_user_profile_sanitize.py`, and `tests/test_recorder_device.py`'s
`InputDeviceConfigTests` must stay green, and a round-tripped legacy profile
must come back byte-identical on the four legacy keys — which is exactly what
`tests/test_audio_schema.py::LegacyProjectionTests` already asserts at the
module level.

### 2.2 `server.py` (owned by the composition/routes lane)

**(a) Import:**

```python
import audio_status
```

**(b) `/capabilities` (~line 2849)** — `platform_capabilities.get_capabilities()`
returns platform facts; the two audio capability words are computed from them:

```python
 @app.get("/capabilities")
 async def capabilities():
-    return get_capabilities()
+    payload = get_capabilities()
+    push_to_mute_available = bool(payload.get("supports_input_injection", False))
+    payload["voice_privacy_status"] = audio_status.voice_privacy_capability(
+        isolation_available=False,           # no capture-isolation adapter yet (Wave 8B)
+        push_to_mute_available=push_to_mute_available,
+    )
+    payload["wake_status"] = audio_status.wake_capability(
+        engine_available=True,               # replace with wake_models.backbone_status(...)
+        classifier_available=bool(routes_wake.selected_classifier_id()),
+        qualified=False,                     # no measured wake qualification exists yet
+    )
+    return payload
```

`qualified=False` is deliberate and must stay false until a measured wake
qualification exists (false accept/reject, latency, CPU, handoff, device
recovery). The plan requires evidence before a support claim.

**(c) A runtime status surface** — the honest per-feature answer, distinct from
the capability words above:

```python
+@app.get("/audio/status")
+async def audio_runtime_status():
+    import audio_input_broker
+
+    config = load_profile(get_last_active_profile())
+    return audio_status.audio_status_snapshot(
+        config,
+        broker_status=audio_input_broker.get_broker().status(),
+        isolation_available=False,
+        push_to_mute_available=bool(get_capabilities().get("supports_input_injection", False)),
+        engaged=injector is not None and bool(injector._held_voice_mute_key),
+        restore_complete=True,               # becomes real with Wave 8B's journaled lease
+        enabled=bool(config.get("wake_word_enabled", False)),
+        listening=routes_wake.is_wake_listening(),
+    )
```

**(d) Privacy wipe** — the wipe path already calls
`routes_wake.stop_wake_listener()`. Add the unconditional broker quiesce beside
it, so "no live capture" is guaranteed without knowing who was holding it:

```python
         routes_wake.stop_wake_listener()
+        import audio_input_broker
+        audio_input_broker.get_broker().stop_all()
```

**(e) Emergency stop** — same call, same reasoning.

### 2.3 `routes_wake.py`

**No change required.** `WakeListener`'s constructor and `start`/`stop`/
`is_listening`/`status` signatures are unchanged; only the internals moved to
the broker. `status()` gains an optional `input_error` key when the microphone
could not be acquired, which existing clients ignore.

Optional improvement, once (b) above needs it — a small accessor so
`/capabilities` can ask which classifier is selected without duplicating the
profile read:

```python
+def selected_classifier_id():
+    return (_profile_config().get("wake_word_model") or "") or None
```

`/wake/enable`'s existing `reason` strings already carry
`"unavailable: no wake-phrase classifier selected"`; mapping that onto
`audio_status.WAKE_CLASSIFIER_MISSING` is a renderer-side concern.

### 2.4 `platform_capabilities.py`

**No change required for correctness.** `supports_audio_ducking` remains
accurate — it describes output ducking, which is now its own setting, so the
name finally matches the thing. If the settings lane wants an explicit input
counterpart:

```python
+# Input voice privacy is push-to-mute today; capture isolation (D-0010) has no
+# adapter yet on any platform, so this is deliberately not a "supports
+# isolation" flag.
+supports_voice_privacy_push_to_mute = supports_input_injection
+supports_capture_isolation = False
```

---

## 3. Not landed in Wave 8A

Stated plainly so nothing is assumed done:

- **`wake_pretrigger` is not wired into the wake path.** The module and its
  tests are complete and written against the broker's subscriber interface,
  but nothing constructs a `WakeHandoff` yet. Integration needs three calls:
  `arm()` when `/wake/enable` starts the listener, `on_chunk()` from
  `WakeListener._on_chunk`, and `activate()` in `routes_wake`'s `on_detect`
  before `hotkey_manager.request_start(reason="wake_word")`, with the drained
  pre-roll prepended to the recording. The recorder has no
  "prepend this audio" entry point yet; adding one is the smallest missing
  piece and belongs with the wake-handoff integration, not with the broker.
- **Trailing-silence command capture is not forced on for wake-started
  recordings.** `build_command_capture_detector()` exists and is tested; the
  recorder still builds its detector only from
  `auto_stop_after_silence_enabled`. Wiring it means passing the wake reason
  into `start_recording`.
- **Lease-based journaled exact restoration (D-0010) is Wave 8B.**
  `audio_status`'s `partially_restored` is the vocabulary it will report
  through; today `restore_complete` is always passed as `True`.
- **Capture isolation is Wave 8B.** `isolate_capture_streams` is a reserved,
  round-tripping mode value only; `effective_privacy_mode()` degrades it to
  push-to-mute and `voice_privacy_status()` says so out loud.
- **No renderer work.** Package H is backend vocabulary only; surfacing it is a
  later integration.
