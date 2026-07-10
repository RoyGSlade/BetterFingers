import unittest
from unittest.mock import patch

import llm_engine
from llm_engine import LLMEngine


def _answer_text(session, qid, text):
    """Assert the session is currently waiting on ``qid`` and submit ``text``."""
    q = llm_engine.foundry_next_prompt(session)
    assert q["id"] == qid, f"expected {qid}, got {q['id']}"
    return llm_engine.foundry_submit_answer(session, text)


def _engine():
    engine = LLMEngine.__new__(LLMEngine)
    engine.api_url = "http://127.0.0.1:8080"
    return engine


def _completed_session():
    session = llm_engine.foundry_new_session()
    _answer_text(session, "role", "An executive editor for terse business emails.")
    _answer_text(session, "character_cares", "Clarity and getting to the point fast.")
    _answer_text(session, "character_hates", "Hedging, filler words, and apologies.")
    _answer_text(session, "character_language", "Short declarative sentences, active voice.")
    _answer_text(session, "character_temperament", "Sharp and a little severe, never warm.")
    _answer_text(session, "character_never", "Never add a smiley or soften a hard truth.")
    llm_engine.foundry_submit_answer(session, "rewrite_only")
    llm_engine.foundry_submit_answer(session, "flexible_length")
    llm_engine.foundry_submit_answer(session, "stay_literal")
    _answer_text(session, "contract_tone_shift", "Just cleaner, no personality injection.")
    llm_engine.foundry_submit_answer(session, "clean_profanity")
    llm_engine.foundry_submit_answer(session, "sanitize")
    for raw, desired in [("yeah so maybe we push launch", "We are moving the launch."),
                          ("idk seems fine i guess", "Approved."),
                          ("can u check this", "Please review this.")]:
        llm_engine.foundry_submit_answer(session, {"raw": raw, "desired": desired})
    llm_engine.foundry_submit_answer(session, {"next": True})
    llm_engine.foundry_submit_answer(session, "Would never say 'per my last email'.")
    llm_engine.foundry_submit_answer(session, {"next": True})
    assert session["done"]
    return session


class FoundryQuestionListTests(unittest.TestCase):
    def test_question_ids_are_unique_and_ordered_by_group(self):
        ids = [q["id"] for q in llm_engine.FOUNDRY_QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        groups = [q["group"] for q in llm_engine.FOUNDRY_QUESTIONS]
        self.assertEqual(groups, sorted(groups, key=groups.index))  # grouped, not interleaved

    def test_choice_questions_carry_choices(self):
        for q in llm_engine.FOUNDRY_QUESTIONS:
            if q["kind"] == "choice":
                self.assertTrue(q.get("choices"))


class FoundryHappyPathTests(unittest.TestCase):
    def _walk_fixed_questions(self, session, contract_expand="stay_literal", contract_length="preserve_length"):
        _answer_text(session, "role", "An executive editor for terse business emails.")
        _answer_text(session, "character_cares", "Clarity and getting to the point fast.")
        _answer_text(session, "character_hates", "Hedging, filler words, and apologies.")
        _answer_text(session, "character_language", "Short declarative sentences, active voice.")
        _answer_text(session, "character_temperament", "Sharp and a little severe, never warm.")
        _answer_text(session, "character_never", "Never add a smiley or soften a hard truth.")
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["id"], "contract_scope")
        llm_engine.foundry_submit_answer(session, "rewrite_only")
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["id"], "contract_length")
        llm_engine.foundry_submit_answer(session, contract_length)
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["id"], "contract_expand")
        llm_engine.foundry_submit_answer(session, contract_expand)
        _answer_text(session, "contract_tone_shift", "Just cleaner, no personality injection.")
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["id"], "contract_profanity")
        llm_engine.foundry_submit_answer(session, "clean_profanity")
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["id"], "contract_safety")
        return llm_engine.foundry_submit_answer(session, "sanitize")

    def test_full_walkthrough_reaches_examples_then_done(self):
        session = llm_engine.foundry_new_session()
        result = self._walk_fixed_questions(session)
        self.assertIsNone(result["pushback"])
        self.assertFalse(result["done"])

        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["kind"], "collection")
        self.assertEqual(q["group"], "examples")

        for raw, desired in [("a", "b"), ("c", "d"), ("e", "f")]:
            r = llm_engine.foundry_submit_answer(session, {"raw": raw, "desired": desired})
            self.assertIsNone(r["pushback"])

        r = llm_engine.foundry_submit_answer(session, {"next": True})
        self.assertIsNone(r["pushback"])
        self.assertFalse(r["done"])
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["group"], "anti_examples")

        r = llm_engine.foundry_submit_answer(session, "Would never say 'per my last email'.")
        self.assertIsNone(r["pushback"])
        r = llm_engine.foundry_submit_answer(session, {"next": True})
        self.assertTrue(r["done"])
        self.assertTrue(session["done"])
        self.assertIsNone(llm_engine.foundry_next_prompt(session))

        self.assertEqual(session["answers"]["role"], "An executive editor for terse business emails.")
        self.assertEqual(len(session["examples"]), 3)
        self.assertEqual(len(session["anti_examples"]), 1)


