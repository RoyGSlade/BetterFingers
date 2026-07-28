"""The audio privacy lease: one owner, one release path, one honest answer.

D-0010's requirement is not "mute other apps while recording". It is
**exact restoration on every stop path**, and the way to get that is to stop
scattering "engage" and "restore" calls across the codebase and give the
behavior a single owner with a lifetime.

That owner is the lease:

    acquire  →  (recording runs)  →  release

and the whole design exists to make the second arrow unconditional. Every way
a recording can end goes through :meth:`AudioPrivacyLease.release`:

===========================  ===================================================
Stop path                    How the release is reached
===========================  ===================================================
Normal stop                  ``recorder.stop_recording``
Silence auto-stop            ``recorder.stop_recording`` (auto-stop calls it)
Watchdog force-stop          ``recorder.stop_recording`` (watchdog calls it)
Recorder failed to start     ``recorder.start_recording``'s failure branch
Emergency stop               ``server.emergency_stop_runtime``
Privacy wipe                 ``server._perform_privacy_wipe``
Shutdown                     ``server.shutdown_event``
Backend crash                :func:`journal.recover_pending` on the NEXT start
===========================  ===================================================

The last row is why the journal exists: a crash has no release path at all, so
the record of what to undo has to survive the process. It is written before
any state changes, and recovered and cleared at the next startup.

**Two mechanisms, one lifecycle.** ``push_to_mute`` holds a key; capture
isolation mutes streams. They differ in fidelity, not in lifetime, so the
lease drives both and reports through the same status vocabulary. Which one
runs is :func:`audio_schema.effective_privacy_mode`'s answer, given live
isolation detection — so a stored ``isolate_capture_streams`` becomes real
isolation on a machine with pactl and a Pulse-compatible server, and degrades
visibly to push-to-mute everywhere else, exactly as ``audio_schema`` already
promised.

**``restore_complete`` is now measured.** Wave 8A passed a constant ``True``
to :func:`audio_status.voice_privacy_status` because nothing tracked
restoration. :meth:`AudioPrivacyLease.restore_complete` is the real value: it
goes False when a release could not put everything back, and stays False —
surfacing as ``partially_restored`` — until a later release succeeds or the
user is told. A status route that always says "fine" is worse than no status
route.

Idempotency is a requirement, not a nicety: emergency stop, wipe, and
shutdown can all fire for the same recording, in any order, from different
threads. ``acquire`` twice is one lease; ``release`` twice is one restore.
"""

from __future__ import annotations

import logging
import threading

import audio_schema

from backend.platform.audio_privacy.base import detect_guard
from backend.platform.audio_privacy.journal import PrivacyJournal, new_lease_id


def _default_push_to_mute():
    """Late-bound lookup of the process's injector.

    Deliberately a lookup and not an import-time dependency: this package is
    platform code and must stay importable without the server. Returns an
    object exposing ``hold_mute_key``/``release_mute_key``, or None when no
    injector is running (a headless test, or a backend that failed to build
    one), in which case push-to-mute reports unavailable rather than silently
    doing nothing.
    """
    try:
        import server

        return getattr(server, "output_injector", None)
    except Exception as exc:  # pragma: no cover - import-order defensive
        logging.debug("Push-to-mute injector lookup failed: %s", exc)
        return None


