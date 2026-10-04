import json
from dataclasses import replace

import pytest

from backend.wake.wake_qwen_capability import (
    BENCHMARK_REQUIRED,
    CANDIDATE_VRAM_FLOOR_MIB,
    MIN_ACCEPTED_GENERATION_RATIO,
    QUALIFIED,
    UNSUPPORTED,
    BenchmarkObservation,
    HardwareSnapshot,
    evaluate_benchmark,
    evaluate_precheck,
)


def _candidate_snapshot(**overrides):
    values = {
        "platform": "Windows",
        "gpu_name": "NVIDIA GeForce RTX test device",
        "gpu_vendor": "NVIDIA",
        "compute_backend": "cuda",
        "cuda_available": True,
        "total_vram_mib": CANDIDATE_VRAM_FLOOR_MIB,
        "free_disk_mib": 40_000,
        "on_ac_power": True,
        "total_ram_mib": 32_768,
        "available_ram_mib": 20_000,
        "free_vram_mib": 7_500,
        "driver_version": "591.74",
        "cuda_runtime_version": "13.0",
        "compute_capability": "12.0",
    }
    values.update(overrides)
    return HardwareSnapshot(**values)


def _complete_observations(*, peak_reserved_vram_mib=7_000.0, accepted=True):
    # 2*1 + 1*2 + 31*4 == exactly 128 requested generations while proving
    # batch-size 1, 2, and 4 measurements were all taken.
    batch_sizes = [1, 1, 2] + ([4] * 31)
    return [
        BenchmarkObservation(
            batch_size=batch_size,
            requested_generations=batch_size,
            completed_generations=batch_size,
            accepted_generations=batch_size if accepted else 0,
            elapsed_seconds=batch_size * 0.5,
            peak_reserved_vram_mib=peak_reserved_vram_mib,
        )
        for batch_size in batch_sizes
    ]


def _with_accepted_total(observations, accepted_total):
    remaining = accepted_total
    updated = []
    for observation in observations:
        accepted = min(observation.completed_generations, remaining)
        updated.append(replace(observation, accepted_generations=accepted))
        remaining -= accepted
    assert remaining == 0
    return updated


def test_candidate_precheck_requires_benchmark_and_does_not_claim_a_proven_minimum():
    report = evaluate_precheck(_candidate_snapshot())

    assert report.status == BENCHMARK_REQUIRED
    assert report.benchmark_allowed is True
    assert report.candidate_floor_vram_mib == 8_000
    assert any("measured 128-generation benchmark" in reason for reason in report.reasons)
    assert any("candidate floor" in warning and "not a proven" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"platform": "Linux"}, "Windows-only"),
        ({"gpu_name": "AMD Radeon", "gpu_vendor": "AMD"}, "NVIDIA GPU"),
        ({"compute_backend": "cpu", "cuda_available": False}, "CUDA backend"),
        ({"total_vram_mib": 7_999, "free_vram_mib": 7_500}, "8 GB-class candidate floor"),
        ({"on_ac_power": False}, "Connect AC power"),
    ],
)
def test_precheck_rejects_hard_candidate_gate_failures(overrides, expected_reason):
    report = evaluate_precheck(_candidate_snapshot(**overrides))

    assert report.status == UNSUPPORTED
    assert report.benchmark_allowed is False
    assert any(expected_reason in reason for reason in report.reasons)


def test_nvidia_smi_8151_mib_8gb_class_card_reaches_benchmark_gate():
    report = evaluate_precheck(
        _candidate_snapshot(total_vram_mib=8_151, free_vram_mib=7_900)
    )

    assert report.status == BENCHMARK_REQUIRED
    assert report.candidate_floor_vram_mib == 8_000
    assert any("8 GB-class candidate floor" in warning for warning in report.warnings)


def test_precheck_requires_package_plus_scratch_disk_headroom():
    report = evaluate_precheck(
        _candidate_snapshot(free_disk_mib=2_999),
        pinned_package_mib=1_000,
        scratch_mib=2_000,
    )

    assert report.status == UNSUPPORTED
    assert report.required_free_disk_mib == 3_000
    assert any("only 2999 MiB" in reason for reason in report.reasons)


def test_unknown_ac_state_is_honest_warning_not_an_invented_failure():
    report = evaluate_precheck(_candidate_snapshot(on_ac_power=None))

    assert report.status == BENCHMARK_REQUIRED
    assert any("power state is unknown" in warning for warning in report.warnings)


