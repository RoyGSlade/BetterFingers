"""Coordination between draft sends and the privacy wipe.

The privacy wipe must operate on a quiescent output path: no send may be
mid-injection while user data is deleted, and no send may write draft history
back to disk after the wipe has erased it. This module provides the handshake:

- A send registers itself (begin_send) before its first "sending" persistence
  and deregisters (end_send) after its final one. Registration is refused
  while a wipe is draining or holds the exclusive lease.
- The wipe drains: it sets the cancellation event (visible to sends via
  cancel_requested), invokes a caller-supplied cancel callback (which stops
  the active injection), waits until the active-send count reaches zero, and
  then holds an exclusive lease for the duration of the delete-and-verify
  phase. If active sends do not finish within the timeout, drain fails and
  reports the stuck operations so the wipe can abort without deleting under
  a live send.
"""

import threading
import time
import uuid


class OutputCoordinator:
    def __init__(self):
        self._cond = threading.Condition()
        # op_id -> monotonic start time, for timeout reporting.
        self._active = {}
        self._cancel = threading.Event()
        self._lease_held = False

    def begin_send(self, operation_id=None):
        """Register a send. Returns its operation id, or None if refused.

        Refused while a drain is in progress (cancellation set) or the wipe
        holds the exclusive lease — a send that cannot register must not
        inject or persist.
        """
        with self._cond:
            if self._cancel.is_set() or self._lease_held:
                return None
            op_id = operation_id or uuid.uuid4().hex
            self._active[op_id] = time.monotonic()
            return op_id

    def end_send(self, operation_id):
        """Deregister a send. Safe to call with an already-removed id."""
        with self._cond:
            self._active.pop(operation_id, None)
            self._cond.notify_all()

    def cancel_requested(self):
        """True while a wipe is draining or deleting.

        A send must check this before its final draft-history persistence and
        skip the write when set: the wipe is deleting (or has deleted) the
        very files the write would recreate.
        """
        return self._cancel.is_set()

    def active_count(self):
        with self._cond:
            return len(self._active)

    def drain(self, cancel_active=None, timeout=5.0):
        """Cancel active sends, wait for quiescence, take the exclusive lease.

        Returns (ok, stuck). On success stuck is empty and the lease is held —
        the caller MUST call release() when done. On timeout the lease is NOT
        taken, cancellation is rolled back so sends resume, and stuck maps each
        unfinished operation id to its age in seconds.
        """
        self._cancel.set()
        if cancel_active is not None:
            cancel_active()
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    now = time.monotonic()
                    stuck = {op: round(now - started, 3)
                             for op, started in self._active.items()}
                    self._cancel.clear()
                    return False, stuck
                self._cond.wait(remaining)
            self._lease_held = True
            return True, {}

    def release(self):
        """Release the exclusive lease and allow sends again."""
        with self._cond:
            self._lease_held = False
            self._cancel.clear()
            self._cond.notify_all()
