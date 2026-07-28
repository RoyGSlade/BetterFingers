# Windows capture isolation — feasibility design and spike acceptance criteria

**Status: DESIGNED, NOT IMPLEMENTED. Windows ships push-to-mute.**

D-0010 permits Linux capture isolation and requires a *time-boxed Core Audio
feasibility proof* before Windows may claim the same. No Windows host exists
in this environment, so no proof has been produced. This document is the
design and the bar the spike has to clear; it is not evidence that the bar can
be cleared.

The code side of that statement is
[`backend/platform/audio_privacy/windows_core_audio.py`](../../backend/platform/audio_privacy/windows_core_audio.py),
which returns `(False, "not_implemented")` from `availability()` and mutates
nothing. On Windows, `audio_schema.effective_privacy_mode` therefore degrades
a stored `isolate_capture_streams` to `push_to_mute`, and
`audio_status.voice_privacy_status` reports
`reason="isolation_degraded_to_push_to_mute"` — the honest answer, in the
vocabulary that already existed for it.

---

## 1. What the platform actually offers

The short version: **Windows has no supported per-application capture mute.**

| Mechanism | Endpoint | What it does | Verdict |
|---|---|---|---|
| `IAudioSessionManager2::GetSessionEnumerator` + `IAudioSessionControl2::GetProcessId` | capture | Enumerates capture sessions with their owning process id | **Usable** — this is the enumeration half |
| `ISimpleAudioVolume::SetMute` | render | The per-app sliders in the Windows volume mixer | Output ducking, which BetterFingers already does. Not input |
| `ISimpleAudioVolume::SetMute` on a *capture* session | capture | Documented for render sessions; behavior on capture sessions is not a supported per-application capture mute | **The open question the spike exists to answer** |
| `IAudioEndpointVolume::SetMute` | capture | Mutes the microphone endpoint outright | **Rejected** — global. It would mute BetterFingers too, which defeats the purpose |
| `IPolicyConfig` / policy-config COM interfaces | either | Undocumented, unstable across Windows builds | **Rejected** — D-0010's "supported API only" rule |
| Disable the capture device | device | Turns the microphone off at the device level | **Rejected by D-0010 by name.** Global, user-hostile, and survives a crash in the worst possible way |
| Bundle SoundVolumeView | — | Third-party mixer CLI | **Rejected by D-0010 by name.** We would be redistributing it |
| Shell out and match application names | — | — | **Rejected.** Names are not identifiers; see [`linux_pulse.py`](../../backend/platform/audio_privacy/linux_pulse.py)'s module docstring for the full reasoning |

So the spike is narrow and answerable: **can one capture session be muted, and
exactly restored, through a supported API, without touching the endpoint or any
other session?** Everything else in the adapter — enumeration, process
identity, the journal, the lease lifecycle — already exists and is platform
independent.

## 2. The shape of the adapter, if the spike passes

`WindowsCoreAudioPrivacyGuard` implements the same
[`PrivacyGuard`](../../backend/platform/audio_privacy/base.py) contract the
Linux adapter does. Nothing above it changes:

- `availability()` → COM initializes, a capture `IMMDevice` is obtained, and a
  session enumerator answers.
- `list_streams()` → one `CaptureStream` per session: `key` is the session
  instance identifier, `is_self` comes from `GetProcessId` compared against
  this process (never from `GetDisplayName`), `labels` carry the display name
  **only** for the user's `keep_unmuted_apps` allowlist.
- `engage()` / `restore()` → identical decision rules to Linux: mute only
  currently-unmuted, non-ours, non-allowlisted sessions; record the prior
  state; restore only what we changed; a session that ended is `gone`, not
  `failed`.
- `watch()` → `IAudioSessionNotification` for sessions created mid-recording,
  used as a "go look" trigger exactly like `pactl subscribe`.

The journal, the lease, `restore_complete`, and the status vocabulary need no
Windows-specific work at all. That is the point of putting the contract in
`base.py`.

## 3. Spike acceptance criteria

Mirrored as data in `windows_core_audio.SPIKE_ACCEPTANCE_CRITERIA` and asserted
by `tests/test_audio_privacy_base.py::WindowsFeasibilityTests`, so the list
cannot be quietly shortened while the adapter is still unavailable.

| # | Criterion | Passes when |
|---|---|---|
| 1 | `enumerate_capture_sessions` | Every process capturing from the default input device is listed, each with its process id |
| 2 | `identify_own_session` | Our own capture session is identified by process identity alone. A test with a deliberately misleading display name must still identify it correctly |
| 3 | `read_prior_mute_state` | Each session's mute state is readable *before* we change it |
| 4 | `mute_one_session_only` | Muting one session leaves every other session audible and the endpoint itself untouched — verified by observing a second capturing application, not by reading back our own call |
| 5 | `exact_restore` | The prior state is put back exactly, including the case where the app muted itself while we held the lease |
| 6 | `restore_after_process_crash` | BetterFingers killed mid-recording (`TerminateProcess`, no unwinding) leaves state that the next run undoes from the journal alone |
| 7 | `detect_new_session_midstream` | A capture client started after `engage()` is muted too |
| 8 | `supported_api_only` | No `IPolicyConfig`, no undocumented interfaces, no third-party binaries, no device disable |
| 9 | `measured_on_supported_windows` | 1–8 verified on every Windows version the release supports, on real hardware |

**A partial pass is not a pass.** Criteria 5 and 6 are the ones that make
isolation better than nothing: a mute we cannot exactly restore leaves the user
with a dead microphone in another application and no way to know why, which is
strictly worse than the push-to-mute they have today. If the spike passes 1–4
and fails 5, the correct outcome is to keep this file's status line unchanged.

## 4. Time box and outcome

The spike is bounded to one focused engineering session on a real Windows host.
Its output is one of exactly two things:

1. **Pass** — the adapter is implemented against this contract, the criteria
   above become tests, and Windows's `voice_privacy_status` gains a real
   `supported` capability word.
2. **Fail** — this document records *which* criterion failed and why, and
   Windows keeps `push_to_mute` with the `isolation_degraded_to_push_to_mute`
   status it has now.

There is no third outcome. Shipping isolation that mostly restores is not on
the table.
