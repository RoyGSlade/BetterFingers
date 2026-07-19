"""Model-free tests for live_model_harness.py's decision/report logic (I3.10).

Every dependency is a plain fake — no network, no subprocess, no real model —
so this suite runs in the cheap subset. Real-model exercise lives in
tests/test_live_model_integration.py, which skips explicitly when a live
model is unavailable.
"""

from backend.services.message_rescue import check_preservation
from live_model_harness import (
    DEFAULT_CONTEXT_TEXT,
    PRESERVATION_TRANSCRIPT,
    discover_readiness,
    run_harness,
    run_preservation_probe,
)


# --- discover_readiness -------------------------------------------------------


def test_readiness_available_when_server_running():
    readiness = discover_readiness(is_server_running=lambda: True, model_id="gemma-4-e2b-q4")
    assert readiness["available"] is True
    assert readiness["model_id"] == "gemma-4-e2b-q4"


def test_readiness_unavailable_with_specific_reason_when_model_incomplete():
    readiness = discover_readiness(
        is_server_running=lambda: False,
        get_model_status=lambda model_id: {"ok": False, "attention": ["missing"]},
        model_id="gemma-4-e2b-q4",
    )
    assert readiness["available"] is False
    assert "missing" in readiness["reason"]
    assert readiness["model_ok"] is False


def test_readiness_unavailable_generic_reason_without_model_status():
    readiness = discover_readiness(is_server_running=lambda: False)
    assert readiness["available"] is False
    assert "did not respond" in readiness["reason"]
    assert readiness["model_ok"] is None


def test_readiness_never_raises_on_broken_dependencies():
    def boom():
        raise RuntimeError("network unreachable")

    def status_boom(model_id):
        raise RuntimeError("disk error")

    readiness = discover_readiness(is_server_running=boom, get_model_status=status_boom)
    assert readiness["available"] is False


# --- run_preservation_probe ---------------------------------------------------


def _json_call_fn(payload):
    def call_fn(messages):
        return payload

    return call_fn


GOOD_RESPONSE = (
    '{"assessment": {"intent": "reschedule"}, '
    '"variants": {"faithful": "%s", "clearer": "", "alternate": ""}}' % PRESERVATION_TRANSCRIPT
)


def test_probe_pass_on_well_formed_preserving_response():
    probe = run_preservation_probe(_json_call_fn(GOOD_RESPONSE))
    assert probe["status"] == "PASS"
    assert probe["model_call_invoked"] is True
    assert probe["model_call_raised"] is False
    assert probe["response_parsed_as_json"] is True
    assert probe["faithful_non_empty"] is True
    assert probe["preservation_all_passed"] is True
    assert probe["context_leak_detected"] is False
    # PRESERVATION_TRANSCRIPT was engineered to exercise every category.
    assert set(probe["preservation_categories_checked"]) >= {
        "numbers",
        "dates",
        "negation",
        "modality",
        "commitments",
        "names",
    }


def test_probe_call_failed_status_when_call_fn_raises():
    def raising_call_fn(messages):
        raise TimeoutError("local LLM call timed out")

    probe = run_preservation_probe(raising_call_fn)
    assert probe["status"] == "CALL_FAILED"
    assert probe["model_call_invoked"] is True
    assert probe["model_call_raised"] is True
    assert probe["model_call_exception_type"] == "TimeoutError"
    # rescue_message() still falls back to the raw transcript even though the
    # real call failed; that must not upgrade a CALL_FAILED run to PASS.
    assert probe["faithful_non_empty"] is True
    assert probe["preservation_all_passed"] is True


def test_probe_pass_when_model_drops_a_fact_because_the_safety_net_catches_it():
    """A real (unpredictable) model can return well-formed JSON that quietly
    drops a preserved fact. rescue_message()'s own safety net must replace
    the faithful variant with the raw transcript in that case — so the probe
    still reports PASS on the final output, while still recording that the
    call itself succeeded."""
    mangled = PRESERVATION_TRANSCRIPT.replace("Marcus", "someone")
    bad_response = '{"variants": {"faithful": "%s", "clearer": "", "alternate": ""}}' % mangled
    probe = run_preservation_probe(_json_call_fn(bad_response))
    assert probe["model_call_raised"] is False
    assert probe["status"] == "PASS"
    assert probe["preservation_all_passed"] is True
    assert probe["model_warnings_count"] >= 1


def test_probe_pass_when_model_leaks_context_because_the_safety_net_catches_it():
    leaked = "faithful text that quotes: " + DEFAULT_CONTEXT_TEXT
    leaking_response = '{"variants": {"faithful": "%s", "clearer": "", "alternate": ""}}' % leaked
    probe = run_preservation_probe(_json_call_fn(leaking_response))
    assert probe["model_call_raised"] is False
    assert probe["status"] == "PASS"
    assert probe["context_leak_detected"] is False
    assert probe["model_warnings_count"] >= 1


def test_probe_response_parsed_as_json_false_for_garbage_but_still_passes():
    probe = run_preservation_probe(_json_call_fn("not json at all"))
    assert probe["response_parsed_as_json"] is False
    assert probe["model_call_raised"] is False
    # rescue_message() falls back to the raw transcript on unparsable output.
    assert probe["status"] == "PASS"


def test_probe_never_returns_transcript_or_response_content():
    probe = run_preservation_probe(_json_call_fn(GOOD_RESPONSE))
    serialized = str(probe)
    assert PRESERVATION_TRANSCRIPT not in serialized
    assert DEFAULT_CONTEXT_TEXT not in serialized


# --- run_harness ---------------------------------------------------------------


def test_run_harness_reports_unavailable_without_running_probe():
    invoked = {"count": 0}

    def call_fn(messages):
        invoked["count"] += 1
        return GOOD_RESPONSE

    report = run_harness(is_server_running=lambda: False, call_fn=call_fn)
    assert report["status"] == "UNAVAILABLE"
    assert report["probe"] is None
    assert invoked["count"] == 0


def test_run_harness_delegates_to_probe_when_available():
    report = run_harness(is_server_running=lambda: True, call_fn=_json_call_fn(GOOD_RESPONSE))
    assert report["status"] == "PASS"
    assert report["probe"] is not None
    assert report["readiness"]["available"] is True


# --- sanity: the engineered transcript actually exercises every category -----


def test_preservation_transcript_covers_every_category():
    checks = check_preservation(PRESERVATION_TRANSCRIPT, PRESERVATION_TRANSCRIPT)
    categories = {c["name"].split("/", 1)[1] for c in checks}
    assert categories >= {"numbers", "dates", "negation", "modality", "commitments", "names"}
    assert all(c["passed"] for c in checks)
