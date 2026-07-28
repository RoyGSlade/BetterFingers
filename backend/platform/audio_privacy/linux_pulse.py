"""Linux capture isolation over PulseAudio / PipeWire's Pulse server (D-0010).

While BetterFingers is recording, every other application that is *also*
capturing the microphone keeps hearing the user. Push-to-mute guesses at that
by holding a key the other app may or may not have bound. This adapter does
the real thing: it asks the audio server which processes are capturing right
now, mutes exactly those, and puts back exactly what it changed.

**Structured output only, never name matching.** Every enumeration goes
through ``pactl -f json list source-outputs`` and is parsed as JSON. There is
no ``grep``, no ``awk``, and no parsing of pactl's human-readable listing
anywhere in this module, for two reasons that are worth stating plainly:

1. The human-readable format is a UI, not an API — its indentation and field
   order have changed between pactl releases and are localized.
2. **Application names are not identifiers.** Two streams can share a name,
   a name can be empty, and a name can be chosen by the application to be
   anything at all. Deciding "is this BetterFingers?" by comparing a display
   string is how an isolation feature ends up muting the user's own
   microphone — or, worse, silently missing the app it was supposed to mute.

So the two structural questions are answered structurally:

* **Is this stream ours?** By process identity: the stream's
  ``application.process.id``, checked against this process and its
  descendants by walking ``/proc``. Never by name.
* **Which stream is which, later?** By the server's own ``index``, paired
  with ``object.serial`` where the server provides one. A serial is
  monotonic within a server session and never reused, so it is what makes
  journal recovery safe against index reuse after a stream exits.

Names appear in exactly one place — matching the user's
``voice_privacy.keep_unmuted_apps`` allowlist — because that list *is* a list
of names the user typed. That is a deliberate, documented exception, confined
to :meth:`base.CaptureStream.matches_allowlist`.

**Only what we changed.** A stream that is already muted is left alone and
not recorded (restoring it would unmute something the user muted themselves).
A stream that disappears before restore is not a failure. Restore never mutes
anything, only unmutes what the journal says we muted.

**New streams during a recording.** ``pactl subscribe`` is a long-lived
event stream; the watcher treats each event as "something changed, go look"
and re-enumerates rather than trusting the event payload, so a new capture
client that starts mid-recording is muted too, and joins the journal.

Every subprocess call goes through an injected runner, so the whole adapter
is unit-testable with no pactl, no audio server, and no side effects.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading

from backend.platform.audio_privacy.base import (
    ADAPTER_LINUX_PULSE,
    AVAILABLE,
    CaptureStream,
    EngageOutcome,
    MutedStream,
    PrivacyGuard,
    RestoreOutcome,
    UNAVAILABLE_NO_STRUCTURED_OUTPUT,
    UNAVAILABLE_SERVER_UNREACHABLE,
    UNAVAILABLE_TOOL_MISSING,
)

# pactl is fast; these bound a hung audio server rather than a slow one. A
# recording start must not block on a wedged PulseAudio.
PROBE_TIMEOUT_S = 2.0
COMMAND_TIMEOUT_S = 2.0

# Properties read off a source-output. Structural identity first, then the
# display labels used only for the user's allowlist.
_PROP_PID = "application.process.id"
_PROP_SERIAL = "object.serial"
_LABEL_PROPS = ("application.name", "application.process.binary", "media.name")


def _default_runner(args, timeout=COMMAND_TIMEOUT_S):
    """Run a pactl command. Returns ``(returncode, stdout, stderr)``.

    Never raises: a missing binary, a timeout, or a crashed server all come
    back as a non-zero return code, because every caller's correct response to
    all three is the same — treat isolation as unavailable.
    """
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""
    except FileNotFoundError:
        return 127, "", "pactl not found"
    except subprocess.TimeoutExpired:
        return 124, "", "pactl timed out"
    except OSError as exc:
        return 1, "", str(exc)


def _own_pid_set():
    """This process id. Kept as a set so the descendant walk has one origin
    and tests can inject a different identity."""
    return {os.getpid()}


def _is_descendant_of(pid, ancestors, proc_root="/proc", max_depth=32):
    """True when ``pid`` is one of ``ancestors`` or a descendant of one.

    Walks the ``PPid`` chain in ``/proc/<pid>/status``. Bounded depth so a
    malformed or cyclic chain cannot spin. A pid that has already exited, or a
    system without ``/proc``, answers False — which errs toward treating the
    stream as somebody else's and therefore mutable. That is the safe
    direction for a privacy feature: the cost of a wrong False is that we mute
    a stream and restore it a moment later; the cost of a wrong True is that
    another app keeps hearing the user.
    """
    if pid is None:
        return False
    if pid in ancestors:
        return True
    current = pid
    for _ in range(max_depth):
        try:
            with open(os.path.join(proc_root, str(current), "status"), "r", encoding="utf-8") as handle:
                parent = None
                for line in handle:
                    if line.startswith("PPid:"):
                        parent = int(line.split(":", 1)[1].strip())
                        break
        except (OSError, ValueError):
            return False
        if parent is None or parent <= 0:
            return False
        if parent in ancestors:
            return True
        current = parent
    return False


def _coerce_pid(value):
    try:
        pid = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _coerce_serial(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_mute(value):
    """pactl's JSON emits a real boolean; older/odd builds have emitted
    ``"yes"``/``"no"``. Accept both, and treat anything unrecognized as
    unmuted — a stream we wrongly believe is muted would be skipped, i.e.
    left listening, which is the failure this feature exists to prevent."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in ("yes", "true", "1", "on")


