from backend.services.persona_schema import (
    ENGINE_LOCKED_PRESERVE,
    compile_persona_instruction,
    default_structured_persona,
    migrate_legacy_persona,
    normalize_structured_persona,
)


def test_legacy_migration_preserves_original_and_marks_inference_for_review():
    prompt = "Use an occasional nautical term, but keep technical commands exact."
    structured, migration = migrate_legacy_persona("Readable Pirate", {"prompt": prompt})
    assert migration["original_prompt"] == prompt
    assert migration["source_format"] == "legacy_prompt"
    assert migration["confirmed"] is False
    assert migration["fields_requiring_review"]
    assert structured["characterization"]["speaking_habits"] == [prompt]


def test_critical_meaning_locks_cannot_be_disabled_by_stored_data():
    persona = default_structured_persona("Safe")
    persona["meaning_lock"]["preserve"] = {key: False for key in ENGINE_LOCKED_PRESERVE}
    persona["output_contract"]["output_only_rewritten_text"] = False
    normalized = normalize_structured_persona(persona)
    assert all(normalized["meaning_lock"]["preserve"].values())
    assert normalized["output_contract"]["output_only_rewritten_text"] is True


def test_compiler_is_deterministic_prioritized_and_keeps_transcript_separate():
    persona = default_structured_persona("Readable Pirate", "Light nautical flavor")
    persona["characterization"]["core_impression"] = ["Direct", "Experienced"]
    persona["characterization"]["speaking_habits"] = ["Occasional nautical metaphor"]
    persona["characterization"]["forbidden_devices"] = ["No caricature"]
    preset = {"metadata": {"display_name": "Workplace Email"}, "structure": {"target_length": "concise"}}
    first = compile_persona_instruction(persona, writing_preset=preset, runtime_context={"recipient": "coworker"})
    second = compile_persona_instruction(persona, writing_preset=preset, runtime_context={"recipient": "coworker"})
    assert first == second
    assert first.index("PRIORITIES") < first.index("ACTIVE PERSONA") < first.index("ACTIVE WRITING PRESET")
    assert "negation, uncertainty, conditions, questions, and commitments" in first
    assert "Return only the rewritten message" in first
    assert "[TRANSCRIPT]" not in first


def test_compiler_places_explicit_edits_above_style_and_never_impersonates():
    persona = default_structured_persona("Whimsical Fantasy Narrator")
    compiled = compile_persona_instruction(persona, factual_instructions="Correct the room number to 8:30 exactly.")
    assert compiled.index("EXPLICIT USER EDIT") < compiled.index("OUTPUT")
    assert "Do not invent" in compiled
    assert "impersonate a real or fictional person" in compiled
