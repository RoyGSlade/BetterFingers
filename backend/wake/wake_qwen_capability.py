"""Pure capability gates for the local Qwen wake-enrollment worker.

This module deliberately does not inspect hardware, import Qwen, start a
process, or use the network.  Callers supply a hardware snapshot and measured
microbatch observations.  That keeps the gate deterministic and lets the UI
describe an honest distinction between a *candidate* machine and one that has
completed the qualification benchmark.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Literal


UNSUPPORTED = "unsupported"
BENCHMARK_REQUIRED = "benchmark_required"
QUALIFIED = "qualified"
CapabilityStatus = Literal["unsupported", "benchmark_required", "qualified"]

# This is intentionally named a candidate floor.  It must not be surfaced as a
# proven minimum until real Windows hardware completes the measured gate.
CANDIDATE_VRAM_FLOOR_MIB = 8_000
PINNED_QWEN_PACKAGE_MIB = 4_650
DEFAULT_SCRATCH_MIB = 8 * 1024
REQUIRED_BENCHMARK_GENERATIONS = 128
REQUIRED_BATCH_SIZES = (1, 2, 4)
MAX_PEAK_RESERVED_VRAM_RATIO = 0.90
MIN_ACCEPTED_GENERATION_RATIO = 0.90
DEFAULT_ACCEPTED_POSITIVE_TARGET = 5_000


def _require_nonnegative_int(value: object, name: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer" + (" or None" if allow_none else ""))
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _require_positive_int(value: object, name: str) -> int:
    normalized = _require_nonnegative_int(value, name)
    assert normalized is not None
    if normalized == 0:
        raise ValueError(f"{name} must be positive")
    return normalized


def _require_finite_number(
    value: object,
    name: str,
    *,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if normalized < 0 or (positive and normalized == 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be {qualifier}")
    return normalized


def _require_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


@dataclass(frozen=True)
class HardwareSnapshot:
    """Serializable facts collected outside this side-effect-free module."""

    platform: str
    gpu_name: str | None
    gpu_vendor: str | None
    compute_backend: str | None
    cuda_available: bool
    total_vram_mib: int | None
    free_disk_mib: int | None
    on_ac_power: bool | None
    total_ram_mib: int | None = None
    available_ram_mib: int | None = None
    free_vram_mib: int | None = None
    driver_version: str | None = None
    cuda_runtime_version: str | None = None
    compute_capability: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.platform, str) or not self.platform.strip():
            raise ValueError("platform must be a nonempty string")
        _require_optional_text(self.gpu_name, "gpu_name")
        _require_optional_text(self.gpu_vendor, "gpu_vendor")
        _require_optional_text(self.compute_backend, "compute_backend")
        if not isinstance(self.cuda_available, bool):
            raise TypeError("cuda_available must be a boolean")
        _require_nonnegative_int(self.total_vram_mib, "total_vram_mib", allow_none=True)
        _require_nonnegative_int(self.free_disk_mib, "free_disk_mib", allow_none=True)
        if self.on_ac_power is not None and not isinstance(self.on_ac_power, bool):
            raise TypeError("on_ac_power must be a boolean or None")
        total_ram = _require_nonnegative_int(
            self.total_ram_mib,
            "total_ram_mib",
            allow_none=True,
        )
        available_ram = _require_nonnegative_int(
            self.available_ram_mib,
            "available_ram_mib",
            allow_none=True,
        )
        free_vram = _require_nonnegative_int(
            self.free_vram_mib,
            "free_vram_mib",
            allow_none=True,
        )
        _require_optional_text(self.driver_version, "driver_version")
        _require_optional_text(self.cuda_runtime_version, "cuda_runtime_version")
        _require_optional_text(self.compute_capability, "compute_capability")
        if total_ram is not None and available_ram is not None and available_ram > total_ram:
            raise ValueError("available_ram_mib cannot exceed total_ram_mib")
        if (
            self.total_vram_mib is not None
            and free_vram is not None
            and free_vram > self.total_vram_mib
        ):
            raise ValueError("free_vram_mib cannot exceed total_vram_mib")

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "gpu_name": self.gpu_name,
            "gpu_vendor": self.gpu_vendor,
            "compute_backend": self.compute_backend,
            "cuda_available": self.cuda_available,
            "total_vram_mib": self.total_vram_mib,
            "free_disk_mib": self.free_disk_mib,
            "on_ac_power": self.on_ac_power,
            "total_ram_mib": self.total_ram_mib,
            "available_ram_mib": self.available_ram_mib,
            "free_vram_mib": self.free_vram_mib,
            "driver_version": self.driver_version,
            "cuda_runtime_version": self.cuda_runtime_version,
            "compute_capability": self.compute_capability,
        }


@dataclass(frozen=True)
class PrecheckReport:
    """Outcome of the cheap candidate gate, before any model is loaded."""

    status: CapabilityStatus
    snapshot: HardwareSnapshot
    candidate_floor_vram_mib: int
    pinned_package_mib: int
    scratch_mib: int
    required_free_disk_mib: int
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def benchmark_allowed(self) -> bool:
        return self.status == BENCHMARK_REQUIRED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "benchmark_allowed": self.benchmark_allowed,
            "snapshot": self.snapshot.to_dict(),
            "candidate_floor_vram_mib": self.candidate_floor_vram_mib,
            "pinned_package_mib": self.pinned_package_mib,
            "scratch_mib": self.scratch_mib,
            "required_free_disk_mib": self.required_free_disk_mib,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BenchmarkObservation:
    """One measured microbatch from an external Qwen benchmark runner."""

    batch_size: int
    requested_generations: int
    completed_generations: int
    accepted_generations: int
    elapsed_seconds: float
    peak_reserved_vram_mib: float
    oom_detected: bool = False
    hang_detected: bool = False
    nan_detected: bool = False
    fallback_detected: bool = False

    def __post_init__(self) -> None:
        batch_size = _require_positive_int(self.batch_size, "batch_size")
        requested = _require_positive_int(self.requested_generations, "requested_generations")
        completed = _require_nonnegative_int(self.completed_generations, "completed_generations")
        accepted = _require_nonnegative_int(self.accepted_generations, "accepted_generations")
        assert completed is not None and accepted is not None
        if requested > batch_size:
            raise ValueError("requested_generations cannot exceed this microbatch's batch_size")
        if completed > requested:
            raise ValueError("completed_generations cannot exceed requested_generations")
        if accepted > completed:
            raise ValueError("accepted_generations cannot exceed completed_generations")
        _require_finite_number(self.elapsed_seconds, "elapsed_seconds", positive=True)
        _require_finite_number(self.peak_reserved_vram_mib, "peak_reserved_vram_mib")
        for name in ("oom_detected", "hang_detected", "nan_detected", "fallback_detected"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")

    @property
    def accepted_clips_per_minute(self) -> float:
        return self.accepted_generations * 60.0 / self.elapsed_seconds

    def to_dict(self) -> dict:
        return {
            "batch_size": self.batch_size,
            "requested_generations": self.requested_generations,
            "completed_generations": self.completed_generations,
            "accepted_generations": self.accepted_generations,
            "elapsed_seconds": self.elapsed_seconds,
            "peak_reserved_vram_mib": self.peak_reserved_vram_mib,
            "accepted_clips_per_minute": self.accepted_clips_per_minute,
            "oom_detected": self.oom_detected,
            "hang_detected": self.hang_detected,
            "nan_detected": self.nan_detected,
            "fallback_detected": self.fallback_detected,
        }


@dataclass(frozen=True)
class CapabilityVerdict:
    """Final, serializable decision after precheck and measured evidence."""

    status: CapabilityStatus
    precheck: PrecheckReport
    observations: tuple[BenchmarkObservation, ...]
    required_generations: int
    requested_generations: int
    completed_generations: int
    accepted_generations: int
    batch_sizes_tested: tuple[int, ...]
    peak_reserved_vram_mib: float | None
    peak_reserved_vram_ratio: float | None
    accepted_generation_ratio: float | None
    accepted_clips_per_minute: float | None
    target_accepted_positives: int
    estimated_minutes_for_target: float | None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def qualified(self) -> bool:
        return self.status == QUALIFIED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "qualified": self.qualified,
            "precheck": self.precheck.to_dict(),
            "observations": [observation.to_dict() for observation in self.observations],
            "required_generations": self.required_generations,
            "requested_generations": self.requested_generations,
            "completed_generations": self.completed_generations,
            "accepted_generations": self.accepted_generations,
            "batch_sizes_tested": list(self.batch_sizes_tested),
            "peak_reserved_vram_mib": self.peak_reserved_vram_mib,
            "peak_reserved_vram_ratio": self.peak_reserved_vram_ratio,
            "accepted_generation_ratio": self.accepted_generation_ratio,
            "accepted_clips_per_minute": self.accepted_clips_per_minute,
            "target_accepted_positives": self.target_accepted_positives,
            "estimated_minutes_for_target": self.estimated_minutes_for_target,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


def _is_windows(platform_name: str) -> bool:
    normalized = platform_name.strip().lower()
    return normalized in {"windows", "win32"} or normalized.startswith("windows ")


def _is_nvidia(snapshot: HardwareSnapshot) -> bool:
    vendor = (snapshot.gpu_vendor or "").strip().lower()
    name = (snapshot.gpu_name or "").strip().lower()
    return "nvidia" in vendor or "nvidia" in name


def evaluate_precheck(
    snapshot: HardwareSnapshot,
    *,
    pinned_package_mib: int = PINNED_QWEN_PACKAGE_MIB,
    scratch_mib: int = DEFAULT_SCRATCH_MIB,
) -> PrecheckReport:
    """Apply the offline candidate gate to an injected hardware snapshot."""

    if not isinstance(snapshot, HardwareSnapshot):
        raise TypeError("snapshot must be a HardwareSnapshot")
    package = _require_positive_int(pinned_package_mib, "pinned_package_mib")
    scratch = _require_positive_int(scratch_mib, "scratch_mib")
    required_disk = package + scratch
    reasons: list[str] = []
    warnings: list[str] = []

    if not _is_windows(snapshot.platform):
        reasons.append("Qwen wake enrollment is currently a Windows-only qualification path.")
    if not _is_nvidia(snapshot):
        reasons.append("The Qwen 1.7B candidate path requires an NVIDIA GPU.")
    if not snapshot.cuda_available or (snapshot.compute_backend or "").strip().lower() != "cuda":
        reasons.append("A working CUDA backend is required; CPU and other fallback paths are not qualified.")

    if snapshot.total_vram_mib is None:
        reasons.append("Total dedicated VRAM could not be verified.")
    elif snapshot.total_vram_mib < CANDIDATE_VRAM_FLOOR_MIB:
        reasons.append(
            f"Detected {snapshot.total_vram_mib} MiB VRAM, below the "
            f"{CANDIDATE_VRAM_FLOOR_MIB} MiB 8 GB-class candidate floor."
        )

    if snapshot.free_disk_mib is None:
        reasons.append("Free disk space could not be verified.")
    elif snapshot.free_disk_mib < required_disk:
        reasons.append(
            f"Need at least {required_disk} MiB free for the pinned package "
            f"({package} MiB) plus scratch space ({scratch} MiB); "
            f"only {snapshot.free_disk_mib} MiB is available."
        )

    if snapshot.on_ac_power is False:
        reasons.append("Connect AC power before lending the GPU to wake enrollment.")
    elif snapshot.on_ac_power is None:
        warnings.append("AC power state is unknown; connect power before running the benchmark.")

    if reasons:
        status: CapabilityStatus = UNSUPPORTED
    else:
        status = BENCHMARK_REQUIRED
        reasons.append("Candidate precheck passed; the measured 128-generation benchmark is still required.")
        warnings.append(
            "The 8 GB-class candidate floor is not a proven or advertised minimum."
        )

    return PrecheckReport(
        status=status,
        snapshot=snapshot,
        candidate_floor_vram_mib=CANDIDATE_VRAM_FLOOR_MIB,
        pinned_package_mib=package,
        scratch_mib=scratch,
        required_free_disk_mib=required_disk,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def evaluate_benchmark(
    precheck: PrecheckReport,
    observations: Iterable[BenchmarkObservation],
    *,
    target_accepted_positives: int = DEFAULT_ACCEPTED_POSITIVE_TARGET,
) -> CapabilityVerdict:
    """Evaluate externally measured microbatches without running the model.

    Missing or protocol-incomplete evidence remains ``benchmark_required``.
    A precheck failure or an observed safety/runtime failure is ``unsupported``.
    Only the complete, clean measured run becomes ``qualified``.
    """

    if not isinstance(precheck, PrecheckReport):
        raise TypeError("precheck must be a PrecheckReport")
    required = REQUIRED_BENCHMARK_GENERATIONS
    target = _require_positive_int(target_accepted_positives, "target_accepted_positives")
    try:
        measured = tuple(observations)
    except TypeError as exc:
        raise TypeError("observations must be an iterable of BenchmarkObservation values") from exc
    for index, observation in enumerate(measured):
        if not isinstance(observation, BenchmarkObservation):
            raise TypeError(f"observations[{index}] must be a BenchmarkObservation")

    requested = sum(item.requested_generations for item in measured)
    completed = sum(item.completed_generations for item in measured)
    accepted = sum(item.accepted_generations for item in measured)
    elapsed = sum(item.elapsed_seconds for item in measured)
    batch_sizes = tuple(sorted({item.batch_size for item in measured}))
    peak_mib = max((item.peak_reserved_vram_mib for item in measured), default=None)
    total_vram_mib = precheck.snapshot.total_vram_mib
    peak_ratio = (
        peak_mib / total_vram_mib
        if peak_mib is not None and total_vram_mib is not None and total_vram_mib > 0
        else None
    )
    accepted_rate = accepted * 60.0 / elapsed if elapsed > 0 else None
    accepted_ratio = accepted / completed if completed > 0 else None
    eta_minutes = target / accepted_rate if accepted_rate is not None and accepted_rate > 0 else None

    reasons: list[str] = []
    warnings = list(precheck.warnings)
    evidence_gaps: list[str] = []
    observed_failures: list[str] = []

    if precheck.status == UNSUPPORTED:
        reasons.extend(precheck.reasons)
        status: CapabilityStatus = UNSUPPORTED
    else:
        if not measured:
            evidence_gaps.append("No microbatch measurements were supplied.")
        if requested != required:
            evidence_gaps.append(
                f"Benchmark must request exactly {required} generations; received {requested}."
            )
        missing_batches = sorted(set(REQUIRED_BATCH_SIZES) - set(batch_sizes))
        if missing_batches:
            evidence_gaps.append(
                "Benchmark is missing required batch-size measurements: "
                + ", ".join(str(value) for value in missing_batches)
                + "."
            )

        if measured and completed != requested:
            observed_failures.append(
                f"Only {completed} of {requested} requested generations completed."
            )
        if any(item.oom_detected for item in measured):
            observed_failures.append("An out-of-memory condition was observed.")
        if any(item.hang_detected for item in measured):
            observed_failures.append("A generation hang was observed.")
        if any(item.nan_detected for item in measured):
            observed_failures.append("NaN or non-finite model output was observed.")
        if any(item.fallback_detected for item in measured):
            observed_failures.append("A CPU or non-CUDA fallback was observed.")
        if peak_ratio is None and measured:
            evidence_gaps.append("Peak reserved VRAM could not be compared with total VRAM.")
        elif peak_ratio is not None and peak_ratio > MAX_PEAK_RESERVED_VRAM_RATIO:
            observed_failures.append(
                f"Peak reserved VRAM reached {peak_ratio:.1%}; the gate allows at most "
                f"{MAX_PEAK_RESERVED_VRAM_RATIO:.0%}."
            )
        if measured and (accepted_rate is None or accepted_rate <= 0):
            observed_failures.append("Accepted-clips throughput must be greater than zero.")
        if (
            measured
            and accepted_ratio is not None
            and accepted_ratio < MIN_ACCEPTED_GENERATION_RATIO
        ):
            observed_failures.append(
                f"Only {accepted} of {completed} completed generations passed acceptance "
                f"({accepted_ratio:.1%}); the gate requires at least "
                f"{MIN_ACCEPTED_GENERATION_RATIO:.0%}."
            )

        if observed_failures:
            status = UNSUPPORTED
            reasons.extend(observed_failures)
            reasons.extend(evidence_gaps)
        elif evidence_gaps:
            status = BENCHMARK_REQUIRED
            reasons.extend(evidence_gaps)
        else:
            status = QUALIFIED
            reasons.append(
                "Candidate hardware completed the measured benchmark; qualification applies only "
                "to this recorded configuration."
            )

    return CapabilityVerdict(
        status=status,
        precheck=precheck,
        observations=measured,
        required_generations=required,
        requested_generations=requested,
        completed_generations=completed,
        accepted_generations=accepted,
        batch_sizes_tested=batch_sizes,
        peak_reserved_vram_mib=peak_mib,
        peak_reserved_vram_ratio=peak_ratio,
        accepted_generation_ratio=accepted_ratio,
        accepted_clips_per_minute=accepted_rate,
        target_accepted_positives=target,
        estimated_minutes_for_target=eta_minutes,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


__all__ = [
    "BENCHMARK_REQUIRED",
    "CANDIDATE_VRAM_FLOOR_MIB",
    "CapabilityVerdict",
    "DEFAULT_ACCEPTED_POSITIVE_TARGET",
    "DEFAULT_SCRATCH_MIB",
    "HardwareSnapshot",
    "BenchmarkObservation",
    "MAX_PEAK_RESERVED_VRAM_RATIO",
    "MIN_ACCEPTED_GENERATION_RATIO",
    "PINNED_QWEN_PACKAGE_MIB",
    "PrecheckReport",
    "QUALIFIED",
    "REQUIRED_BATCH_SIZES",
    "REQUIRED_BENCHMARK_GENERATIONS",
    "UNSUPPORTED",
    "evaluate_benchmark",
    "evaluate_precheck",
]