def test_optional_runtime_manifest_facts_are_serialized_without_becoming_static_gates():
    snapshot = _candidate_snapshot(
        total_ram_mib=16_384,
        available_ram_mib=8_000,
        free_vram_mib=6_000,
        driver_version="600.01",
        cuda_runtime_version="13.1",
        compute_capability="12.1",
    )
    report = evaluate_precheck(snapshot)

    assert report.status == BENCHMARK_REQUIRED
    assert report.to_dict()["snapshot"] == snapshot.to_dict()
    assert snapshot.to_dict()["total_ram_mib"] == 16_384
    assert snapshot.to_dict()["available_ram_mib"] == 8_000
    assert snapshot.to_dict()["free_vram_mib"] == 6_000
    assert snapshot.to_dict()["driver_version"] == "600.01"
    assert snapshot.to_dict()["cuda_runtime_version"] == "13.1"
    assert snapshot.to_dict()["compute_capability"] == "12.1"


def test_no_observations_stays_benchmark_required():
    precheck = evaluate_precheck(_candidate_snapshot())
    verdict = evaluate_benchmark(precheck, [])

    assert verdict.status == BENCHMARK_REQUIRED
    assert verdict.qualified is False
    assert verdict.estimated_minutes_for_target is None
    assert any("No microbatch" in reason for reason in verdict.reasons)


def test_complete_clean_measured_run_qualifies_and_estimates_5000_clip_eta():
    precheck = evaluate_precheck(_candidate_snapshot())
    verdict = evaluate_benchmark(precheck, _complete_observations())

    assert verdict.status == QUALIFIED
    assert verdict.qualified is True
    assert verdict.requested_generations == 128
    assert verdict.completed_generations == 128
    assert verdict.accepted_generations == 128
    assert verdict.accepted_generation_ratio == 1.0
    assert verdict.batch_sizes_tested == (1, 2, 4)
    assert verdict.accepted_clips_per_minute == pytest.approx(120.0)
    assert verdict.estimated_minutes_for_target == pytest.approx(5_000 / 120.0)


def test_accepted_generation_ratio_just_below_discrete_boundary_is_unsupported():
    precheck = evaluate_precheck(_candidate_snapshot())
    # 115/128 is 89.84%; 116 is the first whole accepted count at or above 90%.
    observations = _with_accepted_total(_complete_observations(), 115)

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.accepted_generation_ratio == pytest.approx(115 / 128)
    assert verdict.accepted_generation_ratio < MIN_ACCEPTED_GENERATION_RATIO
    assert verdict.status == UNSUPPORTED
    assert any("requires at least 90%" in reason for reason in verdict.reasons)


def test_accepted_generation_ratio_at_discrete_boundary_qualifies():
    precheck = evaluate_precheck(_candidate_snapshot())
    observations = _with_accepted_total(_complete_observations(), 116)

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.accepted_generation_ratio == pytest.approx(116 / 128)
    assert verdict.accepted_generation_ratio >= MIN_ACCEPTED_GENERATION_RATIO
    assert verdict.status == QUALIFIED


def test_generation_count_contract_cannot_be_weakened_by_a_caller():
    precheck = evaluate_precheck(_candidate_snapshot())

    with pytest.raises(TypeError, match="required_generations"):
        evaluate_benchmark(
            precheck,
            _complete_observations(),
            required_generations=100,
        )


def test_exactly_ninety_percent_peak_reserved_vram_is_allowed():
    total_vram = CANDIDATE_VRAM_FLOOR_MIB
    precheck = evaluate_precheck(_candidate_snapshot(total_vram_mib=total_vram))
    verdict = evaluate_benchmark(
        precheck,
        _complete_observations(peak_reserved_vram_mib=total_vram * 0.90),
    )

    assert verdict.status == QUALIFIED
    assert verdict.peak_reserved_vram_ratio == pytest.approx(0.90)


def test_more_than_ninety_percent_peak_reserved_vram_is_unsupported():
    total_vram = CANDIDATE_VRAM_FLOOR_MIB
    precheck = evaluate_precheck(_candidate_snapshot(total_vram_mib=total_vram))
    verdict = evaluate_benchmark(
        precheck,
        _complete_observations(peak_reserved_vram_mib=total_vram * 0.901),
    )

    assert verdict.status == UNSUPPORTED
    assert any("allows at most 90%" in reason for reason in verdict.reasons)


@pytest.mark.parametrize(
    ("flag", "expected_reason"),
    [
        ("oom_detected", "out-of-memory"),
        ("hang_detected", "hang"),
        ("nan_detected", "NaN"),
        ("fallback_detected", "fallback"),
    ],
)
def test_any_observed_runtime_failure_is_unsupported(flag, expected_reason):
    precheck = evaluate_precheck(_candidate_snapshot())
    observations = _complete_observations()
    observations[0] = replace(observations[0], **{flag: True})

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.status == UNSUPPORTED
    assert any(expected_reason in reason for reason in verdict.reasons)


