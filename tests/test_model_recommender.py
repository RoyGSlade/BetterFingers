import unittest

import model_recommender as r
from model_manager import AVAILABLE_MODELS


class RecommenderTests(unittest.TestCase):
    def test_cpu_only_recommends_small_llm(self):
        rec = r.recommend_llm("cpu-only", 8000)
        self.assertIn(rec["recommended"], AVAILABLE_MODELS)
        chosen = next(m for m in rec["models"] if m["id"] == rec["recommended"])
        self.assertLessEqual(chosen["params_b"], 4)
        self.assertEqual(chosen["fit"], "comfortable")

    def test_dgpu_recommends_larger_than_cpu(self):
        cpu = r.recommend_llm("cpu-only", 64000)["recommended"]
        dgpu = r.recommend_llm("dgpu-12g+", 64000)["recommended"]
        cpu_params = next(m for m in r.recommend_llm("cpu-only", 64000)["models"] if m["id"] == cpu)["params_b"]
        dgpu_params = next(m for m in r.recommend_llm("dgpu-12g+", 64000)["models"] if m["id"] == dgpu)["params_b"]
        self.assertGreater(dgpu_params, cpu_params)

    def test_low_ram_never_recommends_insufficient_model(self):
        rec = r.recommend_llm("dgpu-12g+", 4000)
        chosen = next(m for m in rec["models"] if m["id"] == rec["recommended"])
        self.assertNotEqual(chosen["fit"], "insufficient")

    def test_recommended_is_marked_and_first(self):
        rec = r.recommend_llm("igpu", 16000)
        self.assertTrue(rec["models"][0]["recommended"])
        self.assertEqual(rec["models"][0]["id"], rec["recommended"])
        self.assertEqual(sum(1 for m in rec["models"] if m["recommended"]), 1)

    def test_every_model_has_a_note(self):
        rec = r.recommend_llm("cpu-only", 16000)
        self.assertTrue(all(m["note"] for m in rec["models"]))

    def test_whisper_recommendation_scales_with_tier(self):
        self.assertEqual(r.recommend_whisper("cpu-only")["recommended"], "base.en")
        self.assertEqual(r.recommend_whisper("dgpu-12g+")["recommended"], "medium.en")

    def test_recommend_shape(self):
        out = r.recommend("igpu", 16000)
        self.assertEqual(out["tier"], "igpu")
        self.assertIn("recommended", out["llm"])
        self.assertIn("recommended", out["whisper"])
        self.assertTrue(out["llm"]["models"])


if __name__ == "__main__":
    unittest.main()
