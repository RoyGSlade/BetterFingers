# Wave 8B wiring — what landed, what is designed only, and the exact diffs for integration

Wave 8B is the second half of Gate 8: capture isolation, the journaled privacy
lease, the wake handoff, and the runtime license gate. It completes the
Linux-side implementation of D-0010 and closes the "not landed" list D-0025
recorded against Wave 8A.

Read [`WAVE8A_WIRING.md`](WAVE8A_WIRING.md) first — this document assumes the
schema split, the `AudioInputBroker`, and the `audio_status` vocabulary are
already in the tree, because everything here builds on them.

Section 1 is what is in the tree and tested. Section 2 is what is deliberately
**designed and not implemented**, stated plainly. Section 3 gives the exact
changes for the files this wave did not touch because another lane owns them.

---

## 1. Landed and tested

### New package: `backend/platform/audio_privacy/`

| Module | What it owns |
|---|---|
| `base.py` | The `PrivacyGuard` adapter contract, the `CaptureStream` / `MutedStream` / `EngageOutcome` / `RestoreOutcome` vocabulary, `NullPrivacyGuard`, and `detect_guard()` runtime detection. No platform code. |
| `journal.py` | `PrivacyJournal` — the crash-recovery journal, written and `fsync`ed **before** any state change, content-free by construction, plus `recover_pending()` which restores and clears at the next startup. |
| `linux_pulse.py` | `LinuxPulsePrivacyGuard` — PulseAudio / PipeWire capture isolation over structured `pactl -f json` output. |
| `windows_core_audio.py` | Feasibility design only; permanently `not_implemented`. See [`WINDOWS_CAPTURE_ISOLATION_FEASIBILITY.md`](WINDOWS_CAPTURE_ISOLATION_FEASIBILITY.md). |
| `lease.py` | `AudioPrivacyLease` — the one owner of engage/release, driving both push-to-mute and isolation, and producing the real `restore_complete`. |

`__init__.py` re-exports **nothing**, on purpose: a re-exporting package module
becomes a dependency of its own leaves and `tests/test_architecture_smoke.py`
correctly reports that as a cycle. Callers import the module they need
(`from backend.platform.audio_privacy import lease`). The real graph is a DAG:
`lease → journal → base`.

### The three rules the Linux adapter is built around

1. **Structured output only.** Every enumeration is `pactl -f json list
   source-outputs`, parsed as JSON. There is no `grep`, `awk`, `sed`, or shell
   string anywhere in the module, and `availability()` refuses an adapter whose
   `pactl` cannot produce JSON rather than falling back to the human-readable
   listing (`tests/test_audio_privacy_linux_pulse.py` asserts both).
2. **Names are not identifiers.** "Is this stream ours?" is answered by process
   identity — the stream's `application.process.id`, walked up the `/proc`
   `PPid` chain against this process. A stream whose display name is
   "BetterFingers" but whose pid is not ours is muted; a stream named "Some
   Other App" whose pid is ours is not. Names appear in exactly one place,
   `CaptureStream.matches_allowlist`, because the user's `keep_unmuted_apps`
   list *is* a list of names the user typed.
3. **Only what we changed.** A stream that is already muted is skipped and not
   recorded, so restore can never unmute something the user muted. A stream
   that disappeared is `gone`, not `failed`. Where the server provides
   `object.serial`, a reused index with a different serial is treated as gone,
   so restore cannot touch a stream that inherited the index.

### The lease, and every path that releases it

| Stop path | How the release is reached | Landed here? |
|---|---|---|
| Normal stop | `recorder.stop_recording` | **Yes** |
| Silence auto-stop | `recorder.stop_recording` (auto-stop calls it) | **Yes** |
| Watchdog force-stop | `recorder.stop_recording` (watchdog calls it) | **Yes** |
| Recorder failed to start | `recorder.start_recording`'s failure branch | **Yes** |
| Emergency stop | `server.emergency_stop_runtime` | Diff §3.1 |
| Privacy wipe | `server._perform_privacy_wipe` | Diff §3.2 |
| Shutdown | `server.shutdown_event` | Diff §3.3 |
| Backend crash | `journal.recover_pending()` at the next startup | Diff §3.4 |

