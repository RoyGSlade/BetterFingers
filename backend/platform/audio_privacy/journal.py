"""Crash-recovery journal for the audio privacy lease (D-0010, Wave 8B).

The failure this exists for: BetterFingers mutes another app's capture stream,
and then dies — a segfault in a native audio library, an OOM kill, a power
cut — before it can put the stream back. Nothing else on the system knows the
mute was ours, so the user's microphone stays dead in their meeting app until
they find the mixer themselves. That is the single worst outcome capture
isolation can produce, and it is worse than not shipping isolation at all.

The rule that prevents it, stated once:

    **The journal is written before the state changes, never after.**

:meth:`PrivacyJournal.record` is called with the streams we are *about* to
mute, and it does not return until the bytes are on disk (``fsync`` on the
file and on its directory). Only then does the adapter issue the first mute.
A crash at any instant therefore leaves a journal that is either empty (no
mute happened) or describes at least as much as was actually changed. Over-
describing is safe: restoring a stream that was never muted is a no-op.

**Content-free by construction.** A journal entry holds stream identifiers
(the audio server's own index and, where available, its non-reused serial), a
boolean prior mute state, a timestamp, and an adapter name. It holds no
application names, no window titles, no audio, no transcript, no user text.
:func:`sanitize_record` is the single chokepoint that enforces that shape on
both write and read, so a future adapter cannot widen it by accident.

**Recovered and cleared at startup**, once, before anything else touches
audio: :func:`recover_pending` reads the journal, asks the adapter to restore
what it lists, and clears the file. A journal that cannot be parsed is
discarded rather than retried forever — an unreadable journal describes
nothing we can safely act on.

Pure stdlib; the clock and the storage path are injectable, so every path
here is testable without touching a real user directory.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid

from backend.platform.audio_privacy.base import MutedStream, RestoreOutcome

JOURNAL_VERSION = 1
JOURNAL_FILENAME = "audio_privacy_journal.json"

# Keys allowed at the top level of a journal record. Anything else is dropped
# on both write and read — the allowlist is the privacy guarantee, not a
# comment claiming one.
_ALLOWED_KEYS = ("version", "lease_id", "adapter", "started_at", "streams")


def default_journal_path() -> str:
    """``<user data dir>/audio_privacy_journal.json``.

    Imported lazily so this module stays importable (and unit-testable) in a
    bare interpreter with no profile directory.
    """
    from utils import get_user_data_path

    return os.path.join(get_user_data_path(), JOURNAL_FILENAME)


def new_lease_id() -> str:
    """A random, content-free correlation id. Not derived from anything about
    the user, the machine, or what is being recorded."""
    return uuid.uuid4().hex


def sanitize_record(record) -> dict:
    """Normalize a journal record to the allowed, content-free shape.

    Applied on write (so nothing extra can be persisted) and on read (so a
    hand-edited or older file cannot smuggle anything into the restore path).
    Returns an empty dict when the record is unusable.
    """
    if not isinstance(record, dict):
        return {}

    adapter = record.get("adapter")
    if not isinstance(adapter, str) or not adapter:
        return {}

    streams = []
    raw_streams = record.get("streams")
    if isinstance(raw_streams, (list, tuple)):
        for item in raw_streams:
            stream = MutedStream.from_record(item)
            if stream is not None:
                streams.append(stream.as_record())

    started_at = record.get("started_at")
    if not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
        started_at = 0.0

    lease_id = record.get("lease_id")
    if not isinstance(lease_id, str):
        lease_id = ""

    return {
        "version": JOURNAL_VERSION,
        "lease_id": lease_id[:64],
        "adapter": adapter[:64],
        "started_at": float(started_at),
        "streams": streams,
    }


class PrivacyJournal:
    """A single-file, write-before-change journal.

    Not thread-safe by itself; the lease serializes access under its own lock,
    which is also the only place that knows when a write is required.
    """

    def __init__(self, path=None, clock=None):
        self._path = path
        self._clock = clock or time.time

    # -- location ------------------------------------------------------

    def path(self) -> str:
        if self._path is None:
            self._path = default_journal_path()
        return self._path

    def exists(self) -> bool:
        try:
            return os.path.exists(self.path())
        except Exception:
            return False

    # -- writing -------------------------------------------------------

    def record(self, adapter, muted_streams, lease_id=None) -> dict:
        """Persist the streams we are about to mute, durably, before we do.

        Returns the record actually written. Raises nothing: a journal that
        cannot be written is logged and reported by returning an empty dict,
        and the lease treats that as "do not engage isolation" — muting
        without a recovery record is exactly the situation this module exists
        to prevent.
        """
        payload = sanitize_record({
            "adapter": adapter,
            "lease_id": lease_id or new_lease_id(),
            "started_at": float(self._clock()),
            "streams": [
                s.as_record() if isinstance(s, MutedStream) else s
                for s in (muted_streams or [])
            ],
        })
        if not payload:
            return {}
        if self._write_atomic(payload):
            return payload
        return {}

    def _write_atomic(self, payload) -> bool:
        path = self.path()
        directory = os.path.dirname(path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            logging.error("Audio privacy journal directory is unusable: %s", exc)
            return False

        handle = None
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=".privacy-journal-", dir=directory)
            handle = os.fdopen(fd, "w", encoding="utf-8")
            json.dump(payload, handle)
            handle.flush()
            # The durability that makes "written before the change" true: a
            # buffered write that is still in the page cache when the machine
            # loses power would leave the mute with no record of itself.
            os.fsync(handle.fileno())
            handle.close()
            handle = None
            os.replace(tmp_path, path)
            tmp_path = ""
            self._fsync_dir(directory)
            return True
        except (OSError, TypeError, ValueError) as exc:
            logging.error("Audio privacy journal write failed: %s", exc)
            return False
        finally:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _fsync_dir(directory) -> None:
        """Make the rename itself durable. Best-effort: directory fsync is not
        available on every filesystem or platform, and failing it is not a
        reason to refuse the whole operation."""
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    # -- reading / clearing --------------------------------------------

    def read(self) -> dict:
        """The pending record, or an empty dict when there is none.

        A corrupt or truncated file returns empty *and is left in place* for
        :meth:`clear` to remove — silently deleting a file we failed to parse
        would hide a real bug in the write path.
        """
        try:
            with open(self.path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logging.warning("Audio privacy journal is unreadable; discarding it: %s", exc)
            return {}
        return sanitize_record(data)

    def pending_streams(self) -> list:
        """The recorded streams as :class:`MutedStream` objects."""
        record = self.read()
        streams = []
        for item in record.get("streams", []):
            stream = MutedStream.from_record(item)
            if stream is not None:
                streams.append(stream)
        return streams

    def clear(self) -> bool:
        """Remove the journal. Idempotent; True when nothing is left behind."""
        path = self.path()
        try:
            os.remove(path)
        except FileNotFoundError:
            return True
        except OSError as exc:
            logging.error("Audio privacy journal could not be cleared: %s", exc)
            return False
        self._fsync_dir(os.path.dirname(path) or ".")
        return True


def recover_pending(guard=None, journal=None) -> dict:
    """Undo a crashed lease's mutes, then clear the journal. Call once at
    startup, before anything else opens audio.

    Returns a summary dict — counts and reasons only, no identifiers — so a
    caller can log it or put it in a status route:

        ``{"recovered": bool, "streams": int, "outcome": {...}, "reason": str}``

    The journal is cleared in every terminating case, including a failed
    restore. Retrying forever across restarts would mean an unrestorable
    stream (its app has long since exited) permanently blocks the feature; the
    failure is reported instead, which is what ``partially_restored`` is for.

    ``guard`` is resolved by live detection when omitted. An adapter that is
    no longer available (the user switched from PulseAudio to something else)
    cannot restore anything, and the journal is cleared with that stated:
    holding a record we can never act on is not caution, it is a leak.
    """
    journal = journal if journal is not None else PrivacyJournal()
    record = journal.read()

    if not record:
        if journal.exists():
            # Present but unparseable — remove it and say so.
            journal.clear()
            return {"recovered": False, "streams": 0, "reason": "unreadable_journal", "outcome": {}}
        return {"recovered": False, "streams": 0, "reason": "no_journal", "outcome": {}}

    streams = [
        stream for stream in (MutedStream.from_record(item) for item in record.get("streams", []))
        if stream is not None
    ]

    if not streams:
        journal.clear()
        return {"recovered": True, "streams": 0, "reason": "nothing_to_restore", "outcome": {}}

    if guard is None:
        from backend.platform.audio_privacy.base import detect_guard

        guard = detect_guard()

    adapter = record.get("adapter", "")
    if getattr(guard, "name", "") != adapter or not guard.is_available():
        logging.warning(
            "Audio privacy journal was written by adapter '%s', which is not available now; "
            "%d stream(s) cannot be restored automatically.",
            adapter, len(streams),
        )
        journal.clear()
        return {
            "recovered": False,
            "streams": len(streams),
            "reason": "adapter_unavailable",
            "outcome": {},
        }

    try:
        outcome = guard.restore(streams)
    except Exception as exc:  # pragma: no cover - adapters are defensive already
        logging.error("Audio privacy crash recovery failed: %s", exc)
        journal.clear()
        return {"recovered": False, "streams": len(streams), "reason": "restore_failed", "outcome": {}}

    journal.clear()
    logging.info(
        "Recovered a crashed audio privacy lease: %s",
        outcome.summary() if isinstance(outcome, RestoreOutcome) else outcome,
    )
    return {
        "recovered": bool(getattr(outcome, "complete", False)),
        "streams": len(streams),
        "reason": "recovered" if getattr(outcome, "complete", False) else "restore_incomplete",
        "outcome": outcome.summary() if isinstance(outcome, RestoreOutcome) else {},
    }
