"""Server-owned wake phrase setup registry: privacy and lifecycle contract."""

from dataclasses import FrozenInstanceError
import json
import threading

import pytest

import wake_setup_registry as wsr


class _Clock:
    def __init__(self, value=100.0):
        self.value = float(value)

    def __call__(self):
        return self.value


def _tokens(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def _report(phrase="hey betterfinger", verdict="good", **extra):
    report = {
        "version": 1,
        "language": "en",
        "normalized_phrase": phrase,
        "verdict": verdict,
        "score": 95,
        "reasons": ["Text preflight passed."],
        "evidence": {"estimated_syllables": 5, "estimated_phonemes": 12},
        "near_confusers": ["hey better finger"],
        "acoustic_test_required": True,
    }
    report.update(extra)
    return report


def _registry(*tokens, clock=None, max_entries=16, ttl_seconds=1800):
    return wsr.WakeSetupRegistry(
        max_entries=max_entries,
        ttl_seconds=ttl_seconds,
        clock=clock or _Clock(),
        token_factory=_tokens(*tokens),
    )


def test_issue_and_resolve_use_an_opaque_server_id():
    registry = _registry("opaque-token-0001")
    record = registry.issue("hey betterfinger", _report())

    assert record.phrase_id == "opaque-token-0001"
    assert "betterfinger" not in record.phrase_id
    assert registry.resolve(record.phrase_id) is record
    assert record.to_dict()["normalized_phrase"] == "hey betterfinger"


@pytest.mark.parametrize("verdict", ["reject", "", None, "reliable"])
def test_issue_rejects_any_nonpassing_fitness_verdict(verdict):
    registry = _registry("opaque-token-0001")
    with pytest.raises(ValueError, match="verdict"):
        registry.issue("hey betterfinger", _report(verdict=verdict))
    assert len(registry) == 0


@pytest.mark.parametrize(
    "phrase",
    ["", " Hey betterfinger", "hey  betterfinger", "HEY BETTERFINGER", "hey bétterfinger"],
)
def test_issue_requires_already_normalized_nonempty_english_phrase(phrase):
    registry = _registry("opaque-token-0001")
    with pytest.raises(ValueError, match="normalized_phrase"):
        registry.issue(phrase, _report(phrase=phrase))


def test_report_must_belong_to_the_exact_phrase():
    registry = _registry("opaque-token-0001")
    with pytest.raises(ValueError, match="does not belong"):
        registry.issue("hey betterfinger", _report(phrase="hey other phrase"))


def test_record_is_frozen_and_nested_report_is_a_defensive_copy():
    registry = _registry("opaque-token-0001")
    source = _report()
    record = registry.issue("hey betterfinger", source)

    source["score"] = 0
    source["reasons"].append("mutated outside")
    returned = record.fitness_report
    returned["score"] = 1
    returned["reasons"].append("mutated return")

    assert registry.resolve(record.phrase_id).fitness_report["score"] == 95
    assert registry.resolve(record.phrase_id).fitness_report["reasons"] == ["Text preflight passed."]
    with pytest.raises(FrozenInstanceError):
        record.normalized_phrase = "different"


def test_public_record_is_json_round_trip_safe():
    record = _registry("opaque-token-0001").issue("hey betterfinger", _report())
    payload = record.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) == {
        "phrase_id", "normalized_phrase", "fitness_report", "issued_at", "expires_at"
    }


@pytest.mark.parametrize("field", ["audio", "path", "text", "clone_prompt", "model_id"])
def test_report_refuses_content_or_runtime_fields(field):
    registry = _registry("opaque-token-0001")
    with pytest.raises(ValueError, match="unsupported fields"):
        registry.issue("hey betterfinger", _report(**{field: "must not be retained"}))


@pytest.mark.parametrize(
    ("evidence", "field"),
    [
        ({"pronunciation": {"path": "C:/someone.wav", "audio": "raw-clone-data"}}, "pronunciation"),
        ({"phonetic_signature": {"clone_prompt": "hidden"}}, "phonetic_signature"),
        ({"contained_commands": [{"text": "arbitrary TTS"}]}, "contained_commands"),
        ({"nearest_vocabulary_similarity": [0.9, {"path": "C:/voice.wav"}]}, "nearest_vocabulary_similarity"),
    ],
)
def test_evidence_fields_reject_nested_path_audio_or_tts_payloads(evidence, field):
    registry = _registry("opaque-token-0001")
    with pytest.raises(ValueError, match=field):
        registry.issue("hey betterfinger", _report(evidence=evidence))
    assert len(registry) == 0


def test_full_phrase_evaluator_report_survives_exact_evidence_validation():
    import wake_phrase_fitness

    report = wake_phrase_fitness.evaluate_wake_phrase("hey betterfingers")
    assert report["verdict"] in {"good", "workable"}

    record = _registry("opaque-token-0001").issue(report["normalized_phrase"], report)

    assert record.fitness_report == report


@pytest.mark.parametrize(
    "evidence",
    [
        {"word_count": True},
        {"estimated_phonemes": 161},
        {"phonetic_signature": "../../voice.wav"},
        {"pronunciation_source": "arbitrary_tts"},
        {"unsupported_characters": ["7"]},
        {"nearest_vocabulary_phrase": "C:/voice.wav"},
        {"nearest_vocabulary_similarity": float("nan")},
        {"contained_common_phrases": ["not/normalized"]},
    ],
)
def test_evidence_scalar_and_list_contracts_fail_closed(evidence):
    registry = _registry("opaque-token-0001")
    with pytest.raises(ValueError, match="fitness report"):
        registry.issue("hey betterfinger", _report(evidence=evidence))
    assert len(registry) == 0