def test_incomplete_generation_is_an_observed_failure():
    precheck = evaluate_precheck(_candidate_snapshot())
    observations = _complete_observations()
    observations[0] = replace(
        observations[0],
        completed_generations=0,
        accepted_generations=0,
    )

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.status == UNSUPPORTED
    assert any("127 of 128" in reason for reason in verdict.reasons)


def test_zero_accepted_throughput_is_unsupported():
    precheck = evaluate_precheck(_candidate_snapshot())
    verdict = evaluate_benchmark(precheck, _complete_observations(accepted=False))

    assert verdict.status == UNSUPPORTED
    assert verdict.accepted_clips_per_minute == 0
    assert verdict.estimated_minutes_for_target is None
    assert any("greater than zero" in reason for reason in verdict.reasons)


def test_protocol_gaps_require_a_new_benchmark_instead_of_claiming_hardware_failure():
    precheck = evaluate_precheck(_candidate_snapshot())
    observations = _complete_observations()[1:]  # 127 total, but still contains 1/2/4.

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.status == BENCHMARK_REQUIRED
    assert any("exactly 128" in reason for reason in verdict.reasons)


def test_incomplete_microbatch_fails_even_when_protocol_is_also_short():
    precheck = evaluate_precheck(_candidate_snapshot())
    observations = _complete_observations()[1:]
    observations[0] = replace(
        observations[0],
        completed_generations=0,
        accepted_generations=0,
    )

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.status == UNSUPPORTED
    assert any("126 of 127" in reason for reason in verdict.reasons)


def test_all_required_batch_sizes_must_be_measured():
    precheck = evaluate_precheck(_candidate_snapshot())
    observations = [
        BenchmarkObservation(
            batch_size=4,
            requested_generations=4,
            completed_generations=4,
            accepted_generations=4,
            elapsed_seconds=2,
            peak_reserved_vram_mib=7_000,
        )
        for _ in range(32)
    ]

    verdict = evaluate_benchmark(precheck, observations)

    assert verdict.status == BENCHMARK_REQUIRED
    assert any("batch-size measurements: 1, 2" in reason for reason in verdict.reasons)


def test_unsupported_precheck_cannot_be_overridden_by_good_benchmark_numbers():
    precheck = evaluate_precheck(_candidate_snapshot(platform="Linux"))
    verdict = evaluate_benchmark(precheck, _complete_observations())

    assert verdict.status == UNSUPPORTED
    assert verdict.qualified is False
    assert any("Windows-only" in reason for reason in verdict.reasons)


def test_contracts_round_trip_through_json_without_custom_encoder():
    precheck = evaluate_precheck(_candidate_snapshot(on_ac_power=None))
    verdict = evaluate_benchmark(precheck, _complete_observations())

    encoded = json.dumps(verdict.to_dict())
    decoded = json.loads(encoded)

    assert decoded["status"] == QUALIFIED
    assert decoded["precheck"]["snapshot"]["on_ac_power"] is None
    assert decoded["precheck"]["snapshot"]["driver_version"] == "591.74"
    assert decoded["accepted_generation_ratio"] == 1.0
    assert decoded["observations"][0]["batch_size"] == 1


def test_invalid_snapshot_and_observation_values_fail_closed():
    with pytest.raises(TypeError, match="total_vram_mib"):
        _candidate_snapshot(total_vram_mib=True)
    with pytest.raises(ValueError, match="accepted_generations"):
        BenchmarkObservation(
            batch_size=1,
            requested_generations=1,
            completed_generations=1,
            accepted_generations=2,
            elapsed_seconds=1,
            peak_reserved_vram_mib=1,
        )
    with pytest.raises(ValueError, match="finite"):
        BenchmarkObservation(
            batch_size=1,
            requested_generations=1,
            completed_generations=1,
            accepted_generations=1,
            elapsed_seconds=float("nan"),
            peak_reserved_vram_mib=1,
        )
    with pytest.raises(ValueError, match="pinned_package_mib"):
        evaluate_precheck(_candidate_snapshot(), pinned_package_mib=0)


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"total_ram_mib": -1}, "total_ram_mib"),
        ({"available_ram_mib": 40_000}, "available_ram_mib cannot exceed"),
        ({"free_vram_mib": 9_000}, "free_vram_mib cannot exceed"),
        ({"driver_version": "  "}, "driver_version"),
        ({"cuda_runtime_version": 13.0}, "cuda_runtime_version"),
        ({"compute_capability": ""}, "compute_capability"),
    ],
)
def test_optional_runtime_manifest_facts_are_validated(overrides, expected_error):
    with pytest.raises((TypeError, ValueError), match=expected_error):
        _candidate_snapshot(**overrides)


def test_non_observation_input_is_rejected_instead_of_trusted():
    precheck = evaluate_precheck(_candidate_snapshot())

    with pytest.raises(TypeError, match=r"observations\[0\]"):
        evaluate_benchmark(precheck, [object()])
