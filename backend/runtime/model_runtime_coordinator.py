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

It also owns a small resource ledger + admission control (DESIGN.md M6): each
loaded component reports its estimated resident MB via ``note_loaded``; before
a load site allocates real memory it calls ``request_admission`` to check the
load fits the RAM floor, evicting idle/non-pinned components (LRU) through
their registered evictor when it doesn't. This never OOM-crashes the app —
a load that still doesn't fit after evicting everything evictable is refused
with a payload naming the resident models, not a crash.

Pure threading + a small state machine, no server imports — unit-tested in
``tests/test_model_runtime_coordinator.py`` and
``tests/test_model_admission.py``.
"""

import contextlib
import logging
import os
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


# Default RAM safety floor kept free below `available_mb` after a load;
# overridable per-deployment since laptops vs. workstations differ a lot.
DEFAULT_RAM_FLOOR_MB = 1500

# Idle-unload defaults (seconds) for the coordinator-level sweep. TTS is
# excluded — it already self-manages an idle-unload window (see
# tts_engine.py's sentinel timer) and the coordinator must not double-free it.
_DEFAULT_IDLE_UNLOAD_SEC = {"llm": 300.0, "stt": 300.0}
_IDLE_SWEEP_INTERVAL_SEC = 5.0


def _psutil_available_mb():
    """Cheap RAM probe: psutil only, no GPU/subprocess detection. Admission
    checks can run several times in one load (once per eviction), so this
    deliberately skips hardware_report.get_hardware_report()'s nvidia-smi /
    lspci / llama-server --list-devices probes."""
    try:
        import psutil
    except Exception:
        return None
    try:
        return round(psutil.virtual_memory().available / (1024 * 1024))
    except Exception:
        return None


class _LedgerEntry:
    __slots__ = ("model_id", "estimated_mb", "loaded_at", "last_used", "pinned")

    def __init__(self, model_id, estimated_mb, pinned):
        now = time.monotonic()
        self.model_id = model_id
        self.estimated_mb = int(estimated_mb or 0)
        self.loaded_at = now
        self.last_used = now
        self.pinned = bool(pinned)

    def snapshot(self):
        return {
            "model_id": self.model_id,
            "estimated_mb": self.estimated_mb,
            "loaded_at": self.loaded_at,
            "last_used": self.last_used,
            "pinned": self.pinned,
        }


class ModelRuntimeCoordinator:
    def __init__(self, names=("stt", "llm", "tts"), available_mb_fn=None, ram_floor_mb=None):
        self._runtimes = {name: _Runtime(name) for name in names}
        self._ledger_lock = threading.Lock()
        self._ledger = {name: None for name in names}
        self._pinned = {name: False for name in names}
        self._evictors = {}
        self._available_mb_fn = available_mb_fn or _psutil_available_mb
        # None => read the env var fresh on every call (lets ops tune it live);
        # an explicit value (mainly for tests) pins it for this instance.
        self._ram_floor_mb = ram_floor_mb
        self._idle_thread = None
        self._idle_stop = threading.Event()

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
        self._touch(name)
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

    # -- resource ledger ------------------------------------------------

    def _touch(self, name):
        with self._ledger_lock:
            entry = self._ledger.get(name)
            if entry is not None:
                entry.last_used = time.monotonic()

    def set_pinned(self, name, pinned):
        """Mirror the profile's model_keep_*_loaded flag. A pinned component
        is never chosen for eviction (admission or idle sweep)."""
        self._runtime(name)
        with self._ledger_lock:
            self._pinned[name] = bool(pinned)
            entry = self._ledger.get(name)
            if entry is not None:
                entry.pinned = bool(pinned)

    def register_evictor(self, name, fn):
        """Register the zero-arg callable that actually frees `name`'s
        memory (e.g. server.py's `_unload_model_component_locked`). Must be
        idempotent — the coordinator may call it when the component is
        already unloaded (double-free-safe by construction, not by luck)."""
        self._runtime(name)
        self._evictors[name] = fn
        self._maybe_start_idle_sweep()

    def note_loaded(self, name, model_id, estimated_mb):
        """Record that `name` finished loading `model_id` at ~estimated_mb."""
        self._runtime(name)
        with self._ledger_lock:
            self._ledger[name] = _LedgerEntry(model_id, estimated_mb, self._pinned.get(name, False))

    def note_unloaded(self, name):
        self._runtime(name)
        with self._ledger_lock:
            self._ledger[name] = None

    def _evictable_candidates(self, exclude):
        with self._ledger_lock:
            items = [
                (n, e) for n, e in self._ledger.items()
                if e is not None and n != exclude and not e.pinned
            ]
        items.sort(key=lambda pair: pair[1].last_used)  # LRU first
        return items

    def _resident_snapshot(self):
        with self._ledger_lock:
            return [
                {"component": n, "model_id": e.model_id, "estimated_mb": e.estimated_mb, "pinned": e.pinned}
                for n, e in self._ledger.items() if e is not None
            ]

    def resources_snapshot(self):
        """The ledger + current headroom, for GET /models/resources."""
        with self._ledger_lock:
            ledger = {n: (e.snapshot() if e else None) for n, e in self._ledger.items()}
            pinned = dict(self._pinned)
        return {
            "ledger": ledger,
            "pinned": pinned,
            "available_mb": self._available_mb_fn(),
            "ram_floor_mb": self._ram_floor(),
        }

    def _ram_floor(self):
        if self._ram_floor_mb is not None:
            return self._ram_floor_mb
        try:
            return max(0, int(os.getenv("BETTERFINGERS_RAM_FLOOR_MB", "") or DEFAULT_RAM_FLOOR_MB))
        except (TypeError, ValueError):
            return DEFAULT_RAM_FLOOR_MB

    def _evict_component(self, name, evictor):
        """Run `evictor` for `name` under its write lease. Returns True if the
        write lease was acquired (evictor ran or was skipped as a no-op);
        False if the component is busy with active inference and must not be
        touched — never evict work that's in flight."""
        rt = self._runtime(name)
        if not rt.acquire_write(wait=False):
            return False
        new_state = UNLOADED
        try:
            evictor()
        except Exception as exc:
            logging.error("Eviction of %s failed: %s", name, exc)
            new_state = FAILED
        finally:
            rt.release_write(new_state=new_state)
        self.note_unloaded(name)
        return True

    # -- admission control ------------------------------------------------

    def request_admission(self, name, estimated_mb, model_id=None):
        """Check whether loading `estimated_mb` of `name` fits the RAM floor,
        evicting idle/non-pinned components (LRU) through their registered
        evictor when it doesn't. Never raises for a refusal — callers map the
        returned payload to a clean "unavailable" error, not a crash.

        Returns:
          {"allowed": bool, "evicted": [...],
           "available_mb_before": int|None, "available_mb_after": int|None,
           "refusal": None | {"message": str, "resident": [...],
                               "suggested_model_id": str|None}}
        """
        self._runtime(name)
        estimated_mb = int(estimated_mb or 0)
        floor = self._ram_floor()

        with self._ledger_lock:
            current = self._ledger.get(name)
            # A load site reloading/replacing its OWN already-resident model
            # (e.g. switching LLM checkpoints) will free that memory as part
            # of the load — credit it back so a same-size or smaller
            # replacement never refuses spuriously.
            self_credit = current.estimated_mb if current is not None else 0

        available = self._available_mb_fn()
        if available is None:
            # No RAM telemetry: never block a load on missing metrics.
            return {
                "allowed": True, "evicted": [],
                "available_mb_before": None, "available_mb_after": None,
                "refusal": None,
            }

        available_before = available
        projected = available + self_credit - estimated_mb
        evicted = []

        if projected < floor:
            for cand_name, entry in self._evictable_candidates(exclude=name):
                evictor = self._evictors.get(cand_name)
                if evictor is None:
                    continue
                freed_mb = entry.estimated_mb
                if not self._evict_component(cand_name, evictor):
                    continue  # busy with active inference; try the next LRU candidate
                evicted.append({"component": cand_name, "model_id": entry.model_id, "freed_mb": freed_mb})
                # Re-sample real available_mb — estimates drift from reality
                # (fragmentation, other processes); don't refuse a load that
                # eviction actually made room for.
                resampled = self._available_mb_fn()
                available = resampled if resampled is not None else available + freed_mb
                projected = available + self_credit - estimated_mb
                if projected >= floor:
                    break

        allowed = projected >= floor
        result = {
            "allowed": allowed,
            "evicted": evicted,
            "available_mb_before": available_before,
            "available_mb_after": available,
            "refusal": None,
        }
        if not allowed:
            resident = self._resident_snapshot()
            resident_desc = ", ".join(f"{r['component']}={r['model_id']}" for r in resident) or "nothing else"
            message = (
                f"Not enough RAM to load {name} (needs ~{estimated_mb} MB, "
                f"{available} MB free, floor {floor} MB). Resident: {resident_desc}."
            )
            suggested_model_id = None
            if name == "llm" and model_id:
                try:
                    from hardware_report import _suggest_lighter_model
                    suggested_model_id = _suggest_lighter_model(model_id, max(0, available + self_credit))
                except Exception as exc:
                    logging.debug("suggest_lighter_model failed: %s", exc)
            result["refusal"] = {
                "message": message,
                "resident": resident,
                "suggested_model_id": suggested_model_id,
            }
        return result

    # -- idle eviction sweep (llm/stt only; tts self-manages) -------------

    def _idle_timeout_sec(self, name):
        default = _DEFAULT_IDLE_UNLOAD_SEC.get(name, 0.0)
        env_name = f"BETTERFINGERS_{name.upper()}_IDLE_UNLOAD_SEC"
        try:
            return max(0.0, float(os.getenv(env_name, "") or default))
        except (TypeError, ValueError):
            return default

    def _maybe_start_idle_sweep(self):
        if self._idle_thread is not None:
            return
        if not any(n in _DEFAULT_IDLE_UNLOAD_SEC for n in self._evictors):
            return
        self._idle_stop.clear()
        t = threading.Thread(target=self._idle_sweep_loop, daemon=True, name="model-idle-sweep")
        self._idle_thread = t
        t.start()

    def _idle_sweep_loop(self):
        while not self._idle_stop.wait(_IDLE_SWEEP_INTERVAL_SEC):
            for name in _DEFAULT_IDLE_UNLOAD_SEC:
                self.check_idle_eviction(name)

    def check_idle_eviction(self, name):
        """Evict `name` if it's non-pinned, idle past its timeout, and not
        busy with active inference. Exposed directly (not just via the sweep
        thread) so tests can drive it deterministically without real sleeps."""
        evictor = self._evictors.get(name)
        if evictor is None:
            return False
        with self._ledger_lock:
            entry = self._ledger.get(name)
            pinned = self._pinned.get(name, False)
        if entry is None or pinned:
            return False
        timeout = self._idle_timeout_sec(name)
        if timeout <= 0:
            return False
        if time.monotonic() - entry.last_used < timeout:
            return False
        return self._evict_component(name, evictor)

    def stop_idle_sweep(self):
        """Test/shutdown hook: stop the background sweep thread if running."""
        self._idle_stop.set()
        thread, self._idle_thread = self._idle_thread, None
        if thread is not None:
            thread.join(timeout=2.0)
