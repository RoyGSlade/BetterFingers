"""The capture-isolation adapter contract (D-0010, Wave 8B).

Input voice privacy has two mechanisms with very different fidelity:

* **push-to-mute** — hold the key another voice app has bound to its own mute
  toggle. It works everywhere an input-injection tool works, it needs no audio
  permissions, and it is a guess: we do not know whether the key was bound, we
  do not know the app's prior state, and we cannot verify the result.
* **capture isolation** — ask the audio server which processes are capturing
  right now and mute exactly those, then put back exactly what we changed.
  Higher fidelity, and only possible where a capture-stream API exists.

This module owns the contract the second mechanism implements, plus the
vocabulary its results are reported in. It contains no platform code: the
Linux adapter is :mod:`.linux_pulse`, and Windows is a documented feasibility
design (:mod:`.windows_core_audio`) that stays unavailable until a spike
proves otherwise.

Three rules the contract exists to enforce, each of which was a real way to
get this wrong:

1. **Never mute ourselves.** BetterFingers is itself a capture client. An
   adapter identifies its own stream structurally (process identity + stream
   properties), never by matching a display name.
2. **Only restore what we changed.** ``engage`` returns the exact set of
   streams it muted, each with the state it had before. ``restore`` touches
   nothing else, and a stream that disappeared in between is not a failure —
   it is a stream that no longer needs restoring.
3. **A partial restore is reported, not swallowed.** :class:`RestoreOutcome`
   distinguishes "everything is back" from "some of it is not", which is
   exactly the distinction :mod:`audio_status`'s ``partially_restored``
   exists to surface.

Pure stdlib. Every adapter is constructed with its side-effecting calls
injected, so the whole contract is testable without an audio server.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

# Adapter identifiers. Stable strings — they are written into the journal and
# read back by a later process, so renaming one is a compatibility change.
ADAPTER_LINUX_PULSE = "linux_pulse"
ADAPTER_WINDOWS_CORE_AUDIO = "windows_core_audio"
ADAPTER_NULL = "null"

# Why an adapter is not available. Machine-readable; the renderer keys copy
# off these rather than parsing prose.
UNAVAILABLE_WRONG_PLATFORM = "wrong_platform"
UNAVAILABLE_TOOL_MISSING = "tool_missing"
UNAVAILABLE_SERVER_UNREACHABLE = "server_unreachable"
UNAVAILABLE_NO_STRUCTURED_OUTPUT = "no_structured_output"
UNAVAILABLE_NOT_IMPLEMENTED = "not_implemented"
AVAILABLE = "available"


@dataclass(frozen=True)
class CaptureStream:
    """One capture client, as the adapter sees it.

    ``key`` is the adapter's own stable handle for the stream (a PulseAudio
    source-output index, for example). ``serial`` is an optional
    never-reused-within-a-session counter: where the audio server provides one
    it makes journal recovery safe against index reuse, and where it does not
    the recovery path degrades to a documented best-effort check.

    ``labels`` holds the human-facing names (application name, binary,
    media name). They exist for exactly one purpose — matching the user's
    ``keep_unmuted_apps`` allowlist, which is a list of names the user typed —
    and are never used to decide whether a stream is ours.
    """

    key: str
    muted: bool
    is_self: bool = False
    serial: Optional[int] = None
    labels: tuple = ()

    def matches_allowlist(self, allowlist) -> bool:
        """True when the user asked for this stream to be left alone.

        Case-insensitive substring match in both directions, because a user
        types "discord" for a stream labelled "Discord" and types
        "Google Chrome" for one labelled "chrome". Names are a poor identifier
        and that is precisely why they are confined to this one function.
        """
        if not allowlist:
            return False
        wanted = [str(item).strip().lower() for item in allowlist if str(item).strip()]
        for label in self.labels:
            text = str(label or "").strip().lower()
            if not text:
                continue
            for item in wanted:
                if item in text or text in item:
                    return True
        return False


@dataclass(frozen=True)
class MutedStream:
    """A stream this process muted, and the state to put back."""

    key: str
    prior_muted: bool
    serial: Optional[int] = None

    def as_record(self) -> dict:
        """The content-free shape written to the journal: identifiers and a
        boolean, never a name, never audio."""
        record = {"key": self.key, "prior_muted": bool(self.prior_muted)}
        if self.serial is not None:
            record["serial"] = int(self.serial)
        return record

    @classmethod
    def from_record(cls, record) -> Optional["MutedStream"]:
        if not isinstance(record, dict):
            return None
        key = record.get("key")
        if not isinstance(key, str) or not key:
            return None
        serial = record.get("serial")
        return cls(
            key=key,
            prior_muted=bool(record.get("prior_muted", False)),
            serial=int(serial) if isinstance(serial, int) else None,
        )


@dataclass
class EngageOutcome:
    """What :meth:`PrivacyGuard.engage` actually did."""

    ok: bool = False
    muted: list = field(default_factory=list)      # list[MutedStream]
    skipped_self: int = 0
    skipped_allowlisted: int = 0
    skipped_already_muted: int = 0
    failed: list = field(default_factory=list)     # list[str] stream keys
    reason: str = ""

    def summary(self) -> dict:
        """Counts only — safe to log and safe to put in a status route."""
        return {
            "ok": bool(self.ok),
            "muted": len(self.muted),
            "failed": len(self.failed),
            "skipped_self": int(self.skipped_self),
            "skipped_allowlisted": int(self.skipped_allowlisted),
            "skipped_already_muted": int(self.skipped_already_muted),
            "reason": self.reason,
        }


@dataclass
class RestoreOutcome:
    """What :meth:`PrivacyGuard.restore` put back.

    ``complete`` is the single fact :mod:`audio_status` needs: False is the
    ``partially_restored`` case. A stream that vanished counts as ``gone``,
    not ``failed`` — there is nothing left to restore, so the restore is still
    complete.
    """

    complete: bool = True
    restored: int = 0
    gone: int = 0
    failed: list = field(default_factory=list)     # list[str] stream keys
    reason: str = ""

    def summary(self) -> dict:
        return {
            "complete": bool(self.complete),
            "restored": int(self.restored),
            "gone": int(self.gone),
            "failed": len(self.failed),
            "reason": self.reason,
        }


class PrivacyGuard:
    """Adapter contract. Subclasses implement the three platform verbs.

    Lifecycle, and the order is the point: ``availability()`` is asked before
    anything is promised to the user, ``engage()`` writes the journal BEFORE
    it changes any state (the guard is handed a ``journal_write`` callable so
    the ordering cannot be got wrong by an adapter), and ``restore()`` is
    called on every stop path including one that starts in a later process.
    """

    name = ADAPTER_NULL

    def availability(self) -> tuple:
        """Return ``(available: bool, reason: str)`` from live detection.

        Must be cheap enough to call per recording and must never raise: a
        detection failure is an unavailable adapter, not a crash.
        """
        return False, UNAVAILABLE_NOT_IMPLEMENTED

    def is_available(self) -> bool:
        try:
            return bool(self.availability()[0])
        except Exception as exc:  # pragma: no cover - defensive
            logging.debug("Privacy guard availability probe failed: %s", exc)
            return False

    def list_streams(self) -> list:
        """Every capture stream the audio server currently reports."""
        return []

    def engage(self, keep_unmuted_apps=(), journal_write=None) -> EngageOutcome:
        """Mute every currently-unmuted capture stream that is not ours and
        not allowlisted, recording the prior state of each.

        ``journal_write`` is called with the list of :class:`MutedStream`
        records this call is ABOUT TO mute, before the first mute is applied,
        and returns True once they are durably recorded. It is an *add*
        callback: the owner merges the plan into whatever it already holds, so
        a second engage during the same lease (a stream that appeared
        mid-recording) extends the record instead of replacing it.
        """
        raise NotImplementedError

    def restore(self, muted_streams, journal_replace=None) -> RestoreOutcome:
        """Put back exactly the streams in ``muted_streams``.

        ``journal_replace`` is a *replace* callback — it is called with the
        records still outstanding after the attempt (empty on a complete
        restore), so a crash midway through a partial restore leaves a journal
        describing exactly the remainder.
        """
        raise NotImplementedError

    def watch(self, on_new_stream) -> Optional[Callable[[], None]]:
        """Subscribe to stream creation while a lease is held.

        Returns a zero-argument stop callable, or None when the adapter
        cannot watch. ``on_new_stream`` is called with no arguments; the
        listener is expected to re-enumerate rather than trust an event
        payload, because the event only says "something changed".
        """
        return None


class NullPrivacyGuard(PrivacyGuard):
    """The honest no-op: available nowhere, does nothing, restores nothing.

    Used on every platform without an adapter so the lease has one code path
    instead of a None check at every call site.
    """

    name = ADAPTER_NULL

    def __init__(self, reason=UNAVAILABLE_WRONG_PLATFORM):
        self._reason = reason

    def availability(self) -> tuple:
        return False, self._reason

    def list_streams(self) -> list:
        return []

    def engage(self, keep_unmuted_apps=(), journal_write=None) -> EngageOutcome:
        del keep_unmuted_apps, journal_write
        return EngageOutcome(ok=False, reason=self._reason)

    def restore(self, muted_streams, journal_replace=None) -> RestoreOutcome:
        del journal_replace
        # Nothing was ever muted by this guard, so there is nothing to fail at.
        return RestoreOutcome(complete=True, gone=len(list(muted_streams or [])), reason=self._reason)


def detect_guard(platform_name=None, factories=None) -> PrivacyGuard:
    """Return the best capture-isolation adapter for this machine.

    Detection is *runtime*, not compile-time: being on Linux is not enough,
    the adapter must prove pactl exists and a Pulse-compatible server answers.
    Anything short of proof returns a :class:`NullPrivacyGuard` carrying the
    reason, which is what makes ``isolate_capture_streams`` degrade visibly to
    push-to-mute instead of silently doing nothing.

    ``factories`` is injectable so tests can drive every branch without an
    audio server; it maps a platform prefix to a zero-argument constructor.
    """
    import sys

    system = str(platform_name if platform_name is not None else sys.platform).lower()

    if factories is None:
        factories = _default_factories()

    for prefix, factory in factories.items():
        if system.startswith(prefix):
            try:
                guard = factory()
            except Exception as exc:
                logging.debug("Capture-isolation adapter construction failed: %s", exc)
                return NullPrivacyGuard(UNAVAILABLE_TOOL_MISSING)
            available, reason = guard.availability()
            if available:
                return guard
            return NullPrivacyGuard(reason)

    return NullPrivacyGuard(UNAVAILABLE_WRONG_PLATFORM)


def _default_factories() -> dict:
    def _linux():
        from backend.platform.audio_privacy import linux_pulse

        return linux_pulse.LinuxPulsePrivacyGuard()

    def _windows():
        from backend.platform.audio_privacy import windows_core_audio

        return windows_core_audio.WindowsCoreAudioPrivacyGuard()

    return {"linux": _linux, "win": _windows}
