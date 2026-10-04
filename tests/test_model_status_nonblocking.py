"""Status observation stays responsive while fake engines hold load locks."""
import asyncio
import threading
import time
from unittest.mock import patch

import httpx
import pytest

import server
from backend.stt.transcriber import Transcriber
from backend.tts.tts_engine import ReviewTTSEngine


@pytest.fixture
def stt():
    with patch("backend.stt.transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False}):
        yield Transcriber(preload=False)


def start_blocked_load(stt, *, cached=True):
    entered, release = threading.Event(), threading.Event()

    def load():
        entered.set()
        assert release.wait(5), "test did not release fake load"
        stt.active_device = "cpu"
        stt.active_compute_type = "int8"
        stt.active_cpu_threads = 2
        return object()

    patches = [patch.object(stt, "_is_model_cached", return_value=cached), patch.object(stt, "_load_model", side_effect=load)]
    for item in patches:
        item.start()
    worker = threading.Thread(target=stt.ensure_loaded)
    worker.start()
    assert entered.wait(5)
    return worker, release, patches


@pytest.mark.parametrize("cached,state", [(True, "loading"), (False, "downloading")])
def test_loading_snapshot_is_immediate_and_independent(stt, cached, state):
    worker, release, patches = start_blocked_load(stt, cached=cached)
    try:
        started = time.monotonic()
        snapshot = stt.get_runtime_status()
        assert time.monotonic() - started < .25
        assert snapshot["state"] == state
        assert snapshot["loading"] and not snapshot["inference_ready"]
        assert snapshot["progress"] is None
        snapshot["state"] = "tampered"
        assert stt.get_runtime_status()["state"] == state
    finally:
        release.set()
        worker.join(5)
        for item in patches:
            item.stop()
    assert not worker.is_alive()
    assert stt.get_runtime_status()["state"] == "ready"


def test_published_lifecycle_and_reload_generations(stt):
    initial = stt.get_runtime_status()
    worker, release, patches = start_blocked_load(stt)
    loading = stt.get_runtime_status()
    # Unload serializes behind the model owner; after it completes a late
    # construction cannot republish ready over the unloaded generation.
    unloader = threading.Thread(target=stt.unload)
    unloader.start()
    release.set()
    worker.join(5)
    unloader.join(5)
    for item in patches:
        item.stop()
    unloaded = stt.get_runtime_status()
    assert initial["generation"] < loading["generation"] < unloaded["generation"]
    assert unloaded["state"] == "unloaded" and not unloaded["constructed"]
    with patch.object(stt, "_is_model_cached", return_value=True), patch.object(stt, "_load_model", side_effect=RuntimeError("private path")):
        assert not stt.ensure_loaded()
    failed = stt.get_runtime_status()
    assert failed["state"] == "failed" and failed["error_code"] == "stt_model_load_failed"
    assert "private path" not in str(failed)
    assert failed["generation"] > unloaded["generation"]


def test_shared_event_loop_status_and_health_during_load(stt):
    worker, release, patches = start_blocked_load(stt)
    ticks = []

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            async def ticker():
                await asyncio.sleep(.01)
                ticks.append(True)
            started = time.monotonic()
            status, health, _ = await asyncio.gather(client.get("/runtime/status"), client.get("/health"), ticker())
            assert time.monotonic() - started < .25
            assert status.status_code == health.status_code == 200
            assert status.json()["stt"]["state"] == "loading"
            assert status.json()["stt"]["loading"]
            assert health.json()["status"] == "active"

    try:
        with patch.object(server, "transcriber", stt):
            asyncio.run(exercise())
        assert ticks and worker.is_alive()
    finally:
        release.set()
        worker.join(5)
        for item in patches:
            item.stop()


def test_probe_publication_retains_lifecycle_ownership(stt):
    with patch.object(stt, "_is_model_cached", return_value=True), patch.object(stt, "_load_model", return_value=object()):
        assert stt.ensure_loaded()
    decoded, release, unloaded = threading.Event(), threading.Event(), threading.Event()

    def decode(_audio):
        decoded.set()
        assert release.wait(5)
        return [], None

    def unload():
        stt.unload()
        unloaded.set()

    with patch.object(stt, "_decode_segments_with_recovery", side_effect=decode):
        prober = threading.Thread(target=stt.runtime_probe)
        prober.start()
        assert decoded.wait(5)
        unloader = threading.Thread(target=unload)
        unloader.start()
        try:
            assert not unloaded.wait(.05), "unload raced probe publication"
        finally:
            release.set()
            prober.join(5)
            unloader.join(5)
    snapshot = stt.get_runtime_status()
    assert snapshot["state"] == "unloaded"
    assert not snapshot["constructed"] and not snapshot["probe_passed"]


def test_tts_snapshot_and_status_route_do_not_wait_for_load_lock():
    engine = ReviewTTSEngine()
    entered, release = threading.Event(), threading.Event()

    def hold():
        with engine._lock:
            engine._publish_status("loading")
            entered.set()
            assert release.wait(5)

    worker = threading.Thread(target=hold)
    worker.start()
    assert entered.wait(5)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            started = time.monotonic()
            tts, health = await asyncio.gather(client.get("/runtime/tts-status"), client.get("/health"))
            assert time.monotonic() - started < .25
            assert tts.status_code == health.status_code == 200
            assert tts.json()["raw_backend"] == "none"
            assert not tts.json()["ok"]

    try:
        with patch.object(server, "tts_engine", engine), patch.object(server, "ensure_tts_initialized", side_effect=AssertionError("status must not initialize")):
            started = time.monotonic()
            assert server._snapshot_tts_status(engine)["loaded"] is False
            assert engine.get_status_snapshot()["state"] == "loading"
            assert time.monotonic() - started < .25
            asyncio.run(exercise())
        snapshot = engine.get_status_snapshot()
        snapshot["capabilities"]["supported_voice_ids"].append("tampered")
        assert not engine.get_status_snapshot()["capabilities"]["supported_voice_ids"]
    finally:
        release.set()
        worker.join(5)


def test_health_never_waits_for_active_runtime_write_lease():
    entered, release = threading.Event(), threading.Event()

    def hold():
        with server.model_runtime.write_lease("stt"):
            entered.set()
            assert release.wait(5)

    worker = threading.Thread(target=hold)
    worker.start()
    assert entered.wait(5)
    try:
        started = time.monotonic()
        leases = server.model_runtime.active_leases()
        assert time.monotonic() - started < .25
        assert any(row["runtime"] == "stt" and row["writer"] for row in leases)
    finally:
        release.set()
        worker.join(5)
