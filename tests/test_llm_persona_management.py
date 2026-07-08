import os
import tempfile
import unittest
from unittest.mock import patch

import llm_engine
from llm_engine import (
    LLMEngine,
    compose_persona_messages,
    compose_persona_system_prompt,
    default_persona,
    get_persona_runtime,
    normalize_persona,
)


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


class PersonaCompositionTests(unittest.TestCase):
    """Phase 6: composing schema-v2 persona fields into prompts/messages."""

    def test_prompt_only_persona_composes_to_bare_prompt(self):
        # A prompt-only persona (default format/scope) is unchanged.
        p = default_persona("Just clean it up.")
        self.assertEqual(compose_persona_system_prompt(p), "Just clean it up.")

    def test_format_rules_appended(self):
        p = normalize_persona({
            "prompt": "Base.",
            "format": {"caps": "upper", "punctuation": False, "signoff": "Cheers"},
        })
        sys = compose_persona_system_prompt(p)
        self.assertIn("Base.", sys)
        self.assertIn("ALL UPPERCASE", sys)
        self.assertIn("Do not add punctuation", sys)
        self.assertIn("Cheers", sys)

    def test_dictionary_scope_line_only_when_non_global(self):
        p_global = normalize_persona({"prompt": "X", "dictionary_scope": "global"})
        self.assertNotIn("DICTIONARY SCOPE", compose_persona_system_prompt(p_global))
        p_med = normalize_persona({"prompt": "X", "dictionary_scope": "medical"})
        self.assertIn("medical", compose_persona_system_prompt(p_med))

    def test_few_shot_become_separate_turns(self):
        p = normalize_persona({
            "prompt": "Base",
            "few_shot": [{"raw": "hi", "out": "Hello."}, {"raw": "bye", "out": "Goodbye."}],
        })
        msgs = compose_persona_messages(p, "final input")
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], "Base")
        self.assertEqual(msgs[1]["content"], "hi")
        self.assertEqual(msgs[2]["content"], "Hello.")
        self.assertEqual(msgs[-1]["content"], "final input")

    def test_few_shot_capped_at_five(self):
        examples = [{"raw": f"r{i}", "out": f"o{i}"} for i in range(9)]
        p = normalize_persona({"prompt": "Base", "few_shot": examples})
        msgs = compose_persona_messages(p, "z")
        # system + 5*2 few-shot turns + final user
        self.assertEqual(len(msgs), 1 + 5 * 2 + 1)

    def test_invalid_rich_fields_normalize_safely(self):
        # Garbage in the rich fields must not raise; normalize coerces defensively.
        p = normalize_persona({"prompt": "P", "temperature": "hot", "few_shot": "nope", "format": 5})
        sys = compose_persona_system_prompt(p)
        self.assertEqual(sys, "P")
        self.assertEqual(compose_persona_messages(p, "u")[-1]["content"], "u")

    def test_get_persona_runtime_unknown_falls_back(self):
        rt = get_persona_runtime("does-not-exist-xyz-123")
        self.assertTrue(str(rt["prompt"]).strip())


class PersonaInferenceWiringTests(unittest.TestCase):
    """Phase 6: persona v2 fields actually reach the API call."""

    def _engine(self):
        engine = LLMEngine.__new__(LLMEngine)
        engine.api_url = "http://127.0.0.1:8080"
        return engine

    def _appdata(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name

        def restore():
            if original is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = original
            # Reset the module persona cache so later tests see real personas.
            llm_engine.load_personas_v2(force_reload=True)

        self.addCleanup(restore)
        return tmp.name

    def test_persona_temperature_and_few_shot_reach_call_api(self):
        self._appdata()
        llm_engine.upsert_persona("Warm", {
            "prompt": "Rewrite warmly.",
            "temperature": 0.8,
            "few_shot": [{"raw": "hey", "out": "Hello there."}],
        })
        llm_engine.load_personas_v2(force_reload=True)

        engine = self._engine()
        captured = {}

        def fake_call_api(text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
            captured["temperature"] = temperature
            captured["few_shot"] = few_shot
            captured["system_prompt"] = system_prompt
            return "out"

        with patch.object(engine, "ensure_ready", return_value=True), \
             patch.object(engine, "_call_api", side_effect=fake_call_api):
            engine.process_fast_lane("some short text", preset_name="Warm", context_rules=False)

        self.assertEqual(captured["temperature"], 0.8)
        self.assertTrue(captured["few_shot"])
        self.assertEqual(captured["few_shot"][0]["out"], "Hello there.")
        self.assertIn("Rewrite warmly.", captured["system_prompt"])

    def test_prompt_only_persona_keeps_default_temperature(self):
        self._appdata()
        llm_engine.upsert_persona("Plain", "Just rewrite.")
        llm_engine.load_personas_v2(force_reload=True)

        engine = self._engine()
        captured = {}

        def fake_call_api(text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
            captured["temperature"] = temperature
            captured["few_shot"] = few_shot
            return "out"

        with patch.object(engine, "ensure_ready", return_value=True), \
             patch.object(engine, "_call_api", side_effect=fake_call_api):
            engine.process_fast_lane("short", preset_name="Plain", context_rules=False)

        # Non-janitor default temperature, and no few-shot for a prompt-only persona.
        self.assertEqual(captured["temperature"], 0.3)
        self.assertIsNone(captured["few_shot"])


if __name__ == "__main__":
    unittest.main()