class FoundryVaguenessTests(unittest.TestCase):
    def test_vague_answer_gets_pushback_once_then_accepted(self):
        session = llm_engine.foundry_new_session()
        r = llm_engine.foundry_submit_answer(session, "good")
        self.assertEqual(r["pushback"], llm_engine.FOUNDRY_PUSHBACK_VAGUE)
        self.assertFalse(r["done"])
        # Still on the same question.
        self.assertEqual(llm_engine.foundry_next_prompt(session)["id"], "role")
        # Second attempt, still vague — accepted anyway (at most one re-ask).
        r = llm_engine.foundry_submit_answer(session, "fine")
        self.assertIsNone(r["pushback"])
        self.assertEqual(llm_engine.foundry_next_prompt(session)["id"], "character_cares")
        self.assertEqual(session["answers"]["role"], "fine")

    def test_specific_answer_is_accepted_immediately(self):
        session = llm_engine.foundry_new_session()
        r = llm_engine.foundry_submit_answer(session, "A lorekeeper for my D&D campaign notes.")
        self.assertIsNone(r["pushback"])
        self.assertEqual(llm_engine.foundry_next_prompt(session)["id"], "character_cares")

    def test_empty_answer_is_vague(self):
        session = llm_engine.foundry_new_session()
        r = llm_engine.foundry_submit_answer(session, "")
        self.assertEqual(r["pushback"], llm_engine.FOUNDRY_PUSHBACK_VAGUE)


class FoundryChoiceValidationTests(unittest.TestCase):
    def _reach_contract_scope(self, session):
        for qid in ("role", "character_cares", "character_hates", "character_language",
                    "character_temperament", "character_never"):
            _answer_text(session, qid, "A specific enough three-word answer.")

    def test_invalid_choice_rejected_without_advancing(self):
        session = llm_engine.foundry_new_session()
        self._reach_contract_scope(session)
        r = llm_engine.foundry_submit_answer(session, "not_a_real_choice")
        self.assertIsNotNone(r["pushback"])
        self.assertEqual(llm_engine.foundry_next_prompt(session)["id"], "contract_scope")

    def test_valid_choice_advances(self):
        session = llm_engine.foundry_new_session()
        self._reach_contract_scope(session)
        r = llm_engine.foundry_submit_answer(session, "rewrite_only")
        self.assertIsNone(r["pushback"])
        self.assertEqual(llm_engine.foundry_next_prompt(session)["id"], "contract_length")


