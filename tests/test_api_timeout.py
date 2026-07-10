"""HTTP read-timeout sizing for LLM calls (persona cleanup reliability).

A fixed 30s timeout silently failed on CPU: a longer dictation's cleanup ran
past it, the request timed out, and the engine returned the raw uncleaned text
as if it had worked. The timeout now scales to the token budget so legitimate
cleanups complete.
"""

import unittest

import llm_engine as le


class ComputeApiReadTimeoutTests(unittest.TestCase):
    def test_default_budget_exceeds_the_old_30s(self):
        # The whole point: 1100 tokens must allow well over 30s on CPU.
        self.assertGreater(le.compute_api_read_timeout(1100), 30)

    def test_scales_with_tokens(self):
        self.assertLess(
            le.compute_api_read_timeout(200),
            le.compute_api_read_timeout(1500),
        )

    def test_floor_for_small_budgets(self):
        # A tiny budget still gets a usable floor, not a few seconds.
        self.assertEqual(le.compute_api_read_timeout(1, floor=45), 45)

    def test_ceiling_for_huge_budgets(self):
        self.assertEqual(le.compute_api_read_timeout(100000, ceiling=180), 180)

    def test_bad_input_falls_back_to_default(self):
        for bad in (None, "nope", object()):
            self.assertEqual(
                le.compute_api_read_timeout(bad),
                le.compute_api_read_timeout(le.DEFAULT_MAX_OUTPUT_TOKENS),
            )

    def test_slower_assumed_speed_gives_longer_timeout(self):
        self.assertGreater(
            le.compute_api_read_timeout(1000, tokens_per_second=4, ceiling=999),
            le.compute_api_read_timeout(1000, tokens_per_second=16, ceiling=999),
        )


if __name__ == "__main__":
    unittest.main()