The four rows marked "Yes" are in the tree and tested; the four diffs are in
section 3 because `server.py` is integration-owned. `release()` is idempotent
and never raises, so the paths that overlap (emergency stop *and* wipe *and*
shutdown for one recording) are safe in any order and from any thread.

### `restore_complete` is measured now

Wave 8A passed a constant `True`. `AudioPrivacyLease.restore_complete()` is the
real value: it goes `False` when a release could not put everything back, and
it is **sticky** until `acknowledge_partial_restore()` — a later clean
recording must not paper over a microphone we left muted in somebody else's
application. Fed into the existing `audio_status.voice_privacy_status`, it
produces `status="partially_restored"`, `reason="restore_incomplete"`, which is
exactly what that vocabulary was built for in Wave 8A.

### `isolate_capture_streams` is selectable now — where it is provable

`effective_privacy_mode(config, isolation_available=...)` already degraded a
stored `isolate_capture_streams` to `push_to_mute`. The lease now supplies a
real `isolation_available` from `detect_guard()`, which proves three things at
runtime before answering yes: `pactl` exists, a server answers `pactl info`,
and that server speaks JSON. Anything short of all three is a `NullPrivacyGuard`
carrying the reason, and the degradation is the visible one `audio_status`
already describes.

**Measured on this machine:** available. `tests/test_audio_privacy_linux_pulse.py
::RealPactlSmokeTests` ran (did not skip) and the adapter's availability agreed
with the real binary. That is a smoke test, not qualification — the director's
live run is what qualifies it.

### Wake handoff — the D-0025 not-landed list, closed

| D-0025 said | Now |
|---|---|
| "The recorder has no 'prepend this audio' entry point yet" | `AudioRecorder.start_recording(..., prepend_audio=)` seeds the clip before the first live chunk (no race), and `AudioRecorder.prepend_audio()` inserts at the head for the late case. A malformed pre-roll is dropped, never fatal. |
| "`arm()` when `/wake/enable` starts the listener" | `routes_wake.wake_enable` arms before `listener.start()`, so no chunk can arrive at a disarmed ring. |
| "`on_chunk()` from `WakeListener._on_chunk`" | `WakeListener.chunk_observer` is fed **before** scoring, so the audio a detection fires on is already in the ring. |
| "`activate()` in `routes_wake`'s `on_detect`" | `on_detect` drains unconditionally (activate hands over the audio *and* wipes the ring in one step) and passes the pre-roll to `request_start`. |
| "Trailing-silence command capture is not forced on for wake-started recordings" | `start_recording(reason="wake_word")` always builds a detector via `wake_pretrigger.build_command_capture_detector`, regardless of `auto_stop_after_silence_enabled`. |

`wake_pretrigger.py` was **not modified** — it was complete and tested. One
piece of glue lives in `routes_wake._build_chunk_observer`: `activate()`
deliberately disarms (the recorder owns the stream during the command), so the
ring is re-armed once the recording is over. Without that the *next* wake would
lose its first word. That re-arm belongs in the wiring, not in the
owner-driven module.

### WMP-3 closed: the license gate runs at runtime

`wake_models.RUNTIME_ALLOWED_LICENSES` = `ALLOWED_LICENSES` ∪
`{"self-trained"}`, and `assert_license_allowed()` is enforced in both loading
paths:

- `wake_word.build_openwakeword_detector` checks the backbones and the selected
  classifier **first**, before anything is hashed or loaded — whether an
  artifact may be used is a prior question to whether it is intact.
- `wake_models.download_wake_model` checks before the bytes arrive, so an
  incompatibly-licensed artifact never reaches disk.

Two deliberate distinctions:

- `ALLOWED_LICENSES` is untouched, so
  `tests/test_wake_model_provenance.py`'s equality assertion against the
  manifest's `license_gate.allowed` still holds. It is the set we are willing
  to **redistribute**. `self-trained` is not in it — a model the user trained
  here from their own recordings redistributes nothing — but it must still be
  a *known* value, because "unknown license" must never load.
- `model_license()` returns `None` for an unknown id and `""` for a known model
  with no license recorded. An unknown id is a lookup failure the existing
  verification path already reports accurately; a blank license is a policy
  failure that must be refused. Collapsing the two would make every typo look
  like a licensing problem.

### Files modified in place

| File | Change |
|---|---|
| `recorder.py` | Privacy lease acquired at start (before the stream opens) and released in `stop_recording`'s `finally` plus the failed-start branch and the not-recording branch; `reason=` and `prepend_audio=` parameters; `_seed_frames` / `prepend_audio`; wake reason forces command capture. |
| `hotkey_manager.py` | `_start_recording` / `request_start` thread `reason` and `prepend_audio` through to the recorder. |
| `wake_word.py` | `WakeListener.chunk_observer`, fed before scoring; the runtime license gate at the top of `build_openwakeword_detector`. |
| `routes_wake.py` | `get_wake_handoff()`, `_build_chunk_observer()`, `_recording_in_progress()`, `wipe_wake_pretrigger()`; arm/feed/activate in `/wake/enable`; observer cleared and ring wiped in `stop_wake_listener()`. |
| `wake_models.py` | `SELF_PRODUCED_LICENSES`, `RUNTIME_ALLOWED_LICENSES`, `WakeModelLicenseRefused`, `license_allowed()`, `assert_license_allowed()`, `model_license()`; the gate in `download_wake_model`. |
| `tests/test_hotkey_manager_tts.py` | `_DummyRecorder.start_recording` accepts the new `reason` / `prepend_audio` contract and records both. |

---

## 2. Designed only — not implemented, and not to be read as done

- **Windows capture isolation.** A feasibility design with acceptance criteria,
  nothing more. `WindowsCoreAudioPrivacyGuard.availability()` returns
  `(False, "not_implemented")` and the class mutates nothing. Windows stays on
  push-to-mute with the honest `isolation_degraded_to_push_to_mute` status. See
  [`WINDOWS_CAPTURE_ISOLATION_FEASIBILITY.md`](WINDOWS_CAPTURE_ISOLATION_FEASIBILITY.md).
- **PipeWire-native isolation.** The Linux adapter goes through
  `pipewire-pulse`, which is what every PipeWire desktop runs. A native
  `pw-cli`/libpipewire path is not implemented and is not needed for Gate 8.
- **No renderer work.** Nothing here surfaces `partially_restored` to the user.
  The lease produces it and `/audio/status` will carry it once §3 lands;
  displaying it is a later integration, as it was in Wave 8A.
- **Wake `qualified` stays false.** Nothing in this wave is a measured wake
  qualification. `/capabilities` must keep `qualified=False`.
- **Live capture-isolation qualification is not done.** The unit tests mock
  every `pactl` call; the real-binary smoke test is read-only and mutes
  nothing. Muting and restoring a second application's live capture stream is
  the director's live run.
- **WMP-4 (Kokoro license asserted, not verified) is untouched.** It belongs to
  the TTS lane and remains open.

---

## 3. Documented diffs — files this wave did not edit

### 3.1 `server.py` — emergency stop

`emergency_stop_runtime()` already quiesces the broker unconditionally. The
lease release belongs directly beside it, for the same reason: emergency stop
must leave nothing engaged regardless of who engaged it.