class AudioPrivacyLease:
    """Process-wide owner of input voice privacy for one recording at a time."""

    def __init__(self, guard=None, journal=None, push_to_mute_provider=None):
        self._lock = threading.RLock()
        self._guard = guard
        self._guard_detected = guard is not None
        self._isolation_available = None   # None = not probed yet
        self._journal = journal if journal is not None else PrivacyJournal()
        self._push_to_mute_provider = push_to_mute_provider or _default_push_to_mute

        self._held = False
        self._lease_id = ""
        self._mode = audio_schema.PRIVACY_MODE_OFF
        self._muted = []           # list[MutedStream] — only what WE muted
        self._key_held = False
        self._watch_stop = None
        self._keep_unmuted = ()
        self._restore_complete = True
        self._last_reason = ""

    # -- detection -----------------------------------------------------

    def guard(self):
        """The capture-isolation adapter for this machine, detected once.

        Detection is cached because it shells out to pactl and a recording
        start must not pay that repeatedly; a machine does not gain or lose an
        audio server mid-session in a way worth re-probing per recording.
        """
        with self._lock:
            if not self._guard_detected:
                self._guard = detect_guard()
                self._guard_detected = True
            return self._guard

    def isolation_available(self) -> bool:
        """Whether capture isolation can actually run here, probed once.

        Cached alongside the adapter: :meth:`status` must be cheap enough to
        call from a status route on every poll, and shelling out to pactl each
        time would not be.
        """
        with self._lock:
            if self._isolation_available is None:
                try:
                    self._isolation_available = bool(self.guard().is_available())
                except Exception as exc:  # pragma: no cover - defensive
                    logging.debug("Isolation availability probe failed: %s", exc)
                    self._isolation_available = False
            return self._isolation_available

    def reset_detection(self):
        """Force the next call to re-detect. Used by tests and by a device
        change that plausibly means the audio server was restarted."""
        with self._lock:
            if self._held:
                return
            self._guard = None
            self._guard_detected = False
            self._isolation_available = None

    # -- state ---------------------------------------------------------

    def is_held(self) -> bool:
        with self._lock:
            return self._held

    def restore_complete(self) -> bool:
        """The real value behind :mod:`audio_status`'s ``restore_complete``."""
        with self._lock:
            return self._restore_complete

    def acknowledge_partial_restore(self) -> None:
        """Clear a sticky ``partially_restored`` after the user has been told.

        Exposed so the surface that reports the failure can also dismiss it;
        nothing clears it automatically, because a privacy failure that
        silently ages out is a privacy failure the user never learned about.
        """
        with self._lock:
            self._restore_complete = True

    def status(self) -> dict:
        """Counts and words only — never a stream identifier, never a name."""
        with self._lock:
            guard = self._guard
            return {
                "held": self._held,
                "mode": self._mode,
                "adapter": getattr(guard, "name", "") if guard is not None else "",
                "isolation_available": bool(self._isolation_available),
                "muted_streams": len(self._muted),
                "push_to_mute_held": self._key_held,
                "watching": self._watch_stop is not None,
                "restore_complete": self._restore_complete,
                "reason": self._last_reason,
            }

    # -- acquire -------------------------------------------------------

    def acquire(self, config, reason="recording") -> dict:
        """Engage voice privacy for a recording. Idempotent.

        Never raises and never blocks a recording: if privacy cannot be
        engaged, the recording still happens and the failure is reported. A
        dictation app that refuses to record because another app's mixer was
        unreachable would be trading the user's actual task for a secondary
        protection.
        """
        with self._lock:
            if self._held:
                return self.status()

            isolation = self.isolation_available()
            mode = audio_schema.effective_privacy_mode(config, isolation_available=isolation)
            privacy = audio_schema.voice_privacy_of(config)

            self._mode = mode
            self._keep_unmuted = tuple(privacy.get("keep_unmuted_apps") or ())
            self._lease_id = new_lease_id()
            self._muted = []
            self._key_held = False
            self._last_reason = reason

            if mode == audio_schema.PRIVACY_MODE_OFF:
                self._last_reason = "privacy_off"
                return self.status()

            self._held = True
            try:
                if mode == audio_schema.PRIVACY_MODE_ISOLATE:
                    self._engage_isolation()
                else:
                    self._engage_push_to_mute()
            except Exception as exc:
                logging.error("Voice privacy could not be engaged: %s", exc)
                self._last_reason = "engage_failed"
            return self.status()

    def _engage_isolation(self):
        guard = self.guard()
        outcome = guard.engage(
            keep_unmuted_apps=self._keep_unmuted,
            journal_write=self._journal_add,
        )
        self._muted = list(outcome.muted)
        self._last_reason = outcome.reason
        if outcome.failed:
            logging.warning(
                "Capture isolation could not mute %d stream(s); those applications can still hear the microphone.",
                len(outcome.failed),
            )
        # Watch for capture clients that start mid-recording. A failure to
        # watch is not a failure to isolate — the streams that existed at
        # acquire time are muted either way — so it is recorded, not raised.
        try:
            self._watch_stop = guard.watch(self._on_new_stream)
        except Exception as exc:
            logging.debug("Capture-stream watch could not start: %s", exc)
            self._watch_stop = None

    def _engage_push_to_mute(self):
        injector = self._push_to_mute_provider()
        if injector is None:
            self._last_reason = "push_to_mute_unavailable"
            return
        try:
            injector.hold_mute_key()
        except Exception as exc:
            logging.error("Push-to-mute hold failed: %s", exc)
            self._last_reason = "push_to_mute_failed"
            return
        self._key_held = True
        self._last_reason = "engaged"

    def _on_new_stream(self):
        """A capture client appeared while we hold the lease: mute it too.

        Re-running ``engage`` is deliberate rather than diffing against the
        event: the adapter already skips streams that are ours, allowlisted, or
        already muted — and the ones we muted a moment ago are in that last
        category — so a re-enumeration naturally yields exactly the arrivals.
        """
        with self._lock:
            if not self._held or self._mode != audio_schema.PRIVACY_MODE_ISOLATE:
                return
            guard = self._guard
            if guard is None:
                return
            try:
                outcome = guard.engage(
                    keep_unmuted_apps=self._keep_unmuted,
                    journal_write=self._journal_add,
                )
            except Exception as exc:
                logging.debug("Mid-recording capture isolation failed: %s", exc)
                return
            if outcome.muted:
                self._muted.extend(outcome.muted)
                logging.debug("Muted %d capture stream(s) that started mid-recording.", len(outcome.muted))

    # -- release -------------------------------------------------------

    def release(self, reason="stop") -> dict:
        """Put everything back. Idempotent, never raises, safe from any thread.

        Called from every stop path in the table at the top of this module,
        including several that can fire for the same recording. The second and
        later calls are no-ops that still report the last restoration's
        honesty.
        """
        with self._lock:
            if not self._held:
                return self.status()

            self._held = False
            complete = True

            if self._key_held:
                injector = self._push_to_mute_provider()
                try:
                    if injector is not None:
                        injector.release_mute_key()
                    else:
                        # The injector vanished between hold and release. The
                        # key is, as far as we know, still down.
                        complete = False
                except Exception as exc:
                    logging.error("Push-to-mute release failed: %s", exc)
                    complete = False
                self._key_held = False

            if self._muted:
                guard = self._guard
                if guard is None:
                    complete = False
                    logging.error("Capture isolation cannot be restored: the adapter is gone.")
                else:
                    try:
                        outcome = guard.restore(self._muted, journal_replace=self._journal_replace)
                        complete = complete and bool(outcome.complete)
                        self._last_reason = outcome.reason
                        if not outcome.complete:
                            logging.error(
                                "Voice privacy restore incomplete: %d capture stream(s) are still muted.",
                                len(outcome.failed),
                            )
                    except Exception as exc:
                        logging.error("Capture isolation restore failed: %s", exc)
                        complete = False
                self._muted = []

            self._stop_watching()

            if complete:
                # Only a fully successful restore may clear the journal;
                # otherwise the remainder stays on disk for the next startup.
                self._journal.clear()
            # Sticky: one incomplete restore keeps reporting until it is
            # acknowledged, so a later clean recording cannot paper over a
            # microphone we left muted in somebody else's application.
            self._restore_complete = self._restore_complete and complete
            self._mode = audio_schema.PRIVACY_MODE_OFF
            self._last_reason = reason if complete else "restore_incomplete"
            return self.status()

    def _stop_watching(self):
        """Tear the watcher down. Called with the lease lock held.

        The watcher thread takes that same lock in :meth:`_on_new_stream`, so
        it can be blocked on us while we try to join it. That is why the
        adapter's stop callable joins with a timeout rather than unbounded: the
        worst case is a one-second stall on release, after which the watcher
        wakes, sees the lease is no longer held, and does nothing. A blocking
        join here would be a deadlock.
        """
        stop = self._watch_stop
        self._watch_stop = None
        if stop is None:
            return
        try:
            stop()
        except Exception as exc:
            logging.debug("Capture-stream watch teardown failed: %s", exc)

    # -- journal callbacks ---------------------------------------------

    def _journal_add(self, plan) -> bool:
        """Persist ``already muted`` + ``about to mute``, before the mute.

        Returns True only when the record is durably on disk. The adapter
        refuses to mute anything on False, which is the rule that makes crash
        recovery total rather than mostly-total.
        """
        records = list(self._muted) + list(plan or [])
        written = self._journal.record(
            getattr(self._guard, "name", "unknown"), records, lease_id=self._lease_id
        )
        return bool(written)

    def _journal_replace(self, remaining) -> bool:
        remaining = list(remaining or [])
        if not remaining:
            return self._journal.clear()
        written = self._journal.record(
            getattr(self._guard, "name", "unknown"), remaining, lease_id=self._lease_id
        )
        return bool(written)


# --- process-wide singleton -------------------------------------------

_lease = None
_lease_lock = threading.Lock()


def get_lease() -> AudioPrivacyLease:
    """The one lease. Constructed on first use so importing this module never
    probes the audio server."""
    global _lease
    with _lease_lock:
        if _lease is None:
            _lease = AudioPrivacyLease()
        return _lease


def reset_lease_for_tests(lease=None) -> None:
    """Replace the singleton. Tests only — a released lease is left released,
    but a HELD one is released first so a test cannot leak a real mute."""
    global _lease
    with _lease_lock:
        if _lease is not None and _lease.is_held():
            try:
                _lease.release(reason="test_reset")
            except Exception:
                pass
        _lease = lease


def recover_on_startup(guard=None, journal=None) -> dict:
    """Undo a crashed lease's mutes. Call once, early, before audio opens."""
    from backend.platform.audio_privacy.journal import recover_pending

    return recover_pending(guard=guard, journal=journal)