class FoundryContradictionTests(unittest.TestCase):
    def _reach_contract_length(self, session):
        for qid in ("role", "character_cares", "character_hates", "character_language",
                    "character_temperament", "character_never"):
            _answer_text(session, qid, "A specific enough three-word answer.")
        llm_engine.foundry_submit_answer(session, "rewrite_only")

    def test_expand_plus_preserve_length_triggers_pushback(self):
        session = llm_engine.foundry_new_session()
        self._reach_contract_length(session)
        llm_engine.foundry_submit_answer(session, "preserve_length")
        llm_engine.foundry_submit_answer(session, "expand_ideas")
        _answer_text(session, "contract_tone_shift", "Just cleaner, nothing fancy here.")
        llm_engine.foundry_submit_answer(session, "keep_profanity")
        r = llm_engine.foundry_submit_answer(session, "leave_as_is")
        self.assertEqual(r["pushback"], llm_engine.FOUNDRY_PUSHBACK_CONTRADICTION)
        self.assertFalse(r["done"])
        # Re-surfaced as the conflicting question, not the next one.
        self.assertEqual(llm_engine.foundry_next_prompt(session)["id"], "contract_length")

    def test_resolving_conflict_advances_to_examples_without_replaying_contract(self):
        session = llm_engine.foundry_new_session()
        self._reach_contract_length(session)
        llm_engine.foundry_submit_answer(session, "preserve_length")
        llm_engine.foundry_submit_answer(session, "expand_ideas")
        _answer_text(session, "contract_tone_shift", "Just cleaner, nothing fancy here.")
        llm_engine.foundry_submit_answer(session, "keep_profanity")
        llm_engine.foundry_submit_answer(session, "leave_as_is")  # triggers pushback
        r = llm_engine.foundry_submit_answer(session, "flexible_length")  # resolves it
        self.assertIsNone(r["pushback"])
        self.assertEqual(session["answers"]["contract_length"], "flexible_length")
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["kind"], "collection")
        self.assertEqual(q["group"], "examples")

    def test_conflict_pushback_only_fires_once(self):
        session = llm_engine.foundry_new_session()
        self._reach_contract_length(session)
        llm_engine.foundry_submit_answer(session, "preserve_length")
        llm_engine.foundry_submit_answer(session, "expand_ideas")
        _answer_text(session, "contract_tone_shift", "Just cleaner, nothing fancy here.")
        llm_engine.foundry_submit_answer(session, "keep_profanity")
        llm_engine.foundry_submit_answer(session, "leave_as_is")  # triggers pushback
        # Stubbornly re-picks the conflicting value — accepted anyway, no second pushback.
        r = llm_engine.foundry_submit_answer(session, "preserve_length")
        self.assertIsNone(r["pushback"])
        q = llm_engine.foundry_next_prompt(session)
        self.assertEqual(q["group"], "examples")


class FoundryCollectionTests(unittest.TestCase):
    def _reach_examples(self, session):
        for qid in ("role", "character_cares", "character_hates", "character_language",
                    "character_temperament", "character_never"):
            _answer_text(session, qid, "A specific enough three-word answer.")
        llm_engine.foundry_submit_answer(session, "rewrite_only")
        llm_engine.foundry_submit_answer(session, "flexible_length")
        llm_engine.foundry_submit_answer(session, "stay_literal")
        _answer_text(session, "contract_tone_shift", "Just cleaner, nothing fancy here.")
        llm_engine.foundry_submit_answer(session, "keep_profanity")
        llm_engine.foundry_submit_answer(session, "leave_as_is")

    def test_next_rejected_below_minimum_examples(self):
        session = llm_engine.foundry_new_session()
        self._reach_examples(session)
        llm_engine.foundry_submit_answer(session, {"raw": "a", "desired": "b"})
        r = llm_engine.foundry_submit_answer(session, {"next": True})
        self.assertIsNotNone(r["pushback"])
        self.assertEqual(llm_engine.foundry_next_prompt(session)["group"], "examples")

    def test_incomplete_example_pair_rejected(self):
        session = llm_engine.foundry_new_session()
        self._reach_examples(session)
        r = llm_engine.foundry_submit_answer(session, {"raw": "a", "desired": ""})
        self.assertIsNotNone(r["pushback"])
        self.assertEqual(len(session["examples"]), 0)

    def test_next_rejected_below_minimum_anti_examples(self):
        session = llm_engine.foundry_new_session()
        self._reach_examples(session)
        for raw, desired in [("a", "b"), ("c", "d"), ("e", "f")]:
            llm_engine.foundry_submit_answer(session, {"raw": raw, "desired": desired})
        llm_engine.foundry_submit_answer(session, {"next": True})
        r = llm_engine.foundry_submit_answer(session, {"next": True})
        self.assertIsNotNone(r["pushback"])
        self.assertFalse(r["done"])


class ContractToPolicyTests(unittest.TestCase):
    def test_expand_ideas_wins_output_policy(self):
        policy, _ = llm_engine._map_contract_to_policy({"contract_expand": "expand_ideas"})
        self.assertEqual(policy, "expand")

    def test_literal_and_preserve_length_is_preserve(self):
        policy, _ = llm_engine._map_contract_to_policy(
            {"contract_expand": "stay_literal", "contract_length": "preserve_length"})
        self.assertEqual(policy, "preserve")

    def test_literal_and_flexible_length_is_tighten(self):
        policy, _ = llm_engine._map_contract_to_policy(
            {"contract_expand": "stay_literal", "contract_length": "flexible_length"})
        self.assertEqual(policy, "tighten")

    def test_sanitize_forces_strict_safety(self):
        _, safety = llm_engine._map_contract_to_policy({"contract_safety": "sanitize"})
        self.assertEqual(safety, "strict")

    def test_can_answer_and_leave_as_is_is_creative(self):
        _, safety = llm_engine._map_contract_to_policy(
            {"contract_safety": "leave_as_is", "contract_scope": "can_answer"})
        self.assertEqual(safety, "creative")

    def test_rewrite_only_and_leave_as_is_is_light(self):
        _, safety = llm_engine._map_contract_to_policy(
            {"contract_safety": "leave_as_is", "contract_scope": "rewrite_only"})
        self.assertEqual(safety, "light")


