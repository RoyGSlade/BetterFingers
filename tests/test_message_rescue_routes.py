"""Route tests for backend.api.routes.message_rescue (I3.2).

Every test builds its own router via `create_message_rescue_router` with
fake/injected `call_fn`, capture functions, clock, and id_factory — no real
clipboard, network, or model is ever touched. A dedicated auth test class
mounts the router alongside the real `server.auth_middleware` (imported, not
duplicated) on a throwaway FastAPI app to prove the bearer-token gate applies
to these routes exactly as it does to every other route, without needing
`server.py` to have `include_router`'d this module yet.
"""

import json
import re
import threading
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.routes.message_rescue import (
    MAX_MANUAL_CONTEXT_CHARS,
    MAX_TRANSCRIPT_CHARS,
    create_message_rescue_router,
)
from backend.services.context_session import ContextSession


def _clock(start=1000.0):
    box = {"t": start}

    def now():
        return box["t"]

    def advance(seconds):
        box["t"] += seconds

    now.advance = advance
    return now


def _ids(*values):
    it = iter(values)
    return lambda: next(it)


VALID_MODEL_JSON = json.dumps(
    {
        "assessment": {
            "intent": "ask a question",
            "ambiguity_risk": "low",
            "missing_details": [],
            "clarification_question": "",
        },
        "variants": {
            "faithful": "hello world, see you tomorrow",
            "clearer": "Hello! See you tomorrow.",
            "alternate": "Hey, catch you tomorrow.",
        },
    }
)


def _fake_call_fn(_messages):
    return VALID_MODEL_JSON


def _selection_ok(text="Meeting notes for tomorrow at noon"):
    return lambda: {"ok": True, "text": text, "used_fallback": False}


def _selection_empty():
    return lambda: {"ok": False, "text": "", "used_fallback": False}


def _build_app(**router_kwargs):
    defaults = dict(
        context_session=ContextSession(clock=_clock(), id_factory=_ids("ctx-1", "ctx-2", "ctx-3")),
        call_fn=_fake_call_fn,
        clock=_clock(),
        id_factory=_ids("job-1", "job-2", "job-3", "job-4"),
    )
    defaults.update(router_kwargs)
    router = create_message_rescue_router(**defaults)
    app = FastAPI()
    app.include_router(router)
    return app, router