class LinuxPulsePrivacyGuard(PrivacyGuard):
    """Capture isolation via ``pactl`` against a Pulse-compatible server.

    Works on PulseAudio and on PipeWire's ``pipewire-pulse`` shim; the adapter
    does not care which is behind the socket, only that the structured
    interface answers. That is checked at runtime, per
    :meth:`availability` — being on Linux proves nothing.
    """

    name = ADAPTER_LINUX_PULSE

    def __init__(self, runner=None, pactl_path=None, own_pids=None, proc_root="/proc",
                 popen=None):
        self._runner = runner or _default_runner
        self._pactl = pactl_path
        self._own_pids = set(own_pids) if own_pids is not None else _own_pid_set()
        self._proc_root = proc_root
        self._popen = popen or subprocess.Popen
        self._pactl_resolved = pactl_path is not None

    # -- detection -----------------------------------------------------

    def _binary(self):
        if not self._pactl_resolved:
            self._pactl = shutil.which("pactl")
            self._pactl_resolved = True
        return self._pactl

    def availability(self) -> tuple:
        """Runtime proof, in three steps, each of which can fail independently:
        the binary exists, a server answers, and it speaks structured JSON.

        The third step matters on its own: ``pactl`` gained ``-f json`` in
        version 16. An older pactl talking to a healthy server would pass the
        first two checks and then hand us a localized text listing, and the one
        thing this adapter must never do is parse that.
        """
        binary = self._binary()
        if not binary:
            return False, UNAVAILABLE_TOOL_MISSING

        code, _out, _err = self._runner([binary, "info"], timeout=PROBE_TIMEOUT_S)
        if code != 0:
            return False, UNAVAILABLE_SERVER_UNREACHABLE

        code, out, _err = self._runner(
            [binary, "-f", "json", "list", "source-outputs"], timeout=PROBE_TIMEOUT_S
        )
        if code != 0:
            return False, UNAVAILABLE_NO_STRUCTURED_OUTPUT
        try:
            parsed = json.loads(out or "[]")
        except ValueError:
            return False, UNAVAILABLE_NO_STRUCTURED_OUTPUT
        if not isinstance(parsed, list):
            return False, UNAVAILABLE_NO_STRUCTURED_OUTPUT

        return True, AVAILABLE

    # -- enumeration ---------------------------------------------------

    def list_streams(self) -> list:
        """Every capture stream the server currently reports, as
        :class:`CaptureStream`. An unparseable answer yields an empty list —
        never a partially-guessed one."""
        binary = self._binary()
        if not binary:
            return []
        code, out, err = self._runner(
            [binary, "-f", "json", "list", "source-outputs"], timeout=COMMAND_TIMEOUT_S
        )
        if code != 0:
            logging.debug("pactl source-output enumeration failed (%s): %s", code, err.strip()[:200])
            return []
        try:
            parsed = json.loads(out or "[]")
        except ValueError as exc:
            logging.debug("pactl JSON output was unparseable: %s", exc)
            return []
        if not isinstance(parsed, list):
            return []

        streams = []
        for entry in parsed:
            stream = self._to_stream(entry)
            if stream is not None:
                streams.append(stream)
        return streams

    def _to_stream(self, entry):
        if not isinstance(entry, dict):
            return None
        index = entry.get("index")
        if index is None:
            return None
        properties = entry.get("properties")
        properties = properties if isinstance(properties, dict) else {}

        pid = _coerce_pid(properties.get(_PROP_PID))
        labels = tuple(
            str(properties.get(prop))
            for prop in _LABEL_PROPS
            if isinstance(properties.get(prop), str) and properties.get(prop).strip()
        )
        return CaptureStream(
            key=str(index),
            muted=_coerce_mute(entry.get("mute")),
            is_self=_is_descendant_of(pid, self._own_pids, proc_root=self._proc_root),
            serial=_coerce_serial(properties.get(_PROP_SERIAL)),
            labels=labels,
        )

    # -- mutation ------------------------------------------------------

    def _set_mute(self, key, muted) -> bool:
        binary = self._binary()
        if not binary:
            return False
        code, _out, err = self._runner(
            [binary, "set-source-output-mute", str(key), "1" if muted else "0"],
            timeout=COMMAND_TIMEOUT_S,
        )
        if code != 0:
            logging.warning(
                "Failed to %s capture stream %s: %s",
                "mute" if muted else "unmute", key, err.strip()[:200],
            )
            return False
        return True

    def engage(self, keep_unmuted_apps=(), journal_write=None) -> EngageOutcome:
        """Mute every currently-unmuted, non-ours, non-allowlisted stream.

        Journal-before-change is enforced here, not in the caller: the whole
        plan is written through ``journal_write`` and must be persisted before
        the first ``set-source-output-mute`` is issued. A journal that refuses
        to persist aborts the engagement rather than muting without a recovery
        record.
        """
        outcome = EngageOutcome()
        streams = self.list_streams()

        plan = []
        for stream in streams:
            if stream.is_self:
                outcome.skipped_self += 1
                continue
            if stream.matches_allowlist(keep_unmuted_apps):
                outcome.skipped_allowlisted += 1
                continue
            if stream.muted:
                # Already muted by the user or by the app itself. Not ours to
                # change, and therefore not ours to restore later.
                outcome.skipped_already_muted += 1
                continue
            plan.append(MutedStream(key=stream.key, prior_muted=False, serial=stream.serial))

        if not plan:
            outcome.ok = True
            outcome.reason = "nothing_to_mute"
            return outcome

        if journal_write is not None and not journal_write(plan):
            outcome.ok = False
            outcome.reason = "journal_write_failed"
            logging.error(
                "Refusing to mute %d capture stream(s): the privacy journal could not be written.",
                len(plan),
            )
            return outcome

        for entry in plan:
            if self._set_mute(entry.key, True):
                outcome.muted.append(entry)
            else:
                outcome.failed.append(entry.key)

        outcome.ok = bool(outcome.muted) or not outcome.failed
        outcome.reason = "engaged" if outcome.ok else "mute_failed"
        return outcome

    def restore(self, muted_streams, journal_replace=None) -> RestoreOutcome:
        """Put back exactly the recorded streams, and nothing else.

        A stream whose index is gone is counted as ``gone``, not failed. Where
        the record carries a ``serial`` and the live stream carries a
        different one, the index has been reused by a different stream since —
        so the one we muted is gone, and touching the new occupant would be
        changing something we never changed.
        """
        entries = [s for s in (muted_streams or []) if isinstance(s, MutedStream)]
        outcome = RestoreOutcome()
        if not entries:
            outcome.reason = "nothing_to_restore"
            return outcome

        live = {stream.key: stream for stream in self.list_streams()}

        for entry in entries:
            current = live.get(entry.key)
            if current is None:
                outcome.gone += 1
                continue
            if entry.serial is not None and current.serial is not None and entry.serial != current.serial:
                # Index reused by a different stream: ours exited.
                outcome.gone += 1
                continue
            if current.muted == entry.prior_muted:
                # Already back where it started (the app restored itself, or a
                # previous restore attempt succeeded). Nothing to do.
                outcome.restored += 1
                continue
            if self._set_mute(entry.key, entry.prior_muted):
                outcome.restored += 1
            else:
                outcome.failed.append(entry.key)

        outcome.complete = not outcome.failed
        outcome.reason = "restored" if outcome.complete else "restore_incomplete"

        if journal_replace is not None:
            # Leave the journal describing only what is still outstanding, so
            # a crash during a partial restore does not lose the remainder.
            remaining = [e for e in entries if e.key in set(outcome.failed)]
            journal_replace(remaining)

        return outcome

    # -- watching ------------------------------------------------------

    def watch(self, on_new_stream):
        """Follow ``pactl subscribe`` and call ``on_new_stream`` when a capture
        stream appears.

        The event line is used only as a trigger — the callback re-enumerates
        through the JSON path rather than trusting anything parsed out of the
        event text. Returns a stop callable, or None when the watcher could
        not be started (isolation still works for the streams that existed at
        engage time; only mid-recording arrivals are missed, and the caller
        reports that rather than pretending).
        """
        binary = self._binary()
        if not binary:
            return None

        try:
            process = self._popen(
                [binary, "subscribe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            logging.warning("Could not watch for new capture streams: %s", exc)
            return None

        stop_event = threading.Event()

        def _pump():
            try:
                stdout = process.stdout
                if stdout is None:
                    return
                for line in stdout:
                    if stop_event.is_set():
                        break
                    # "Event 'new' on source-output #42" — matched on the two
                    # fixed tokens pactl's event grammar guarantees, not on any
                    # application-supplied text.
                    if "source-output" not in line:
                        continue
                    if "'new'" not in line and "'change'" not in line:
                        continue
                    try:
                        on_new_stream()
                    except Exception as exc:
                        logging.debug("New-capture-stream handler failed: %s", exc)
            except Exception as exc:  # pragma: no cover - stream teardown races
                logging.debug("Capture-stream watcher ended: %s", exc)

        thread = threading.Thread(target=_pump, name="capture-stream-watch", daemon=True)
        thread.start()

        def _stop():
            stop_event.set()
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.wait(timeout=1.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            thread.join(timeout=1.0)

        return _stop