class InferTemperatureTests(unittest.TestCase):
    def test_severe_and_precise_is_low(self):
        self.assertEqual(llm_engine._infer_temperature("severe and precise, very dry"), 0.3)

    def test_chaotic_and_funny_is_high(self):
        self.assertEqual(llm_engine._infer_temperature("chaotic and funny and a bit weird"), 0.9)

    def test_mixed_signals_is_middle(self):
        self.assertEqual(llm_engine._infer_temperature("severe but also a little wild"), 0.6)

    def test_no_signal_is_default(self):
        self.assertEqual(llm_engine._infer_temperature("just talks normally"), 0.5)

    def test_result_always_in_valid_range(self):
        for text in ("", "severe", "chaotic", "severe chaotic", "xyz"):
            temp = llm_engine._infer_temperature(text)
            self.assertGreaterEqual(temp, 0.0)
            self.assertLessEqual(temp, 2.0)


class ExtractTemperamentTagsTests(unittest.TestCase):
    def test_known_vocab_words_extracted(self):
        tags = llm_engine._extract_temperament_tags("Sharp and a little severe, never warm.")
        self.assertIn("sharp", tags)
        self.assertIn("severe", tags)
        # Naive keyword match, no negation handling — "never warm" still hits "warm".
        self.assertIn("warm", tags)

    def test_falls_back_to_significant_words(self):
        tags = llm_engine._extract_temperament_tags("kind of chill honestly")
        self.assertTrue(tags)
        self.assertNotIn("of", tags)
        self.assertIn("chill", tags)


class ParseFoundryCardResponseTests(unittest.TestCase):
    def test_well_formed_response_parses_all_fields(self):
        session = {"answers": {"role": "executive editor"}}
        text = (
            "NAME: Vivian Glass\n"
            "ARCHETYPE: executive editor\n"
            "SIGNATURE_MOVES: cut hedging, tighten verbs\n"
            "FAVORITE_PHRASES: Get to the point.\n"
            "BEST_USE_CASES: email, proposals\n"
        )
        card = llm_engine._parse_foundry_card_response(text, session)
        self.assertEqual(card["display_name"], "Vivian Glass")
        self.assertEqual(card["archetype"], "executive editor")
        self.assertEqual(card["signature_moves"], ["cut hedging", "tighten verbs"])
        self.assertEqual(card["favorite_phrases"], ["Get to the point."])
        self.assertEqual(card["best_use_cases"], ["email", "proposals"])

    def test_empty_response_falls_back_to_role(self):
        session = {"answers": {"role": "lorekeeper"}}
        card = llm_engine._parse_foundry_card_response("", session)
        self.assertEqual(card["display_name"], "Lorekeeper")
        self.assertEqual(card["archetype"], "lorekeeper")
        self.assertEqual(card["signature_moves"], [])

    def test_garbage_response_never_raises(self):
        session = {"answers": {}}
        card = llm_engine._parse_foundry_card_response("not even close to the format", session)
        self.assertIsInstance(card, dict)
        self.assertEqual(card["display_name"], "Custom Persona")


class ParseFoundryStressResponseTests(unittest.TestCase):
    def test_well_formed_response_overrides_seeds(self):
        text = "\n".join(f"{cat}: custom {cat} input" for cat in llm_engine.FOUNDRY_STRESS_CATEGORIES)
        cases = llm_engine._parse_foundry_stress_response(text)
        self.assertEqual(len(cases), 7)
        for case in cases:
            self.assertEqual(case["input"], f"custom {case['category']} input")

    def test_empty_response_falls_back_to_all_seeds(self):
        cases = llm_engine._parse_foundry_stress_response("")
        self.assertEqual(len(cases), 7)
        for case in cases:
            self.assertEqual(case["input"], llm_engine.FOUNDRY_STRESS_SEEDS[case["category"]])

    def test_partial_response_mixes_custom_and_seed(self):
        text = "rambling: custom rambling text\nangry: custom angry text"
        cases = {c["category"]: c["input"] for c in llm_engine._parse_foundry_stress_response(text)}
        self.assertEqual(cases["rambling"], "custom rambling text")
        self.assertEqual(cases["short_command"], llm_engine.FOUNDRY_STRESS_SEEDS["short_command"])


