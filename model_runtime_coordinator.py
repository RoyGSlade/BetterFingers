"""Read/write lease coordinator for model runtimes (STT, LLM, TTS).

The global model singletons were loaded, used, reloaded, and unloaded through
bare module globals with no shared lifecycle lock — so a destructive operation
(unload / reload / delete / select) could drop a runtime out from under an
in-flight inference: LLM shutdown while a request awaits llama-server, Whisper
reload during transcription, TTS unload mid-playback.

This coordinator gives each runtime a classic multiple-reader / single-writer
lease:
- Inference takes a **read lease** (many concurrent).
- A destructive op takes a **write lease** (exclusive). By default it does not
  block: if any read lease is active it fails fast so the caller can return
  HTTP 409 instead of racing. An explicit cancel-and-wait mode signals readers
  and waits for them to drain.

Pure threading + a small state machine, no server imports — unit-tested in
``tests/test_model_runtime_coordinator.py``.
"""

import contextlib
import threading
import time

# Explicit lifecycle states surfaced in diagnostics.
UNLOADED = "unloaded"
LOADING = "loading"
READY = "ready"
BUSY = "busy"
UNLOADING = "unloading"
FAILED = "failed"


class RuntimeBusyError(RuntimeError):
    """Raised when an exclusive op cannot proceed because inference is active."""


class _Runtime:
    def __init__(self, name):
        self.name = name
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._cancel = threading.Event()  # asks active readers to bail out
        self.state = UNLOADED

    # -- read (inference) ---------------------------------------------------
    def acquire_read(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._writer:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cond.wait(remaining)
            self._readers += 1
            if self.state in (READY, UNLOADED):
                self.state = BUSY
            return True

    def release_read(self):
        with self._cond:
            if self._readers > 0:
                self._readers -= 1
            if self._readers == 0 and not self._writer:
                self.state = READY
            self._cond.notify_all()

    # -- write (destructive) ------------------------------------------------
    def acquire_write(self, wait=False, timeout=10.0):
        with self._cond:
            if not wait:
                if self._readers > 0 or self._writer:
                    return False
                self._writer = True
                self.state = UNLOADING
                return True
            # cancel-and-wait: signal readers, wait for them to drain.
            self._cancel.set()
            deadline = time.monotonic() + timeout
            while self._readers > 0 or self._writer:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._cancel.clear()
                    return False
                self._cond.wait(remaining)
            self._cancel.clear()
            self._writer = True
            self.state = UNLOADING
            return True

    def release_write(self, new_state=UNLOADED):
        with self._cond:
            self._writer = False
            self.state = new_state
            self._cond.notify_all()

    def snapshot(self):
        with self._cond:
            return {
                "runtime": self.name,
                "state": self.state,
                "readers": self._readers,
                "writer": self._writer,
                "cancel_requested": self._cancel.is_set(),
            }

    @property
    def cancel_requested(self):
        return self._cancel.is_set()


class ModelRuntimeCoordinator:
    def __init__(self, names=("stt", "llm", "tts")):
        self._runtimes = {name: _Runtime(name) for name in names}

    def _runtime(self, name):
        try:
            return self._runtimes[name]
        except KeyError:
            raise KeyError(f"Unknown runtime {name!r}")

    @contextlib.contextmanager
    def read_lease(self, name, timeout=None):
        """Hold a read (inference) lease for the duration of the block."""
        rt = self._runtime(name)
        if not rt.acquire_read(timeout=timeout):
            raise RuntimeBusyError(f"{name} runtime is being reconfigured")
        try:
            yield rt
        finally:
            rt.release_read()

    @contextlib.contextmanager
    def write_lease(self, name, wait=False, timeout=10.0):
        """Hold an exclusive (destructive) lease. Raises RuntimeBusyError when
        inference is active and ``wait`` is False — map that to HTTP 409."""
        rt = self._runtime(name)
        if not rt.acquire_write(wait=wait, timeout=timeout):
            raise RuntimeBusyError(f"{name} runtime is in use by active inference")
        new_state = UNLOADED
        try:
            yield rt
        except Exception:
            new_state = FAILED
            raise
        finally:
            rt.release_write(new_state=new_state)

    def set_state(self, name, state):
        rt = self._runtime(name)
        with rt._cond:
            rt.state = state

    def is_busy(self, name):
        rt = self._runtime(name)
        with rt._cond:
            return rt._readers > 0 or rt._writer

    def active_leases(self):
        """For /health and /jobs: every runtime with active work."""
        out = []
        for rt in self._runtimes.values():
            snap = rt.snapshot()
            if snap["readers"] or snap["writer"]:
                out.append(snap)
        return out

    def snapshot_all(self):
        return [rt.snapshot() for rt in self._runtimes.values()]