class ContextRoutesTests(unittest.TestCase):
    def test_manual_capture_then_status_then_clear(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post("/message-rescue/context/manual", json={"text": "Reply about the invoice"})
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertTrue(body["active"])
            self.assertEqual(body["source"], "manual")
            self.assertNotIn("text", body)  # raw text never in the response

            status = client.get("/message-rescue/context").json()
            self.assertTrue(status["active"])

            cleared = client.delete("/message-rescue/context")
            self.assertEqual(cleared.status_code, 200)
            status_after = client.get("/message-rescue/context").json()
            self.assertFalse(status_after["active"])
            self.assertIsNone(status_after["id"])

    def test_manual_capture_empty_text_rejected_by_schema(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post("/message-rescue/context/manual", json={"text": ""})
            self.assertEqual(resp.status_code, 422)

    def test_manual_capture_oversize_text_rejected(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                "/message-rescue/context/manual",
                json={"text": "x" * (MAX_MANUAL_CONTEXT_CHARS + 1)},
            )
            self.assertEqual(resp.status_code, 422)

    def test_selection_capture_success(self):
        app, _ = _build_app(
            selection_capture_fn=_selection_ok(),
            selection_supported_fn=lambda: True,
        )
        with TestClient(app) as client:
            resp = client.post("/message-rescue/context/selection")
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["source"], "selection")

    def test_selection_capture_unsupported(self):
        app, _ = _build_app(
            selection_capture_fn=_selection_ok(),
            selection_supported_fn=lambda: False,
        )
        with TestClient(app) as client:
            resp = client.post("/message-rescue/context/selection")
            self.assertEqual(resp.status_code, 422)
            self.assertEqual(resp.json()["detail"], "capture_unsupported")

    def test_selection_capture_empty(self):
        app, _ = _build_app(
            selection_capture_fn=_selection_empty(),
            selection_supported_fn=lambda: True,
        )
        with TestClient(app) as client:
            resp = client.post("/message-rescue/context/selection")
            self.assertEqual(resp.status_code, 422)
            self.assertEqual(resp.json()["detail"], "capture_empty")

    def test_status_when_never_captured_has_stable_shape(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            status = client.get("/message-rescue/context").json()
            self.assertEqual(
                set(status.keys()),
                {"active", "id", "source", "captured_at", "expires_at", "use_count", "max_uses", "visible_preview"},
            )
            self.assertFalse(status["active"])

    def test_expiry_makes_context_inactive_and_unusable(self):
        clock = _clock()
        session = ContextSession(clock=clock, id_factory=_ids("ctx-exp"))
        app, _ = _build_app(context_session=session)
        with TestClient(app) as client:
            client.post("/message-rescue/context/manual", json={"text": "expires soon"})
            clock.advance(9999)
            status = client.get("/message-rescue/context").json()
            self.assertFalse(status["active"])
            gen = client.post(
                "/message-rescue/generate",
                json={"transcript": "hi", "use_context": True},
            )
            self.assertEqual(gen.status_code, 409)
            self.assertEqual(gen.json()["detail"], "context_expired")


class GenerateRoutesTests(unittest.TestCase):
    def test_generate_happy_path_returns_frozen_schema(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                "/message-rescue/generate",
                json={"transcript": "hello world, see you tomorrow"},
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertEqual(body["status"], "done")
            self.assertEqual(
                set(body["result"].keys()),
                {"assessment", "delivery", "variants", "preservation_checks", "warnings"},
            )
            self.assertEqual(
                set(body["result"]["variants"].keys()), {"faithful", "clearer", "alternate"}
            )

            fetched = client.get(f"/message-rescue/generate/{body['id']}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json(), body)

    def test_generate_empty_transcript_rejected_by_schema(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post("/message-rescue/generate", json={"transcript": ""})
            self.assertEqual(resp.status_code, 422)

    def test_generate_oversize_transcript_rejected(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                "/message-rescue/generate",
                json={"transcript": "x" * (MAX_TRANSCRIPT_CHARS + 1)},
            )
            self.assertEqual(resp.status_code, 422)

    def test_malformed_model_output_still_yields_safe_faithful_fallback(self):
        app, _ = _build_app(call_fn=lambda messages: "not json at all")
        with TestClient(app) as client:
            resp = client.post(
                "/message-rescue/generate",
                json={"transcript": "call me back about the invoice"},
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "done")
            self.assertEqual(body["result"]["variants"]["faithful"], "call me back about the invoice")
            self.assertTrue(body["result"]["warnings"])

    def test_unknown_result_id_is_404(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.get("/message-rescue/generate/does-not-exist")
            self.assertEqual(resp.status_code, 404)

    def test_context_consumed_once_and_not_leaked_in_response(self):
        session = ContextSession(clock=_clock(), id_factory=_ids("ctx-1"))
        app, _ = _build_app(context_session=session)
        with TestClient(app) as client:
            secret_context = "SECRET CONTEXT: order #48213, ship to 900 Maple, do not repeat this verbatim"
            client.post("/message-rescue/context/manual", json={"text": secret_context})

            resp = client.post(
                "/message-rescue/generate",
                json={"transcript": "yes that works for me", "use_context": True},
            )
            self.assertEqual(resp.status_code, 200)
            raw_response_text = resp.text
            self.assertNotIn(secret_context, raw_response_text)
            self.assertNotIn("48213", raw_response_text)

            # Context is one-use by default: a second use_context=True request
            # must fail closed rather than silently reusing/re-consuming it.
            second = client.post(
                "/message-rescue/generate",
                json={"transcript": "another message", "use_context": True},
            )
            self.assertEqual(second.status_code, 409)
            self.assertEqual(second.json()["detail"], "context_missing")

    def test_generate_without_use_context_does_not_touch_captured_context(self):
        session = ContextSession(clock=_clock(), id_factory=_ids("ctx-1"))
        app, _ = _build_app(context_session=session)
        with TestClient(app) as client:
            client.post("/message-rescue/context/manual", json={"text": "still here"})
            resp = client.post("/message-rescue/generate", json={"transcript": "hi"})
            self.assertEqual(resp.status_code, 200)
            status = client.get("/message-rescue/context").json()
            self.assertTrue(status["active"])  # untouched, still available


class GenerateTimeoutTests(unittest.TestCase):
    def test_overall_timeout_maps_to_timeout_status_not_a_hang_or_500(self):
        def slow_call_fn(_messages):
            time.sleep(0.4)
            return VALID_MODEL_JSON

        app, _ = _build_app(call_fn=slow_call_fn, generate_timeout_s=0.05)
        with TestClient(app) as client:
            resp = client.post("/message-rescue/generate", json={"transcript": "hello"})
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "timeout")
            self.assertIsNone(body["result"])


class GenerateCancellationTests(unittest.TestCase):
    def test_cancel_while_in_flight_reports_cancelled_not_done(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_call_fn(_messages):
            started.set()
            release.wait(timeout=5)
            return VALID_MODEL_JSON

        app, _ = _build_app(
            call_fn=blocking_call_fn,
            id_factory=_ids("fixed-job"),
        )
        result_box = {}

        def worker():
            with TestClient(app) as worker_client:
                result_box["response"] = worker_client.post(
                    "/message-rescue/generate", json={"transcript": "hold on"}
                )

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(started.wait(timeout=5), "call_fn was never invoked")
            with TestClient(app) as cancel_client:
                cancel_resp = cancel_client.post("/message-rescue/generate/fixed-job/cancel")
                self.assertEqual(cancel_resp.status_code, 200, cancel_resp.text)
                self.assertEqual(cancel_resp.json()["status"], "cancel_requested")
        finally:
            release.set()
            thread.join(timeout=5)

        self.assertIn("response", result_box)
        body = result_box["response"].json()
        self.assertEqual(body["status"], "cancelled")
        self.assertIsNone(body["result"])

        with TestClient(app) as client:
            fetched = client.get("/message-rescue/generate/fixed-job")
            self.assertEqual(fetched.json()["status"], "cancelled")

    def test_cancel_unknown_job_is_404(self):
        app, _ = _build_app()
        with TestClient(app) as client:
            resp = client.post("/message-rescue/generate/does-not-exist/cancel")
            self.assertEqual(resp.status_code, 404)

    def test_cancel_after_generation_already_finished_is_404(self):
        app, _ = _build_app(id_factory=_ids("done-job"))
        with TestClient(app) as client:
            client.post("/message-rescue/generate", json={"transcript": "quick one"})
            resp = client.post("/message-rescue/generate/done-job/cancel")
            self.assertEqual(resp.status_code, 404)


class PersonaExamplesLookupTests(unittest.TestCase):
    def test_persona_and_examples_lookups_are_invoked_with_persona_name(self):
        calls = {}

        def persona_lookup(name):
            calls["persona"] = name
            return {"prompt": "Be concise."}

        def examples_lookup(name):
            calls["examples"] = name
            return [{"raw": "hi", "out": "Hello!"}]

        app, _ = _build_app(persona_lookup=persona_lookup, examples_lookup=examples_lookup)
        with TestClient(app) as client:
            resp = client.post(
                "/message-rescue/generate",
                json={"transcript": "hi there", "persona": "Assistant"},
            )
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls["persona"], "Assistant")
        self.assertEqual(calls["examples"], "Assistant")

    def test_no_persona_supplied_skips_lookups(self):
        calls = {"invoked": False}

        def persona_lookup(name):
            calls["invoked"] = True
            return None

        app, _ = _build_app(persona_lookup=persona_lookup)
        with TestClient(app) as client:
            client.post("/message-rescue/generate", json={"transcript": "hi there"})
        self.assertFalse(calls["invoked"])


class AuthEnforcedTests(unittest.TestCase):
    """Mounts the router with the SAME auth middleware server.py uses, proving
    these routes inherit the global bearer-token gate — without needing
    server.py to include_router this module yet."""

    def test_requests_without_a_bearer_token_are_rejected(self):
        import os
        from unittest.mock import patch

        import server  # noqa: F401  (imports the real auth_middleware function)

        app, _ = _build_app()
        app.add_middleware(BaseHTTPMiddleware, dispatch=server.auth_middleware)

        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "secret-token"}):
            with TestClient(app) as client:
                unauthed = client.get("/message-rescue/context")
                self.assertEqual(unauthed.status_code, 401)

                authed = client.get(
                    "/message-rescue/context", headers={"Authorization": "Bearer secret-token"}
                )
                self.assertEqual(authed.status_code, 200)


class ComposedIntoServerAppTests(unittest.TestCase):
    """Now that server.py include_router's the real production `router`
    (composition-root step of I3.2), confirm it is reachable end-to-end on
    the actual app object, under the actual auth middleware."""

    def test_routes_are_registered_and_auth_gated_on_the_real_app(self):
        import os
        from unittest.mock import patch

        import server

        paths = server.app.openapi()["paths"]
        for path in (
            "/message-rescue/context",
            "/message-rescue/context/selection",
            "/message-rescue/context/manual",
            "/message-rescue/generate",
            "/message-rescue/generate/{job_id}",
            "/message-rescue/generate/{job_id}/cancel",
        ):
            self.assertIn(path, paths)

        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "secret-token"}):
            with TestClient(server.app) as client:
                unauthed = client.get("/message-rescue/context")
                self.assertEqual(unauthed.status_code, 401)
                authed = client.get(
                    "/message-rescue/context", headers={"Authorization": "Bearer secret-token"}
                )
                self.assertEqual(authed.status_code, 200)
                self.assertIn("active", authed.json())


class PrivacyWipeHookTests(unittest.TestCase):
    """I3.4: the router exposes clear_state()/state_counts() so server.py's
    privacy wipe can drop held context and stored generation results without
    reaching into the factory's private closures."""

    def test_state_counts_reflect_context_and_results(self):
        app, router = _build_app(id_factory=_ids("job-1"))
        with TestClient(app) as client:
            self.assertEqual(
                router.state_counts(),
                {"context_active": False, "stored_results": 0, "active_generations": 0},
            )
            client.post("/message-rescue/context/manual", json={"text": "some context"})
            client.post("/message-rescue/generate", json={"transcript": "hello"})
            counts = router.state_counts()
            self.assertTrue(counts["context_active"])
            self.assertEqual(counts["stored_results"], 1)
            self.assertEqual(counts["active_generations"], 0)

    def test_clear_state_drops_context_and_results_and_reports_counts(self):
        app, router = _build_app(id_factory=_ids("job-1"))
        with TestClient(app) as client:
            secret_context = "SECRET: order #48213"
            client.post("/message-rescue/context/manual", json={"text": secret_context})
            gen = client.post("/message-rescue/generate", json={"transcript": "hello"})
            job_id = gen.json()["id"]

            cleared = router.clear_state()
            self.assertEqual(cleared, {"stored_results_cleared": 1, "active_generations_cleared": 0})
            self.assertEqual(
                router.state_counts(),
                {"context_active": False, "stored_results": 0, "active_generations": 0},
            )

            status = client.get("/message-rescue/context").json()
            self.assertFalse(status["active"])
            self.assertIsNone(status["id"])

            fetched = client.get(f"/message-rescue/generate/{job_id}")
            self.assertEqual(fetched.status_code, 404)

    def test_clear_state_does_not_interrupt_in_flight_generation(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_call_fn(_messages):
            started.set()
            release.wait(timeout=5)
            return VALID_MODEL_JSON

        app, router = _build_app(call_fn=blocking_call_fn, id_factory=_ids("fixed-job"))
        result_box = {}

        def worker():
            with TestClient(app) as worker_client:
                result_box["response"] = worker_client.post(
                    "/message-rescue/generate", json={"transcript": "hold on"}
                )

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(started.wait(timeout=5), "call_fn was never invoked")
            cleared = router.clear_state()
            self.assertEqual(cleared["active_generations_cleared"], 1)
        finally:
            release.set()
            thread.join(timeout=5)
        self.assertIn("response", result_box)
        self.assertEqual(result_box["response"].json()["status"], "done")

    def test_clear_state_idempotent_when_already_empty(self):
        app, router = _build_app()
        self.assertEqual(
            router.clear_state(),
            {"stored_results_cleared": 0, "active_generations_cleared": 0},
        )
        self.assertEqual(
            router.clear_state(),
            {"stored_results_cleared": 0, "active_generations_cleared": 0},
        )


class OpenApiAndNoContentLoggingTests(unittest.TestCase):
    def test_openapi_schema_builds_and_lists_expected_paths(self):
        app, _ = _build_app()
        schema = app.openapi()
        paths = set(schema["paths"].keys())
        self.assertEqual(
            paths,
            {
                "/message-rescue/context/selection",
                "/message-rescue/context/manual",
                "/message-rescue/context",
                "/message-rescue/generate",
                "/message-rescue/generate/{job_id}",
                "/message-rescue/generate/{job_id}/cancel",
            },
        )

    def test_module_never_calls_logging(self):
        import backend.api.routes.message_rescue as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import logging", source)
        self.assertIsNone(re.search(r"\blogging\.\w+\(", source))


if __name__ == "__main__":
    unittest.main()
