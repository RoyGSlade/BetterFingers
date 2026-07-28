"""Windows capture isolation — feasibility design, NOT an implementation.

This module ships deliberately unavailable. D-0010 requires a time-boxed Core
Audio feasibility proof before Windows claims capture isolation; no Windows
host exists in this environment, so no such proof has been produced, and
inventing one from documentation would be exactly the "aspiration reported as
capability" that D-0009 forbids. Windows therefore stays on push-to-mute, and
:meth:`WindowsCoreAudioPrivacyGuard.availability` says
``not_implemented`` out loud.

The full design, the API survey, and the spike's acceptance criteria live in
``docs/release/WINDOWS_CAPTURE_ISOLATION_FEASIBILITY.md``. The short version,
recorded here so the shape of the eventual adapter is not lost:

**What Windows actually offers.** There is no per-application capture mute in
the Core Audio API. The Windows mixer's per-application sliders are
``IAudioSessionControl2`` / ``ISimpleAudioVolume`` on *render* endpoints —
that is output ducking, which BetterFingers already does. Capture endpoints do
enumerate sessions (``IAudioSessionManager2::GetSessionEnumerator`` on a
capture ``IMMDevice``, giving a process id per session via
``IAudioSessionControl2::GetProcessId``), so the *enumeration* half of this
adapter's contract is reachable. The *mutation* half is the open question:
``ISimpleAudioVolume::SetMute`` on a capture session is documented for render
and is not a supported per-application capture mute, and the alternatives
(muting the endpoint outright via ``IAudioEndpointVolume``, which is a global
change affecting BetterFingers too, or the policy-config interfaces, which are
undocumented) each fail a different requirement.

**Rejected outright, per D-0010, and not to be revisited by the spike:**
disabling the physical microphone device (a global, user-hostile change that
survives a crash in the worst way), bundling SoundVolumeView (a third-party
binary we would be redistributing), and shelling out to per-application name
loops (names are not identifiers — see :mod:`.linux_pulse`).

Until the spike passes every criterion in the design doc, this class stays as
it is. A partial pass is not a pass: a mute that cannot be exactly restored is
worse than no isolation, because the user is left with a dead microphone in
another application and no way to know why.
"""

from __future__ import annotations

from backend.platform.audio_privacy.base import (
    ADAPTER_WINDOWS_CORE_AUDIO,
    EngageOutcome,
    PrivacyGuard,
    RestoreOutcome,
    UNAVAILABLE_NOT_IMPLEMENTED,
)

#: Every criterion the Core Audio spike must meet before this adapter may
#: report available. Mirrored in the design doc; kept here as data so a future
#: implementer cannot quietly drop one, and so a test can assert the set is
#: unchanged while the adapter is still unavailable.
SPIKE_ACCEPTANCE_CRITERIA = (
    "enumerate_capture_sessions",       # every capturing process is listed, with its pid
    "identify_own_session",             # our own capture session is identified by process
                                        # identity, never by application name
    "read_prior_mute_state",            # each session's mute state can be read before we change it
    "mute_one_session_only",            # muting one session leaves every other session and the
                                        # endpoint itself untouched
    "exact_restore",                    # the prior state can be put back exactly
    "restore_after_process_crash",      # a killed BetterFingers leaves state a next run can undo
                                        # from the journal alone
    "detect_new_session_midstream",     # a capture client starting mid-recording is noticed
    "supported_api_only",               # no undocumented policy-config interfaces, no third-party
                                        # binaries, no device disable
    "measured_on_supported_windows",    # verified on the Windows versions the release supports
)


class WindowsCoreAudioPrivacyGuard(PrivacyGuard):
    """Placeholder adapter: always unavailable, never mutates anything.

    It exists so the platform table has a real entry with a real reason
    instead of a gap, and so :func:`base.detect_guard` has something to
    construct on ``win32`` that degrades exactly like every other unavailable
    adapter.
    """

    name = ADAPTER_WINDOWS_CORE_AUDIO

    #: Re-exported for callers that want to show what is still outstanding.
    acceptance_criteria = SPIKE_ACCEPTANCE_CRITERIA

    def availability(self) -> tuple:
        return False, UNAVAILABLE_NOT_IMPLEMENTED

    def list_streams(self) -> list:
        return []

    def engage(self, keep_unmuted_apps=(), journal_write=None) -> EngageOutcome:
        del keep_unmuted_apps, journal_write
        return EngageOutcome(ok=False, reason=UNAVAILABLE_NOT_IMPLEMENTED)

    def restore(self, muted_streams, journal_replace=None) -> RestoreOutcome:
        del journal_replace
        # Nothing was ever muted here, so there is nothing outstanding.
        return RestoreOutcome(complete=True, gone=len(list(muted_streams or [])),
                              reason=UNAVAILABLE_NOT_IMPLEMENTED)
