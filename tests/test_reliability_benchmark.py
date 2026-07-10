"""Reliability benchmark harness (§6.1): the runner counts iteration failures
and the report computes a single pass/fail gate that treats an unperformed
manual check as incomplete (not passed)."""

import unittest

import reliability_benchmark as rb


class RunRepeatedTests(unittest.TestCase):
    def test_all_pass(self):
        result = rb.run_repeated("loop", 5, lambda i: None)
        self.assertEqual(result.status, rb.PASS)
        self.assertEqual((result.iterations_ok, result.iterations_total), (5, 5))

    def test_returning_falsy_is_failure(self):
        result = rb.run_repeated("loop", 3, lambda i: i != 1)  # iteration 1 returns False
        self.assertEqual(result.status, rb.FAIL)
        self.assertEqual((result.iterations_ok, result.iterations_total), (2, 3))
        self.assertIn("iteration 1", result.detail)

    def test_raising_is_failure_not_propagated(self):
        def step(i):
            if i == 2:
                raise RuntimeError("kaboom")

        result = rb.run_repeated("loop", 4, step)
        self.assertEqual(result.status, rb.FAIL)
        self.assertEqual(result.iterations_ok, 3)
        self.assertIn("kaboom", result.detail)

    def test_stop_on_first_failure(self):
        calls = []

        def step(i):
            calls.append(i)
            return i != 0  # fail immediately

        result = rb.run_repeated("loop", 10, step, stop_on_first_failure=True)
        self.assertEqual(result.status, rb.FAIL)
        self.assertEqual(calls, [0])  # stopped after the first failure

    def test_zero_iterations_is_failure(self):
        result = rb.run_repeated("loop", 0, lambda i: None)
        self.assertEqual(result.status, rb.FAIL)


class RunOnceTests(unittest.TestCase):
    def test_pass_and_fail(self):
        self.assertEqual(rb.run_once("c", lambda: True).status, rb.PASS)
        self.assertEqual(rb.run_once("c", lambda: None).status, rb.PASS)
        self.assertEqual(rb.run_once("c", lambda: False).status, rb.FAIL)

    def test_exception_is_fail(self):
        result = rb.run_once("c", lambda: (_ for _ in ()).throw(ValueError("nope")))
        self.assertEqual(result.status, rb.FAIL)
        self.assertIn("nope", result.detail)


class BenchmarkReportTests(unittest.TestCase):
    def test_all_automated_pass_but_manual_incomplete_is_not_passed(self):
        report = rb.BenchmarkReport()
        report.add(rb.run_repeated("dictations", 3, lambda i: None))
        report.include_manual()
        self.assertFalse(report.passed)  # manual checks still pending
        self.assertEqual(len(report.incomplete), len(rb.MANUAL_CHECKS))
        self.assertEqual(report.failed, [])

    def test_gate_passes_only_when_everything_passes(self):
        report = rb.BenchmarkReport()
        report.add(rb.run_repeated("dictations", 3, lambda i: None))
        # Operator confirms every manual check.
        for check in rb.MANUAL_CHECKS:
            report.add(rb.CheckResult(check.name, rb.MANUAL, status=rb.PASS, detail="confirmed"))
        self.assertTrue(report.passed)

    def test_any_failure_fails_the_gate(self):
        report = rb.BenchmarkReport()
        report.add(rb.run_repeated("dictations", 2, lambda i: False))  # fails
        for check in rb.MANUAL_CHECKS:
            report.add(rb.CheckResult(check.name, rb.MANUAL, status=rb.PASS))
        self.assertFalse(report.passed)
        self.assertEqual(len(report.failed), 1)

    def test_empty_report_is_not_passed(self):
        self.assertFalse(rb.BenchmarkReport().passed)

    def test_to_dict_and_summary_shapes(self):
        report = rb.BenchmarkReport()
        report.add(rb.run_repeated("dictations", 2, lambda i: None))
        report.include_manual([rb.CheckResult("manual_x", rb.MANUAL, detail="do a thing")])
        payload = report.to_dict()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["incomplete"], 1)
        self.assertFalse(payload["passed"])
        summary = report.summary()
        self.assertIn("dictations (2/2)", summary)
        self.assertIn("GATE NOT PASSED", summary)


class _FakeBackend:
    """A minimal in-memory stand-in for the sidecar HTTP surface."""

    def __init__(self, healthy=True):
        self.healthy = healthy
        self._next_id = 1
        self._latest = None

    def call(self, method, path, timeout=15):
        if path == "/health":
            if not self.healthy:
                raise RuntimeError("GET /health -> 503")
            return {"status": "ok"}
        if path == "/drafts/test-mock":
            draft = {"id": self._next_id}
            self._next_id += 1
            self._latest = draft
            return draft
        if path == "/drafts/latest":
            return {"draft": self._latest}
        if path.startswith("/drafts/") and (path.endswith("/accept") or path.endswith("/decline")):
            return {"ok": True}
        if path == "/recordings":
            return {"recordings": []}
        if path == "/jobs":
            return {"jobs": []}
        raise RuntimeError(f"unexpected {method} {path}")


class BuildReportTests(unittest.TestCase):
    def test_healthy_backend_all_automated_pass(self):
        backend = _FakeBackend(healthy=True)
        report = rb.build_report(backend.call, dictations=5, health_checks=3, include_manual=False)
        self.assertTrue(report.passed)  # no manual checks included -> gate is all-automated
        self.assertEqual(report.failed, [])
        loop = next(r for r in report.results if r.name == "dictation_core_loop")
        self.assertEqual((loop.iterations_ok, loop.iterations_total), (5, 5))

    def test_manual_checks_leave_gate_incomplete(self):
        backend = _FakeBackend(healthy=True)
        report = rb.build_report(backend.call, dictations=2, health_checks=2, include_manual=True)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.incomplete), len(rb.MANUAL_CHECKS))

    def test_unhealthy_backend_fails_the_gate(self):
        backend = _FakeBackend(healthy=False)
        report = rb.build_report(backend.call, dictations=3, health_checks=3, include_manual=False)
        self.assertFalse(report.passed)
        # backend_reachable + health-stable both fail against an unhealthy backend.
        failed_names = {r.name for r in report.failed}
        self.assertIn("backend_reachable", failed_names)
        self.assertIn("backend_health_stable", failed_names)


if __name__ == "__main__":
    unittest.main()
