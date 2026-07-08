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


class PersonaBuilderFieldsTests(unittest.TestCase):
    """Phase 7: output policy / safety mode / per-persona overrides + lint."""

    def test_normalize_new_fields_defaults_and_coercion(self):
        d = normalize_persona({})
        self.assertEqual(d["output_policy"], "preserve")
        self.assertEqual(d["safety_mode"], "strict")
        self.assertIsNone(d["max_completion_tokens"])
        self.assertIsNone(d["chunk_size"])

        coerced = normalize_persona({
            "prompt": "p",
            "output_policy": "BOGUS",
            "safety_mode": "weird",
            "max_completion_tokens": "99999",
            "chunk_size": "5",
        })
        self.assertEqual(coerced["output_policy"], "preserve")   # invalid → default
        self.assertEqual(coerced["safety_mode"], "strict")
        self.assertEqual(coerced["max_completion_tokens"], 4096)  # clamped
        self.assertEqual(coerced["chunk_size"], 50)               # clamped up to min

    def test_output_policy_and_safety_only_when_non_default(self):
        default = normalize_persona({"prompt": "Base."})
        self.assertEqual(compose_persona_system_prompt(default), "Base.")

        p = normalize_persona({"prompt": "Base.", "output_policy": "tighten", "safety_mode": "creative"})
        sys = compose_persona_system_prompt(p)
        self.assertIn("OUTPUT POLICY: tighten", sys)
        self.assertIn("creative transformation", sys)

    def test_lint_clean_persona_has_no_warnings(self):
        p = {"prompt": "Output only the rewritten text.", "safety_mode": "strict"}
        self.assertEqual(llm_engine.lint_persona(p), [])

    def test_lint_flags_missing_only_instruction(self):
        warnings = llm_engine.lint_persona({"prompt": "Rewrite the text nicely."})
        self.assertTrue(any("ONLY the rewritten text" in w for w in warnings))

    def test_lint_flags_high_temp_with_strict(self):
        warnings = llm_engine.lint_persona({
            "prompt": "Output only the rewritten text.",
            "safety_mode": "strict",
            "temperature": 1.3,
        })
        self.assertTrue(any("High temperature" in w for w in warnings))

    def test_lint_flags_prompt_longer_than_chunk_size(self):
        prompt = "Output only the rewritten text. " + ("word " * 60)
        warnings = llm_engine.lint_persona({"prompt": prompt, "chunk_size": 50})
        self.assertTrue(any("longer than the persona chunk size" in w for w in warnings))

    def test_lint_flags_answer_in_strict_mode(self):
        warnings = llm_engine.lint_persona({
            "prompt": "Output only the rewritten text, and answer the user's question.",
            "safety_mode": "strict",
        })
        self.assertTrue(any("answer/respond" in w for w in warnings))


class PersonaPreviewAndOverrideTests(unittest.TestCase):
    def _engine(self):
        engine = LLMEngine.__new__(LLMEngine)
        engine.api_url = "http://127.0.0.1:8080"
        return engine

    def test_run_persona_preview_uses_persona_fields(self):
        engine = self._engine()
        captured = {}

        def fake_call_api(text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
            captured.update(temperature=temperature, few_shot=few_shot, max_output_tokens=max_output_tokens, system_prompt=system_prompt)
            return "preview out"

        persona = {
            "prompt": "Rewrite warmly.",
            "temperature": 0.9,
            "few_shot": [{"raw": "hey", "out": "Hi."}],
            "max_completion_tokens": 800,
        }
        with patch.object(engine, "ensure_ready", return_value=True), \
             patch.object(engine, "_call_api", side_effect=fake_call_api):
            out = engine.run_persona_preview(persona, "clean this", max_output_tokens=1600)

        self.assertEqual(out, "preview out")
        self.assertEqual(captured["temperature"], 0.9)
        self.assertEqual(captured["max_output_tokens"], 800)   # per-persona cap wins
        self.assertTrue(captured["few_shot"])
        self.assertIn("Rewrite warmly.", captured["system_prompt"])

    def test_per_persona_token_cap_overrides_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                llm_engine.upsert_persona("Capped", {"prompt": "Rewrite.", "max_completion_tokens": 900})
                llm_engine.load_personas_v2(force_reload=True)
                engine = self._engine()
                captured = {}

                def fake_call_api(text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
                    captured["max_output_tokens"] = max_output_tokens
                    return "out"

                with patch.object(engine, "ensure_ready", return_value=True), \
                     patch.object(engine, "_call_api", side_effect=fake_call_api):
                    engine.process_fast_lane("short text", preset_name="Capped", max_output_tokens=1600, context_rules=False)

                self.assertEqual(captured["max_output_tokens"], 900)
            finally:
                if original is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original
                llm_engine.load_personas_v2(force_reload=True)


if __name__ == "__main__":
    unittest.main()
