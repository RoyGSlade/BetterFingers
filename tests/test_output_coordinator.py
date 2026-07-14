import threading
import time

import pytest

from output_coordinator import OutputCoordinator


def test_begin_end_roundtrip():
    coord = OutputCoordinator()
    op = coord.begin_send()
    assert op is not None
    assert coord.active_count() == 1
    coord.end_send(op)
    assert coord.active_count() == 0


def test_begin_send_uses_supplied_operation_id():
    coord = OutputCoordinator()
    assert coord.begin_send(operation_id="abc123") == "abc123"
    coord.end_send("abc123")


def test_end_send_unknown_id_is_noop():
    coord = OutputCoordinator()
    coord.end_send("never-registered")
    assert coord.active_count() == 0


def test_drain_idle_succeeds_immediately_and_holds_lease():
    coord = OutputCoordinator()
    ok, stuck = coord.drain(timeout=0.1)
    assert ok is True
    assert stuck == {}
    # Lease held: new sends refused.
    assert coord.begin_send() is None
    coord.release()
    assert coord.begin_send() is not None


def test_drain_invokes_cancel_callback():
    coord = OutputCoordinator()
    called = threading.Event()
    ok, _ = coord.drain(cancel_active=called.set, timeout=0.1)
    assert ok and called.is_set()
    coord.release()


def test_drain_waits_for_active_send_to_finish():
    coord = OutputCoordinator()
    op = coord.begin_send()
    result = {}

    def wipe():
        result["ok"], result["stuck"] = coord.drain(timeout=5.0)

    t = threading.Thread(target=wipe)
    t.start()
    # Give the drain a moment to start waiting; the send is still active so
    # cancellation must be visible to it.
    time.sleep(0.05)
    assert coord.cancel_requested() is True
    assert not result  # drain has not returned yet
    coord.end_send(op)
    t.join(timeout=5.0)
    assert result["ok"] is True and result["stuck"] == {}
    coord.release()
    assert coord.cancel_requested() is False


def test_drain_timeout_reports_stuck_ops_and_rolls_back():
    coord = OutputCoordinator()
    op = coord.begin_send(operation_id="stuck-op")
    ok, stuck = coord.drain(timeout=0.05)
    assert ok is False
    assert "stuck-op" in stuck
    assert stuck["stuck-op"] >= 0
    # Rolled back: sends work again, no lease held.
    assert coord.cancel_requested() is False
    op2 = coord.begin_send()
    assert op2 is not None
    coord.end_send(op)
    coord.end_send(op2)


def test_begin_send_refused_while_draining():
    coord = OutputCoordinator()
    op = coord.begin_send()
    started = threading.Event()

    def wipe():
        started.set()
        coord.drain(timeout=5.0)

    t = threading.Thread(target=wipe)
    t.start()
    started.wait(timeout=1.0)
    # Wait until cancellation is actually visible.
    deadline = time.monotonic() + 1.0
    while not coord.cancel_requested() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert coord.begin_send() is None
    coord.end_send(op)
    t.join(timeout=5.0)
    coord.release()


def test_send_finishing_after_cancel_sees_cancellation():
    """The P0 sequence: wipe drains while a send is mid-injection. The send
    must observe cancel_requested() before its final persistence."""
    coord = OutputCoordinator()
    op = coord.begin_send()
    observed = {}
    injection_may_finish = threading.Event()

    def send():
        injection_may_finish.wait(timeout=5.0)
        observed["cancelled"] = coord.cancel_requested()
        coord.end_send(op)

    def wipe():
        ok, stuck = coord.drain(cancel_active=injection_may_finish.set,
                                timeout=5.0)
        observed["drain_ok"] = ok
        coord.release()

    ts = threading.Thread(target=send)
    tw = threading.Thread(target=wipe)
    ts.start()
    tw.start()
    ts.join(timeout=5.0)
    tw.join(timeout=5.0)
    assert observed["cancelled"] is True
    assert observed["drain_ok"] is True
