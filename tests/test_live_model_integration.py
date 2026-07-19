"""Live-model Message Rescue integration test (Build Week I3.10).

Exercises the REAL local llama-server sidecar (if one is already running and
healthy — this test never starts/stops/reloads it) through
``backend.services.rescue_llm_adapter`` + ``backend.services.message_rescue``
with one preservation-critical synthetic transcript, via
``live_model_harness.run_harness`` (unit-tested with fakes in
``tests/test_live_model_harness.py``).

Skip discipline: when no live model is available this test calls
``pytest.skip(reason=...)`` with an explicit, specific reason — it never
returns silently, and a skip is reported by pytest as "skipped", distinct
from "passed", so CI/evidence logs can never mistake "no model available" for
"the preservation contract held." When a model IS available, this test makes
real assertions and fails loudly if the real pipeline doesn't hold up.

Privacy: this test never prints, logs, or asserts on raw transcript or model
*content* — only the structural report produced by
``live_model_harness.run_preservation_probe`` (booleans, counts, category
names), matching backend/services/message_rescue.py's own
content-never-logged convention.
"""

from backend.services.rescue_llm_adapter import build_llm_call_fn
from live_model_harness import DEFAULT_CONTEXT_TEXT, run_harness
from llm_engine import SIDECAR_PORT, is_server_running
from model_manager import DEFAULT_MODEL, get_model_file_status

import pytest


class _RealEngine:
    api_url = f"http://127.0.0.1:{SIDECAR_PORT}"


def test_live_message_rescue_preserves_facts_through_real_local_model():
    call_fn = build_llm_call_fn(_RealEngine())
    report = run_harness(
        is_server_running=is_server_running,
        call_fn=call_fn,
        get_model_status=get_model_file_status,
        model_id=DEFAULT_MODEL,
        context_text=DEFAULT_CONTEXT_TEXT,
    )

    if report["status"] == "UNAVAILABLE":
        pytest.skip(f"live local model unavailable: {report['reason']}")

    probe = report["probe"]
    assert probe["model_call_invoked"] is True, "harness must actually call the real local model, not just report readiness"
    assert probe["model_call_raised"] is False, f"real local model call raised: {probe['model_call_exception_type']}"
    assert probe["faithful_non_empty"] is True
    assert probe["preservation_all_passed"] is True
    assert probe["context_leak_detected"] is False
    assert report["status"] == "PASS", f"live probe did not pass structurally: {probe}"