def test_expired_record_is_pruned_on_resolve():
    clock = _Clock(10)
    registry = _registry("opaque-token-0001", clock=clock, ttl_seconds=30)
    record = registry.issue("hey betterfinger", _report())

    clock.value = 40
    assert registry.resolve(record.phrase_id) is None
    assert len(registry) == 0


def test_explicit_expiry_pruning_reports_removed_count():
    clock = _Clock(10)
    registry = _registry("opaque-token-0001", "opaque-token-0002", clock=clock, ttl_seconds=30)
    registry.issue("hey betterfinger", _report())
    clock.value = 20
    registry.issue("hello private helper", _report(phrase="hello private helper", verdict="workable"))

    clock.value = 40
    assert registry.prune_expired() == 1
    assert len(registry) == 1


def test_capacity_evicts_the_oldest_live_candidate():
    registry = _registry(
        "opaque-token-0001", "opaque-token-0002", "opaque-token-0003", max_entries=2
    )
    first = registry.issue("hey betterfinger", _report())
    second = registry.issue(
        "hello private helper", _report(phrase="hello private helper", verdict="workable")
    )
    third = registry.issue("quiet purple lantern", _report(phrase="quiet purple lantern"))

    assert registry.resolve(first.phrase_id) is None
    assert registry.resolve(second.phrase_id) is second
    assert registry.resolve(third.phrase_id) is third
    assert len(registry) == 2


def test_expired_entries_are_pruned_before_capacity_eviction():
    clock = _Clock(0)
    registry = _registry(
        "opaque-token-0001", "opaque-token-0002", "opaque-token-0003",
        clock=clock, max_entries=2, ttl_seconds=10,
    )
    first = registry.issue("hey betterfinger", _report())
    clock.value = 5
    second = registry.issue(
        "hello private helper", _report(phrase="hello private helper", verdict="workable")
    )
    clock.value = 10
    third = registry.issue("quiet purple lantern", _report(phrase="quiet purple lantern"))

    assert registry.resolve(first.phrase_id) is None
    assert registry.resolve(second.phrase_id) is second
    assert registry.resolve(third.phrase_id) is third


def test_discard_is_idempotent_and_clear_is_a_privacy_wipe_hook():
    registry = _registry("opaque-token-0001", "opaque-token-0002")
    first = registry.issue("hey betterfinger", _report())
    registry.issue("quiet purple lantern", _report(phrase="quiet purple lantern"))

    assert registry.discard(first.phrase_id) is True
    assert registry.discard(first.phrase_id) is False
    assert registry.clear() == 1
    assert registry.clear() == 0
    assert len(registry) == 0


def test_suspended_issuance_cannot_repopulate_a_privacy_wipe():
    registry = _registry("opaque-token-0001", "opaque-token-0002")
    existing = registry.issue("hey betterfinger", _report())

    registry.suspend_issuance()
    assert registry.clear() == 1
    with pytest.raises(wsr.WakeSetupIssuanceSuspended, match="privacy wipe"):
        registry.issue("quiet purple lantern", _report(phrase="quiet purple lantern"))
    assert registry.resolve(existing.phrase_id) is None
    assert len(registry) == 0

    registry.resume_issuance()
    replacement = registry.issue(
        "quiet purple lantern", _report(phrase="quiet purple lantern")
    )
    assert registry.resolve(replacement.phrase_id) is replacement


def test_token_collisions_retry_without_overwriting_authority():
    registry = _registry("opaque-token-0001", "opaque-token-0001", "opaque-token-0002")
    first = registry.issue("hey betterfinger", _report())
    second = registry.issue("quiet purple lantern", _report(phrase="quiet purple lantern"))

    assert first.phrase_id == "opaque-token-0001"
    assert second.phrase_id == "opaque-token-0002"
    assert registry.resolve(first.phrase_id).normalized_phrase == "hey betterfinger"


def test_parallel_issue_is_thread_safe_and_never_exceeds_bound():
    clock = _Clock()
    registry = wsr.WakeSetupRegistry(max_entries=16, clock=clock)
    issued = []
    errors = []
    lock = threading.Lock()

    def worker(index):
        try:
            phrase = f"private helper number {index}"
            # Digits are not normalized phrase text; use deterministic letters.
            phrase = f"private helper {chr(97 + index // 26)}{chr(97 + index % 26)}"
            record = registry.issue(phrase, _report(phrase=phrase, verdict="workable"))
            with lock:
                issued.append(record.phrase_id)
        except Exception as exc:  # pragma: no cover - assertion reports details
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(issued) == 40
    assert len(set(issued)) == 40
    assert len(registry) == 16


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"max_entries": 0}, "max_entries"),
        ({"ttl_seconds": 0}, "ttl_seconds"),
        ({"clock": None}, "callable"),
        ({"token_factory": None}, "callable"),
    ],
)
def test_constructor_rejects_invalid_policy(kwargs, error):
    with pytest.raises((TypeError, ValueError), match=error):
        wsr.WakeSetupRegistry(**kwargs)


def test_global_registry_is_process_local_registry_instance():
    assert isinstance(wsr.WAKE_SETUP_REGISTRY, wsr.WakeSetupRegistry)


def test_module_has_no_logging_or_filesystem_surface():
    assert not hasattr(wsr, "logging")
    assert not hasattr(wsr, "os")
    assert not hasattr(wsr, "Path")