class CompileFoundryPersonaTests(unittest.TestCase):
    def test_compile_with_working_llm_uses_generated_text(self):
        session = _completed_session()
        engine = _engine()

        def fake_call_api(text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
            if system_prompt == llm_engine._FOUNDRY_PROMPT_META_SYSTEM:
                return "You are a sharp executive editor. Return only the rewritten text."
            return "NAME: Vivian Glass\nARCHETYPE: executive editor\nSIGNATURE_MOVES: cut hedging\nFAVORITE_PHRASES: Get to it.\nBEST_USE_CASES: email"

        with patch.object(engine, "ensure_ready", return_value=True), \
             patch.object(engine, "_call_api", side_effect=fake_call_api):
            result = engine.compile_foundry_persona(session)

        persona = result["persona"]
        self.assertEqual(persona["prompt"], "You are a sharp executive editor. Return only the rewritten text.")
        self.assertEqual(persona["persona_card"]["display_name"], "Vivian Glass")
        self.assertEqual(len(persona["few_shot"]), 3)
        self.assertEqual(persona["few_shot"][0]["out"], "We are moving the launch.")
        self.assertEqual(persona["persona_card"]["anti_examples"], ["Would never say 'per my last email'."])
        ok, msg = llm_engine.validate_persona(persona)
        self.assertTrue(ok, msg)

    def test_compile_falls_back_when_llm_not_ready(self):
        session = _completed_session()
        engine = _engine()

        with patch.object(engine, "ensure_ready", return_value=False):
            result = engine.compile_foundry_persona(session)

        persona = result["persona"]
        self.assertIn("executive editor", persona["prompt"])
        self.assertIn("Return only the rewritten text.", persona["prompt"])
        ok, _ = llm_engine.validate_persona(persona)
        self.assertTrue(ok)

    def test_compile_falls_back_when_call_api_raises(self):
        session = _completed_session()
        engine = _engine()

        with patch.object(engine, "ensure_ready", return_value=True), \
             patch.object(engine, "_call_api", side_effect=RuntimeError("boom")):
            result = engine.compile_foundry_persona(session)

        persona = result["persona"]
        ok, _ = llm_engine.validate_persona(persona)
        self.assertTrue(ok)
        self.assertTrue(persona["prompt"])

    def test_compile_maps_contract_and_reliability_score(self):
        session = _completed_session()
        engine = _engine()
        with patch.object(engine, "ensure_ready", return_value=False):
            result = engine.compile_foundry_persona(session)
        persona = result["persona"]
        # session used stay_literal + flexible_length -> tighten; sanitize -> strict.
        self.assertEqual(persona["output_policy"], "tighten")
        self.assertEqual(persona["safety_mode"], "strict")
        self.assertEqual(persona["persona_card"]["reliability_score"], 80)  # 40 + 30 (3 examples) + 10 (no conflict)

    def test_compile_output_lints_clean(self):
        session = _completed_session()
        engine = _engine()
        with patch.object(engine, "ensure_ready", return_value=False):
            result = engine.compile_foundry_persona(session)
        self.assertEqual(result["warnings"], [])


class FoundryStressSuiteTests(unittest.TestCase):
    def test_generate_stress_cases_falls_back_without_llm(self):
        engine = _engine()
        persona = llm_engine.normalize_persona({"prompt": "You are terse."})
        with patch.object(engine, "ensure_ready", return_value=False):
            cases = engine.generate_foundry_stress_cases(persona)
        self.assertEqual(len(cases), 7)
        self.assertEqual({c["category"] for c in cases}, set(llm_engine.FOUNDRY_STRESS_CATEGORIES))

    def test_run_stress_suite_runs_each_case_through_preview(self):
        engine = _engine()
        persona = llm_engine.normalize_persona({"prompt": "You are terse. Return only the rewritten text."})

        def fake_call_api(text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
            return f"OUT[{text[:10]}]"

        with patch.object(engine, "ensure_ready", return_value=True), \
             patch.object(engine, "_call_api", side_effect=fake_call_api):
            results = engine.run_foundry_stress_suite(persona)

        self.assertEqual(len(results), 7)
        for r in results:
            self.assertTrue(r["output"].startswith("OUT["))
            self.assertEqual(r["input"], llm_engine.FOUNDRY_STRESS_SEEDS[r["category"]])


if __name__ == "__main__":
    unittest.main()
