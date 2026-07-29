"""Regression coverage for the FastAPI lifespan migration.

server.py used to register startup/shutdown via the deprecated
``@app.on_event(...)`` decorators, which emit a DeprecationWarning on every
boot. It now wires a single ``lifespan`` async context manager onto
``app.router.lifespan_context`` instead. These tests assert the migration
actually happened (no on_event decorator left, a lifespan is configured) and
that driving it end-to-end (as uvicorn/TestClient do) still runs startup and
shutdown without raising -- with real models kept out of the picture the same
way tests/test_server_lazy_startup.py does it, so this stays cheap.
"""
import os
import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.routing import _DefaultLifespan

import server


class DummyTranscriber:
    instances = []

    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.loaded = False
        DummyTranscriber.instances.append(self)

    def ensure_loaded(self):
        self.loaded = True
        return True


def test_no_on_event_decorator_remains_in_server_source():
    source = Path(server.__file__).read_text()
    assert not re.search(r"@app\.on_event\(", source)


def test_app_has_a_lifespan_configured():
    # A router with no lifespan passed falls back to starlette's internal
    # _DefaultLifespan, which is a no-op -- so this fails if the migration is
    # ever reverted to the implicit default (lifespan silently dropped)
    # rather than an explicit on_event redeclaration. FastAPI wraps whatever
    # lifespan_context is set into a fresh "merged_lifespan" closure on every
    # app.include_router() call (server.py makes several, all after the
    # assignment), so the identity check has to be against the no-op
    # sentinel type, not against `server.lifespan` by name or identity.
    lifespan_context = server.app.router.lifespan_context
    assert lifespan_context is not None
    assert not isinstance(lifespan_context, _DefaultLifespan)


def test_driving_the_lifespan_runs_startup_and_shutdown_without_raising():
    DummyTranscriber.instances = []
    server.transcriber = None
    server.hotkey_manager = None
    server.hotkey_manager_started = False
    server.loop = None

    profile = {
        "model_keep_llm_loaded": False,
        "model_keep_stt_loaded": False,
        "model_keep_tts_loaded": False,
    }

    with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
        server, "Transcriber", DummyTranscriber
    ), patch.object(server, "load_profile", return_value=profile), patch.object(
        server, "get_engine", side_effect=AssertionError("get_engine should not run")
    ), patch.object(
        server, "HotkeyManager", side_effect=AssertionError("HotkeyManager should not start")
    ):
        # TestClient used as a context manager drives the real ASGI lifespan
        # protocol (lifespan.startup -> ... -> lifespan.shutdown), exercising
        # app.router.lifespan_context exactly as uvicorn does at a real boot.
        with TestClient(server.app) as client:
            health = client.get("/health")
            assert health.status_code == 200

        thread = getattr(server, "_warmup_thread", None)
        if thread is not None:
            thread.join(timeout=5)

    assert len(DummyTranscriber.instances) == 1
    assert server.transcriber is not None
