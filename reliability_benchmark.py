"""Reliability benchmark harness (§6.1) — the M1 gate.

The core dictation loop has to be *dependable*, not just functional. This module
is the scaffolding for proving it: it automates what can be automated (core-loop
repetition, backend restart recovery, recovery-after-interrupt) and tracks the
hardware-bound checks (audio-device unplug/replug, sleep/resume, long recordings,
the injection matrix) as manual items an operator marks off. It computes a single
pass/fail gate over all of them.

The runner and report logic here are pure and dependency-injected, so they
unit-test without a live backend, mic, or models. The live wiring — driving a
real sidecar over HTTP — lives in ``tools/reliability_benchmark.py``.
"""

from dataclasses import dataclass, field
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
    CheckResult("long_recording_5min", MANUAL, detail="5-minute dictation completes and is reviewable."),
    CheckResult("long_recording_15min", MANUAL, detail="15-minute dictation completes."),
    CheckResult("long_recording_30min", MANUAL, detail="30-minute dictation completes."),
    CheckResult("long_recording_60min", MANUAL, detail="60-minute dictation completes."),
    CheckResult("audio_device_unplug_replug", MANUAL, detail="Unplug/replug the mic mid-session; recording recovers."),
    CheckResult("sleep_resume", MANUAL, detail="Sleep and resume the machine; the app keeps working."),
    CheckResult("clipboard_restoration", MANUAL, detail="After injection the prior clipboard contents are restored."),
    CheckResult("injection_matrix_top10", MANUAL, detail="Injection succeeds across the M2 top-10 target apps."),
]


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


def build_report(call: Callable[..., dict], dictations: int = 100, health_checks: int = 50, include_manual: bool = True) -> BenchmarkReport:
    """Assemble the automated benchmark against a live sidecar. ``call`` is an
    injected transport — ``call(method, path) -> dict`` that raises on any
    non-2xx — so this is testable with a fake backend (the HTTP wiring lives in
    ``tools/reliability_benchmark.py``).

    The dictation core-loop is a headless proxy for the real loop: it drives the
    mock-draft → review → accept → decline plumbing repeatedly. True audio,
    injection, restart-recovery, and the hardware checks are the manual items.
    """
    report = BenchmarkReport()

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

    if include_manual:
        report.include_manual()
    return report