```python
     # Quiesce the shared capture stream: emergency stop must leave no live
     # audio consumer regardless of who held the broker.
     try:
         import audio_input_broker
         audio_input_broker.get_broker().stop_all()
     except Exception as exc:
         logging.warning(f"Emergency broker stop failed: {exc}")

+    # Release the voice-privacy lease for the same reason: an emergency stop
+    # that left another application's microphone muted would be the worst
+    # possible outcome of pressing the panic button. Idempotent — the recorder
+    # has usually released it already via request_stop above.
+    try:
+        from backend.platform.audio_privacy import lease as privacy_lease
+        privacy_lease.get_lease().release(reason="emergency_stop")
+    except Exception as exc:
+        logging.warning(f"Emergency voice-privacy release failed: {exc}")
+
     pending_manual_send_ids.clear()
```

Note the existing `output_injector.release_mute_key()` a few lines above stays
exactly as it is — it is the belt to the lease's braces, and both are
idempotent.

### 3.2 `server.py` — privacy wipe

Two additions in `_perform_privacy_wipe`, both in step 0, beside the existing
`routes_wake.stop_wake_listener()` and broker quiesce:

```python
         import routes_wake
         cleared["wake_listener_stopped"] = bool(routes_wake.stop_wake_listener())
+        # The pre-trigger ring is the only place in the wake pipeline where raw
+        # audio lives at all, so "no retained audio" has to include it.
+        # stop_wake_listener() already wipes it; this is the explicit,
+        # reportable call for the case where the listener was never running.
+        cleared["wake_pretrigger_wiped"] = bool(routes_wake.wipe_wake_pretrigger())
         # Quiesce the shared capture stream unconditionally: "no live capture"
         # must hold without knowing who was holding the broker.
         import audio_input_broker
         audio_input_broker.get_broker().stop_all()
+        # And release voice privacy: a wipe must not leave another
+        # application's capture stream muted by a lease nothing will release.
+        from backend.platform.audio_privacy import lease as privacy_lease
+        privacy_lease.get_lease().release(reason="privacy_wipe")
```

The wipe also needs to remove the journal file itself — see §3.5.

### 3.3 `server.py` — shutdown

```python
 @app.on_event("shutdown")
 def shutdown_event():
     stop_hotkey_manager()
     # Safety net in case /wake/disable was never called before shutdown --
     # idempotent, safe even if wake word was never enabled this run.
     import routes_wake
     routes_wake.stop_wake_listener()
+    # Last chance to put another application's microphone back. A clean
+    # shutdown that skipped this would leave a journal for the next startup to
+    # recover from, which works — but recovering from a crash we did not have
+    # is not a good look, and the user's meeting app is muted in the meantime.
+    try:
+        from backend.platform.audio_privacy import lease as privacy_lease
+        privacy_lease.get_lease().release(reason="shutdown")
+    except Exception as exc:
+        logging.warning(f"Shutdown voice-privacy release failed: {exc}")
```

### 3.4 `server.py` — crash recovery at startup

In `startup_event()`, after the legacy-data migration and **before** anything
opens audio. Guarded by `_is_test_env()` for the same reason the migration is:
the test suite must never touch a real audio server.

```python
     loop = asyncio.get_event_loop()
+    # D-0010 crash recovery: a previous run that died while holding the voice
+    # privacy lease left other applications' capture streams muted, and the
+    # journal is the only record of it. Undo it before anything else opens
+    # audio, then clear it. Content-free; safe when no journal exists.
+    if not _is_test_env():
+        try:
+            from backend.platform.audio_privacy import lease as privacy_lease
+            recovery = privacy_lease.recover_on_startup()
+            if recovery.get("streams"):
+                logging.info("Audio privacy crash recovery: %s", recovery)
+        except Exception as exc:
+            logging.warning(f"Audio privacy crash recovery skipped: {exc}")
```

### 3.5 `server.py` — the two status surfaces become honest

`/capabilities` (~line 2890): `isolation_available` is now knowable.

```python
     payload = get_capabilities()
     push_to_mute_available = bool(payload.get("supports_input_injection", False))
+    from backend.platform.audio_privacy import lease as privacy_lease
+    isolation_available = privacy_lease.get_lease().isolation_available()
     payload["voice_privacy_status"] = audio_status.voice_privacy_capability(
-        isolation_available=False,  # no capture-isolation adapter yet (Wave 8B)
+        isolation_available=isolation_available,
         push_to_mute_available=push_to_mute_available,
     )
```

