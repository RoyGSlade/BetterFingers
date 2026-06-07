import unittest

import studio_generation as sg


class StudioGenerationTests(unittest.TestCase):
    def test_tier_for_model_maps_param_scale(self):
        self.assertEqual(sg.tier_for_model("gemma-4-e2b-q4"), sg.TIER_SMALL)
        self.assertEqual(sg.tier_for_model("gemma-4-e4b-q4"), sg.TIER_SMALL)
        self.assertEqual(sg.tier_for_model("gemma-3-4b-q4"), sg.TIER_SMALL)
        self.assertEqual(sg.tier_for_model("gemma-3-12b-q8"), sg.TIER_MEDIUM)
        self.assertEqual(sg.tier_for_model("gemma-4-31b-q4"), sg.TIER_LARGE)
        # Unknown / empty defaults to the safe small tier.
        self.assertEqual(sg.tier_for_model(None), sg.TIER_SMALL)
        self.assertEqual(sg.tier_for_model("mystery"), sg.TIER_SMALL)

    def test_profile_and_token_budget(self):
        small = sg.get_generation_profile("gemma-4-e4b-q4")
        large = sg.get_generation_profile("gemma-4-31b-q4")
        self.assertEqual(small["characters_per_call"], 1)
        self.assertGreater(large["characters_per_call"], small["characters_per_call"])
        self.assertGreater(
            sg.max_tokens_for(large, "large"), sg.max_tokens_for(small, "large")
        )

    def test_chunk_and_run_batched_stitch(self):
        self.assertEqual(sg.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        out = sg.run_batched([1, 2, 3, 4, 5], lambda b: [x * 10 for x in b], 2)
        self.assertEqual(out, [10, 20, 30, 40, 50])

    def test_run_batched_skips_failing_chunk(self):
        def fn(batch):
            if 3 in batch:
                raise ValueError("boom")
            return batch
        out = sg.run_batched([1, 2, 3, 4], fn, 1)
        self.assertEqual(out, [1, 2, 4])

    def test_key_validation(self):
        self.assertEqual(sg.missing_keys({"a": 1, "b": ""}, ["a", "b", "c"]), ["b", "c"])
        self.assertTrue(sg.ensure_keys({"a": 1, "b": 2}, ["a", "b"]))
        self.assertFalse(sg.ensure_keys("not a dict", ["a"]))

    def test_sentence_safe_trim_never_cuts_mid_word(self):
        text = ("A basement jazz club with no windows, no rules, and no way to know "
                "what time it was unless you counted the number of drinks.")
        trimmed = sg.sentence_safe_trim(text, 60)
        self.assertLessEqual(len(trimmed), 61)
        # The old bug produced '...number of dri'; ensure we never end mid-word.
        self.assertFalse(trimmed.rstrip("…").endswith("dri"))
        self.assertTrue(text.startswith(trimmed.rstrip("…").rstrip()))

    def test_sentence_safe_trim_short_text_unchanged(self):
        self.assertEqual(sg.sentence_safe_trim("short", 60), "short")


if __name__ == "__main__":
    unittest.main()
