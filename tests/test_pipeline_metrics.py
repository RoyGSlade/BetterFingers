import unittest

import server


class PipelineMetricsTests(unittest.TestCase):
    def setUp(self):
        with server.pipeline_metrics_lock:
            server.pipeline_metrics.clear()

    def tearDown(self):
        with server.pipeline_metrics_lock:
            server.pipeline_metrics.clear()

    def test_record_includes_post_ms(self):
        entry = server.record_pipeline_metrics(stt_ms=10.0, post_ms=2.5, llm_ms=100.0, total_ms=115.0)
        self.assertEqual(entry["stt_ms"], 10.0)
        self.assertEqual(entry["post_ms"], 2.5)
        self.assertEqual(entry["llm_ms"], 100.0)
        self.assertEqual(entry["total_ms"], 115.0)

    def test_record_post_ms_defaults_to_none(self):
        entry = server.record_pipeline_metrics(stt_ms=10.0, llm_ms=100.0, total_ms=110.0)
        self.assertIsNone(entry["post_ms"])

    def test_summary_includes_post_stage_stats(self):
        server.record_pipeline_metrics(stt_ms=10.0, post_ms=2.0, llm_ms=50.0, total_ms=62.0)
        server.record_pipeline_metrics(stt_ms=12.0, post_ms=4.0, llm_ms=60.0, total_ms=76.0)

        summary = server.get_pipeline_metrics_summary()
        self.assertIn("post", summary)
        self.assertEqual(summary["post"]["count"], 2)
        self.assertEqual(summary["post"]["avg_ms"], 3.0)
        self.assertEqual(summary["post"]["last_ms"], 4.0)

    def test_summary_post_stats_empty_when_no_samples(self):
        summary = server.get_pipeline_metrics_summary()
        self.assertEqual(summary["post"], {"count": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "last_ms": None})


if __name__ == "__main__":
    unittest.main()