`wake_capability(..., qualified=False)` stays exactly as it is. Nothing in
Wave 8B is a measured wake qualification.

`/audio/status` (~line 2911): both constants become real.

```python
 async def audio_runtime_status():
     import audio_input_broker
     import audio_status
     import routes_wake

+    from backend.platform.audio_privacy import lease as privacy_lease
+    lease = privacy_lease.get_lease()
     config = load_profile(get_last_active_profile())
     return audio_status.audio_status_snapshot(
         config,
         broker_status=audio_input_broker.get_broker().status(),
-        isolation_available=False,
+        isolation_available=lease.isolation_available(),
         push_to_mute_available=bool(get_capabilities().get("supports_input_injection", False)),
-        engaged=output_injector is not None and bool(output_injector._held_voice_mute_key),
+        # The lease knows about both mechanisms; the injector only knows about
+        # the key. `held` is true for an isolation lease too.
+        engaged=lease.is_held(),
-        restore_complete=True,  # becomes real with Wave 8B's journaled lease
+        restore_complete=lease.restore_complete(),
         enabled=bool(config.get("wake_word_enabled", False)),
         listening=routes_wake.is_wake_listening(),
     )
```

**Verification for these diffs:** `tests/test_audio_status.py`,
`tests/test_server_platform_runtime.py` and `tests/test_server_wake_routes.py`
must stay green, and a manual check that
`/audio/status` reports `voice_privacy.status == "partially_restored"` after a
forced partial restore (the unit-level equivalent is
`tests/test_audio_privacy_lease.py::RestoreHonestyTests`).

### 3.6 `data_categories.py` — declare the journal

The journal is a persistent file under the user data directory. It is
content-free, but an undeclared store is a privacy report that lies by
omission, and the wipe path has to remove it or a wipe would leave a record of
which streams were muted (as opaque indices, but still).

Add beside the other `_PERSONAL` entries, after `wake_models`:

```python
     _cat("wake_models", "Wake models & training artifacts", "python", "sensitive",
          "Kept until personal data is cleared.", _PERSONAL),
+    # Audio privacy crash-recovery journal (Wave 8B, D-0010). Written before
+    # any capture stream is muted and cleared on the next clean release or at
+    # the next startup, so it is normally absent. Declared "configuration"
+    # sensitivity and user_text=False because it holds only audio-server
+    # stream indices and a boolean prior mute state — no names, no audio, no
+    # prose. Cleared by a personal wipe rather than only a factory reset,
+    # because it is operational state, not a setting.
+    _cat("audio_privacy_journal", "Audio privacy recovery journal", "python", "configuration",
+         "Transient; cleared when voice privacy is released and on wipe.", _PERSONAL),
```

The wipe callable, when 2.1d-style wiring reaches this category, is simply
`backend.platform.audio_privacy.journal.PrivacyJournal().clear()`, and the
verify callable is `not PrivacyJournal().exists()`. Note the ordering
requirement: the wipe must run **after** §3.2's lease release, or the release
would rewrite the journal it just deleted.

### 3.7 `platform_capabilities.py` — optional

Wave 8A suggested a `supports_capture_isolation = False` constant and it was
not taken. If the settings lane wants one now, it must be computed, not
constant:

```python
+# Capture isolation is a runtime fact (does a Pulse-compatible server answer?),
+# not a platform fact, so it is deliberately NOT a module constant here. Ask
+# backend.platform.audio_privacy.lease.get_lease().isolation_available().
```

---

## 4. Verification

