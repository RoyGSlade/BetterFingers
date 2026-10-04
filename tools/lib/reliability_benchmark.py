"""Reliability benchmark harness (§6.1) — the M1 gate.

The core dictation loop has to be *dependable*, not just functional. This module
is the scaffolding for proving it: it automates what can be automated (mock
core-loop repetition and backend health probes) and tracks the
hardware-bound checks (audio-device unplug/replug, sleep/resume, long recordings,
the injection matrix) as manual items an operator marks off. It computes a single
pass/fail gate over all of them.

The runner and report logic here are pure and dependency-injected, so they
unit-test without a live backend, mic, or models. The live wiring — driving a
real sidecar over HTTP — lives in ``tools/reliability_benchmark.py``.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

AUTOMATED = "automated"
MANUAL = "manual"

PASS = "pass"
FAIL = "fail"
SKIP = "skip"  # manual check not yet performed
PENDING = "pending"


@dataclass
class CheckResult:
    name: str
    category: str
    status: str = PENDING
    detail: str = ""
    iterations_ok: int = 0
    iterations_total: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "detail": self.detail,
            "iterations_ok": self.iterations_ok,
            "iterations_total": self.iterations_total,
        }


# The full benchmark surface. Automated checks run here; manual checks are the
# hardware-bound ones an operator confirms (they gate the run just like the
# automated ones — a manual FAIL fails the gate, an unperformed manual check
# leaves the gate incomplete).
MANUAL_CHECKS: List[CheckResult] = [
    CheckResult("real_dictations_100", MANUAL, detail="100 production-path microphone dictations complete or recover."),
    CheckResult("full_restart_cycles_50", MANUAL, detail="50 full application/backend restarts return to a usable state."),
    CheckResult("long_recording_5min", MANUAL, detail="5-minute dictation completes and is reviewable."),
    CheckResult("long_recording_15min", MANUAL, detail="15-minute dictation completes."),
    CheckResult("long_recording_30min", MANUAL, detail="30-minute dictation completes."),
    CheckResult("long_recording_60min", MANUAL, detail="60-minute dictation completes."),
    CheckResult("audio_device_unplug_replug", MANUAL, detail="Unplug/replug the mic mid-session; recording recovers."),
    CheckResult("sleep_resume", MANUAL, detail="Sleep and resume the machine; the app keeps working."),
    CheckResult("clipboard_restoration", MANUAL, detail="After injection the prior clipboard contents are restored."),
    CheckResult("injection_matrix_top10", MANUAL, detail="Injection succeeds across the M2 top-10 target apps."),
    CheckResult("backend_killed_during_processing", MANUAL, detail="Killing the backend during processing preserves a recoverable recording and draft."),
    CheckResult("model_download_interrupt_resume", MANUAL, detail="An interrupted model download resumes and verifies successfully."),
    CheckResult("privacy_wipe", MANUAL, detail="Privacy wipe removes the data categories it promises to remove."),
    CheckResult("failed_transcription_recovery", MANUAL, detail="A failed transcription preserves recoverable audio and reports an understandable error."),
    CheckResult("failed_llm_recovery", MANUAL, detail="A failed local rewrite preserves a recoverable draft and reports an understandable error."),
    CheckResult("failed_placement_recovery", MANUAL, detail="A failed placement preserves the approved draft and reports an understandable error."),
]

REQUIRED_ARTIFACT_FIELDS = ("version", "tag", "commit", "filename", "sha256")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class ManualResultsError(ValueError):
    """The operator-supplied manual evidence does not satisfy the release gate."""


def load_manual_results(path) -> tuple[List[CheckResult], dict]:
    """Load and strictly validate completed hardware/operator evidence.

    The file must bind the results to one exact artifact and provide exactly
    one PASS or FAIL record for every name in ``MANUAL_CHECKS``.  A report may
    be honest and red, but it may never be green while evidence is missing.
    """
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ManualResultsError("manual results must be a JSON object")

    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        raise ManualResultsError("manual results must contain an artifact object")
    normalized_artifact = {}
    for field_name in REQUIRED_ARTIFACT_FIELDS:
        value = artifact.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ManualResultsError(f"artifact.{field_name} must be a nonempty string")
        normalized_artifact[field_name] = value.strip()
    if not _SHA256_RE.fullmatch(normalized_artifact["sha256"]):
        raise ManualResultsError("artifact.sha256 must be exactly 64 hexadecimal characters")
    normalized_artifact["sha256"] = normalized_artifact["sha256"].lower()
    if not _COMMIT_RE.fullmatch(normalized_artifact["commit"]):
        raise ManualResultsError("artifact.commit must be exactly 40 hexadecimal characters")
    normalized_artifact["commit"] = normalized_artifact["commit"].lower()
    if normalized_artifact["tag"] != f"v{normalized_artifact['version']}":
        raise ManualResultsError("artifact.tag must equal v plus artifact.version")
    for key, value in artifact.items():
        if key not in normalized_artifact:
            normalized_artifact[key] = value

    rows = payload.get("checks")
    if not isinstance(rows, list):
        raise ManualResultsError("manual results checks must be an array")

    required = {check.name for check in MANUAL_CHECKS}
    seen = set()
    results = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ManualResultsError(f"checks[{index}] must be an object")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ManualResultsError(f"checks[{index}].name must be a nonempty string")
        name = name.strip()
        if name not in required:
            raise ManualResultsError(f"unknown manual check: {name}")
        if name in seen:
            raise ManualResultsError(f"duplicate manual check: {name}")
        seen.add(name)

        raw_status = row.get("status")
        if not isinstance(raw_status, str) or raw_status.strip().lower() not in (PASS, FAIL):
            raise ManualResultsError(f"manual check {name} status must be PASS or FAIL")
        detail = row.get("detail")
        if not isinstance(detail, str) or not detail.strip():
            raise ManualResultsError(f"manual check {name} detail must be a nonempty string")
        results.append(
            CheckResult(name, MANUAL, status=raw_status.strip().lower(), detail=detail.strip())
        )

    missing = sorted(required - seen)
    if missing:
        raise ManualResultsError("missing required manual checks: " + ", ".join(missing))
    return results, normalized_artifact


def run_repeated(name: str, iterations: int, step: Callable[[int], None], stop_on_first_failure: bool = False) -> CheckResult:
    """Run ``step(i)`` ``iterations`` times, counting successes. ``step`` signals
    failure by raising or returning a falsy value (returning ``None`` counts as
    success — the common "it just ran" case). Never raises: a failing iteration
    is recorded, not propagated.

    Used for: 100 consecutive dictations, 50 restart-recovery cycles, and any
    other "do it N times and none may fail" check.
    """
    total = max(0, int(iterations))
    ok = 0
    failures: List[str] = []
    for i in range(total):
        try:
            result = step(i)
            if result is None or result:
                ok += 1
            else:
                failures.append(f"iteration {i}: step returned {result!r}")
                if stop_on_first_failure:
                    break
        except Exception as exc:  # noqa: BLE001 — a benchmark records failures, never crashes
            failures.append(f"iteration {i}: {type(exc).__name__}: {exc}")
            if stop_on_first_failure:
                break
    status = PASS if (total > 0 and ok == total) else FAIL
    detail = "all iterations passed" if status == PASS else "; ".join(failures[:5]) or "no iterations run"
    return CheckResult(name, AUTOMATED, status=status, detail=detail, iterations_ok=ok, iterations_total=total)


def run_once(name: str, step: Callable[[], None]) -> CheckResult:
    """Run a single automated check; ``step`` raises or returns falsy on failure."""
    try:
        result = step()
        ok = result is None or bool(result)
        return CheckResult(
            name,
            AUTOMATED,
            status=PASS if ok else FAIL,
            detail="passed" if ok else f"step returned {result!r}",
            iterations_ok=1 if ok else 0,
            iterations_total=1,
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name, AUTOMATED, status=FAIL, detail=f"{type(exc).__name__}: {exc}", iterations_ok=0, iterations_total=1)


@dataclass
class BenchmarkReport:
    results: List[CheckResult] = field(default_factory=list)
    artifact: dict = field(default_factory=dict)

    def add(self, result: CheckResult):
        self.results.append(result)

    def include_manual(self, checks: Optional[List[CheckResult]] = None):
        """Append the manual checklist (as SKIP/pending) so the report and gate
        account for hardware-bound checks an operator still has to perform."""
        for check in (checks if checks is not None else MANUAL_CHECKS):
            self.results.append(
                CheckResult(check.name, MANUAL, status=SKIP, detail=check.detail)
            )

    @property
    def failed(self) -> List[CheckResult]:
        return [r for r in self.results if r.status == FAIL]

    @property
    def incomplete(self) -> List[CheckResult]:
        return [r for r in self.results if r.status in (SKIP, PENDING)]

    @property
    def passed(self) -> bool:
        """The gate: every check has run and none failed. An unperformed manual
        check leaves the gate incomplete (not passed) — silence is not success."""
        return bool(self.results) and not self.failed and not self.incomplete

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "artifact": self.artifact,
            "total": len(self.results),
            "failed": len(self.failed),
            "incomplete": len(self.incomplete),
            "results": [r.to_dict() for r in self.results],
        }

    def summary(self) -> str:
        lines = []
        for r in self.results:
            mark = {PASS: "PASS", FAIL: "FAIL", SKIP: "TODO", PENDING: "...."}.get(r.status, r.status.upper())
            counts = f" ({r.iterations_ok}/{r.iterations_total})" if r.iterations_total else ""
            lines.append(f"[{mark}] {r.name}{counts} — {r.detail}")
        gate = "GATE PASSED" if self.passed else "GATE NOT PASSED"
        lines.append(
            f"{gate}: {len(self.failed)} failed, {len(self.incomplete)} incomplete of {len(self.results)}"
        )
        return "\n".join(lines)


def build_report(
    call: Callable[..., dict],
    dictations: int = 100,
    health_checks: int = 50,
    include_manual: bool = True,
    manual_results: Optional[List[CheckResult]] = None,
    artifact_metadata: Optional[dict] = None,
) -> BenchmarkReport:
    """Assemble the automated benchmark against a live sidecar. ``call`` is an
    injected transport — ``call(method, path) -> dict`` that raises on any
    non-2xx — so this is testable with a fake backend (the HTTP wiring lives in
    ``tools/reliability_benchmark.py``).

    The dictation core-loop is a headless proxy for the real loop: it drives the
    mock-draft → review → accept → decline plumbing repeatedly. True audio,
    injection, restart-recovery, and the hardware checks are the manual items.
    """
    report = BenchmarkReport(artifact=dict(artifact_metadata or {}))

    report.add(run_once("backend_reachable", lambda: bool(call("GET", "/health").get("status"))))

    def dictation_step(i):
        draft = call("POST", "/drafts/test-mock")
        draft_id = draft["id"]
        latest = call("GET", "/drafts/latest").get("draft")
        if not latest or latest["id"] != draft_id:
            return False
        call("POST", f"/drafts/{draft_id}/accept")
        call("POST", f"/drafts/{draft_id}/decline")
        return True

    report.add(run_repeated("dictation_core_loop", dictations, dictation_step))
    report.add(run_repeated("backend_health_stable", health_checks, lambda i: bool(call("GET", "/health").get("status"))))
    report.add(run_once("recordings_bin_reachable", lambda: "recordings" in call("GET", "/recordings")))
    report.add(run_once("jobs_registry_reachable", lambda: "jobs" in call("GET", "/jobs")))

    if manual_results is not None:
        for result in manual_results:
            report.add(result)
    elif include_manual:
        report.include_manual()
    return report
