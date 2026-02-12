import os
import tempfile
import unittest

import llm_engine


class LLMPersonaManagementTests(unittest.TestCase):
    def test_guided_prompt_builder_returns_non_empty_prompt(self):
        prompt = llm_engine.build_guided_persona_prompt(
            goal="Clean callouts",
            tone="Direct",
            constraints="No extra facts",
            output_style="Short plain text",
        )
        self.assertIn("Clean callouts", prompt)
        self.assertIn("Direct", prompt)

    def test_upsert_and_delete_persona_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                ok, _msg = llm_engine.upsert_persona("Custom Persona", "Rewrite only.")
                self.assertTrue(ok)
                personas = llm_engine.load_personas(force_reload=True)
                self.assertIn("Custom Persona", personas)

                ok, _msg = llm_engine.delete_persona("Custom Persona")
                self.assertTrue(ok)
                personas = llm_engine.load_personas(force_reload=True)
                self.assertNotIn("Custom Persona", personas)
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata

    def test_delete_builtin_allowed_except_true_janitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                personas = llm_engine.load_personas(force_reload=True)
                self.assertIn("True Janitor", personas)
                self.assertIn("Formal", personas)

                ok, _msg = llm_engine.delete_persona("Formal", allow_builtin=True)
                self.assertTrue(ok)
                personas = llm_engine.load_personas(force_reload=True)
                self.assertNotIn("Formal", personas)

                ok, _msg = llm_engine.delete_persona("True Janitor", allow_builtin=True)
                self.assertFalse(ok)
                personas = llm_engine.load_personas(force_reload=True)
                self.assertIn("True Janitor", personas)
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