Everything below was run with the qualified interpreter, `.venv/bin/python`.

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/ -q -p no:randomly` | **2772 passed, 2 skipped, 0 failed** in 84s. The 2 skips are pre-existing (`tests/test_wake_word.py` wake-fixture tests, which need `BETTERFINGERS_WAKE_FIXTURES`). **Caveat:** the working tree also carried a sibling lane's concurrent, uncommitted work (`voice_commands.py`, `tests/test_voice_commands.py`, the Signal Desk renderer files), so the absolute total is not attributable to this wave alone. The per-suite numbers below are. |
| `.venv/bin/python -m pytest tests/test_audio_privacy_base.py -q` | 18 passed |
| `.venv/bin/python -m pytest tests/test_audio_privacy_journal.py -q` | 18 passed |
| `.venv/bin/python -m pytest tests/test_audio_privacy_linux_pulse.py -q` | 40 passed |
| `.venv/bin/python -m pytest tests/test_audio_privacy_lease.py -q` | 28 passed |
| `.venv/bin/python -m pytest tests/test_wake_handoff_wiring.py -q` | 34 passed |
| `.venv/bin/python -m pytest tests/test_wake_license_runtime.py -q` | 16 passed |
| `.venv/bin/python -m pytest "tests/test_audio_privacy_linux_pulse.py::RealPactlSmokeTests" -v` | 2 passed, **not skipped** — pactl and a Pulse-compatible server are present on this machine and the adapter's availability agreed with the binary |

**Pre-existing suites that had to stay green and did:**
`test_recorder_device.py`, `test_wake_models.py`, `test_wake_model_provenance.py`,
`test_wake_pretrigger.py`, `test_audio_schema.py`, `test_audio_status.py`,
`test_audio_input_broker.py` (220 tests together), plus
`test_architecture_smoke.py`'s backend import-cycle check and
`test_hotkey_manager_tts.py`'s watchdog tests — both of which the first
integration attempt broke and both of which are green now (see §1's note on
`__init__.py` and the `_DummyRecorder` update).

**All `pactl` / subprocess / audio I/O in tests is mocked.** The one suite that
touches the real binary, `RealPactlSmokeTests`, is `skipUnless(shutil.which(
"pactl"))`, is read-only, and mutes nothing.

**Not verified here, by design:** muting and restoring a second application's
live capture stream, and any wake qualification. Those are the director's live
run.

## 5. Suggested commit message

```text
Wave 8B: capture isolation, the journaled privacy lease, and wake handoff

Completes the Linux side of Gate 8 (D-0010, D-0013) and closes the
not-landed list D-0025 recorded against Wave 8A.

New package backend/platform/audio_privacy/:
- base.py: the PrivacyGuard contract, result vocabulary, runtime detection
- journal.py: crash-recovery journal, fsynced before any state change,
  content-free, recovered and cleared at startup
- linux_pulse.py: PulseAudio/PipeWire isolation over structured `pactl -f
  json` output. Own streams identified by process identity, never by name;
  only currently-unmuted non-BF streams are muted; only what we changed is
  restored; streams that appear mid-recording are muted too
- windows_core_audio.py: feasibility design only, permanently unavailable.
  Windows stays push_to_mute with an honest degraded status
- lease.py: one owner of engage/release across both mechanisms

Lease released on every stop path: normal, trailing-silence, watchdog,
failed start (all in recorder.py); emergency stop, wipe, shutdown and crash
recovery are documented diffs for the integration-owned server.py.
audio_status's restore_complete is now measured and sticky rather than a
constant True, and isolate_capture_streams becomes selectable where runtime
detection proves pactl plus a Pulse-compatible server.

Wake handoff wired: recorder gains a prepend-audio entry point, the ring is
armed on /wake/enable and fed from WakeListener before scoring, activate()
hands the pre-roll to the recording, and a wake-started recording always
gets trailing-silence command capture. wake_pretrigger.py is unchanged.

WMP-3 closed: ALLOWED_LICENSES is enforced by the code in both model
loading paths, refusing a non-allowed license with an honest error.

Verified: .venv/bin/python -m pytest tests/ -> 2772 passed, 2 skipped
(pre-existing wake-fixture skips). All pactl/subprocess/audio I/O mocked;
the real-pactl smoke test is read-only and skips without the binary.
```
