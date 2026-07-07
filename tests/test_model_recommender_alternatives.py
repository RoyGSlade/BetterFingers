import unittest

import model_recommender as r
from model_manager import AVAILABLE_MODELS
from transcriber import SUPPORTED_MODEL_SIZES


class AlternativesCatalogTests(unittest.TestCase):
    def test_all_alternatives_are_not_downloadable(self):
        for entry in r.ALTERNATIVE_LLMS + r.ALTERNATIVE_STT:
            self.assertFalse(entry["downloadable"], entry["id"])

    def test_alternatives_never_collide_with_downloadable_catalogs(self):
        llm_ids = {m["id"] for m in r.ALTERNATIVE_LLMS}
        stt_ids = {m["id"] for m in r.ALTERNATIVE_STT}
        self.assertEqual(llm_ids & set(AVAILABLE_MODELS.keys()), set())
        self.assertEqual(stt_ids & set(SUPPORTED_MODEL_SIZES), set())

    def test_every_alternative_has_name_and_note(self):
        for entry in r.ALTERNATIVE_LLMS + r.ALTERNATIVE_STT:
            self.assertTrue(entry["name"])
            self.assertTrue(entry["note"])

    def test_small_models_surface_on_cpu_only(self):
        alt = r.recommend_alternatives("cpu-only")
        llm_ids = {m["id"] for m in alt["llm"]}
        self.assertIn("functiongemma-270m", llm_ids)
        self.assertIn("qwen3.5-2b", llm_ids)
        # Moonshine is cpu-friendly and should show; GPU-only STT should not.
        stt_ids = {m["id"] for m in alt["stt"]}
        self.assertIn("moonshine", stt_ids)
        self.assertNotIn("distil-large-v3.5", stt_ids)
        self.assertNotIn("parakeet-onnx", stt_ids)

    def test_gpu_tier_unlocks_more_stt(self):
        stt_ids = {m["id"] for m in r.recommend_alternatives("dgpu-12g+")["stt"]}
        self.assertIn("moonshine", stt_ids)
        self.assertIn("distil-large-v3.5", stt_ids)
        self.assertIn("parakeet-onnx", stt_ids)

    def test_igpu_unlocks_parakeet_not_large(self):
        stt_ids = {m["id"] for m in r.recommend_alternatives("igpu")["stt"]}
        self.assertIn("parakeet-onnx", stt_ids)
        self.assertNotIn("distil-large-v3.5", stt_ids)

    def test_unknown_tier_shows_all(self):
        alt = r.recommend_alternatives("bogus-tier")
        self.assertEqual(len(alt["llm"]), len(r.ALTERNATIVE_LLMS))
        self.assertEqual(len(alt["stt"]), len(r.ALTERNATIVE_STT))

    def test_recommend_includes_alternatives_section(self):
        out = r.recommend("cpu-only", 8000)
        self.assertIn("alternatives", out)
        self.assertIn("llm", out["alternatives"])
        self.assertIn("stt", out["alternatives"])


class GemmaFourCatalogTests(unittest.TestCase):
    """U8 audit: Gemma 4 family is already in the downloadable catalog."""

    def test_gemma4_family_present(self):
        ids = set(AVAILABLE_MODELS.keys())
        for expected in ("gemma-4-e2b-q4", "gemma-4-e4b-q4", "gemma-4-12b-q4", "gemma-4-26b-a4b-q4"):
            self.assertIn(expected, ids)

    def test_gemma4_entries_have_real_urls(self):
        for mid, meta in AVAILABLE_MODELS.items():
            if meta.get("family") == "gemma-4":
                self.assertTrue(str(meta.get("url", "")).startswith("https://"), mid)


if __name__ == "__main__":
    unittest.main()
