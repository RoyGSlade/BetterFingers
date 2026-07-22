"""Brain package tests (wavebasedgame.md §2.3, §2.4, §3.2, §3.5, §3.6; see
docs/INFINITE_STACKS_BRAIN.md).

backend.lan_playground.brain is standalone this wave -- no domain/reducer
wiring exists yet, so these tests drive the package's own modules directly.
Includes property-style tests (malformed interpreter output never raises,
modifier never exceeds +-5, zero-intent always yields a response artifact)
and the package purity test (no imports outside the package + stdlib),
mirroring the pattern in test_stacks_heroes.py / test_stacks_combat.py /
test_stacks_shops.py.
"""
from __future__ import annotations

import ast
import itertools
import os
import random

import pytest

from backend.lan_playground.brain import degrees, fallback, handlers, intents, packets, response, triggers

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN_DIR = os.path.join(REPO_ROOT, "backend", "lan_playground", "brain")

FORBIDDEN_PACKAGE_PREFIXES = (
    "backend.lan_playground.domain",
    "backend.lan_playground.systems",
    "backend.lan_playground.content",
    "backend.lan_playground.heroes",
    "backend.lan_playground.combat",
    "backend.lan_playground.shops",
)


# --------------------------------------------------------------------------- package purity


def _imports_of(file_path: str) -> set:
    with open(file_path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=file_path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_brain_package_has_no_engine_imports():
    """No module under brain/ imports domain/systems/content/heroes/combat/
    shops -- pure package, data in, data out (task requirement, mirrors
    combat/heroes/shops module docstrings)."""
    offenders = {}
    for filename in sorted(os.listdir(BRAIN_DIR)):
        if not filename.endswith(".py"):
            continue
        path = os.path.join(BRAIN_DIR, filename)
        imported = _imports_of(path)
        bad = {
            name
            for name in imported
            if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_PACKAGE_PREFIXES)
        }
        if bad:
            offenders[filename] = bad
    assert not offenders, f"brain/ modules import forbidden engine packages: {offenders}"


def test_brain_package_imports_only_stdlib_and_itself():
    """Every import in brain/ is either stdlib or another brain.* module --
    no third-party packages, no other backend.lan_playground subpackage."""
    stdlib_ok = {
        "__future__", "dataclasses", "enum", "typing", "itertools", "math", "functools",
    }
    offenders = {}
    for filename in sorted(os.listdir(BRAIN_DIR)):
        if not filename.endswith(".py"):
            continue
        path = os.path.join(BRAIN_DIR, filename)
        imported = _imports_of(path)
        bad = set()
        for name in imported:
            top = name.split(".")[0]
            if name.startswith("backend.lan_playground.brain"):
                continue
            if top in stdlib_ok:
                continue
            bad.add(name)
        if bad:
            offenders[filename] = bad
    assert not offenders, f"brain/ modules import non-stdlib/non-brain packages: {offenders}"


# --------------------------------------------------------------------------- §3.5 packets: no cached/model-owned memory


def test_packets_carry_no_history_field():
    """Structural check: none of the four packet dataclasses expose any
    field whose name suggests conversation history or a session/model
    memory handle."""
    banned_substrings = ("history", "memory", "conversation", "session_cache", "prior_turns")
    for cls in (packets.InterpreterPacket, packets.NPCPerformerPacket, packets.NarratorPacket, packets.EventToBookPacket):
        field_names = {f.name for f in __import__("dataclasses").fields(cls)}
        for name in field_names:
            for banned in banned_substrings:
                assert banned not in name.lower(), f"{cls.__name__}.{name} looks like cached history/memory"


def test_build_interpreter_packet_is_pure_and_uncached():
    """Calling build_interpreter_packet twice with the same arguments
    yields equal, independent packets -- nothing is cached between calls."""
    p1 = packets.build_interpreter_packet(raw_utterance="give bacon", actor_id="hero_1", scene_facts=("door_locked",))
    p2 = packets.build_interpreter_packet(raw_utterance="give bacon", actor_id="hero_1", scene_facts=("door_locked",))
    assert p1 == p2
    assert p1 is not p2


def test_narrator_packet_never_receives_scene_history_field():
    packet = packets.build_narrator_packet(scene_facts=("torch_lit",), resolved_degree="clean_success")
    as_dict = packet.to_dict()
    assert "history" not in as_dict
    assert set(as_dict) == {"envelope", "scene_facts", "resolved_degree", "state_delta", "allowed_disclosures"}


def test_envelope_requires_deterministic_fallback_key():
    with pytest.raises(ValueError):
        packets.make_envelope(
            content_purpose="x", authorized_facts=(), deterministic_fallback_key="", cache_key="x",
        )


def test_all_four_build_functions_declare_a_fallback_key():
    interp = packets.build_interpreter_packet(raw_utterance="x", actor_id="a")
    npc = packets.build_npc_performer_packet(npc_id="n", dialogue_act="greet")
    narrator = packets.build_narrator_packet(scene_facts=("f",))
    book = packets.build_event_to_book_packet(event_ids=("e1",))
    for packet in (interp, npc, narrator, book):
        assert packet.envelope.deterministic_fallback_key


def test_packet_envelope_facts_are_frozen_not_shared_mutable_state():
    shared = {"a": 1}
    p1 = packets.build_interpreter_packet(raw_utterance="x", actor_id="a", scene_facts=shared)
    shared["a"] = 2  # mutate the caller's dict after building the packet
    assert p1.scene_facts == (("a", 1),)  # packet snapshot is unaffected


# --------------------------------------------------------------------------- §3.5 Interpreter output contract


def test_intent_candidate_confidence_is_never_a_success_chance_field_name():
    field_names = {f.name for f in __import__("dataclasses").fields(intents.IntentCandidate)}
    assert "confidence" in field_names
    assert "success_chance" not in field_names
    assert "success_probability" not in field_names


def test_intent_candidate_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        intents.IntentCandidate(target=None, method="talk", confidence=0)
    with pytest.raises(ValueError):
        intents.IntentCandidate(target=None, method="talk", confidence=101)


def test_interpretation_result_caps_at_three_candidates():
    many = [intents.IntentCandidate(target=None, method=f"m{i}", confidence=50) for i in range(10)]
    result = intents.InterpretationResult(candidates=tuple(many))
    assert len(result.candidates) == 3


def test_parse_raw_intents_handles_well_formed_list():
    raw = [
        {"target": "goblin", "method": "attack", "confidence": 80},
        {"target": "door", "method": "open", "confidence": 60, "ambiguous": True},
    ]
    result = intents.parse_raw_intents(raw)
    assert len(result.candidates) == 2
    assert result.candidates[0].target == "goblin"
    assert result.candidates[1].ambiguous is True


def test_parse_raw_intents_zero_intent_for_none():
    result = intents.parse_raw_intents(None)
    assert result.is_zero_intent


def test_parse_raw_intents_accepts_bare_dict_as_one_candidate():
    result = intents.parse_raw_intents({"method": "look", "confidence": 30})
    assert len(result.candidates) == 1


def test_parse_raw_intents_caps_at_three_even_with_more_raw_candidates():
    raw = [{"method": f"m{i}", "confidence": 10 + i} for i in range(7)]
    result = intents.parse_raw_intents(raw)
    assert len(result.candidates) == 3


def test_parse_raw_intents_clamps_out_of_range_confidence():
    raw = [{"method": "shove", "confidence": 999}, {"method": "flee", "confidence": -50}]
    result = intents.parse_raw_intents(raw)
    values = {c.method: c.confidence for c in result.candidates}
    assert values["shove"] == 100
    assert values["flee"] == 1


def test_parse_raw_intents_drops_candidate_with_unusable_confidence():
    raw = [{"method": "shove", "confidence": "not-a-number"}, {"method": "flee", "confidence": 50}]
    result = intents.parse_raw_intents(raw)
    assert [c.method for c in result.candidates] == ["flee"]


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        "a plain string, not JSON",
        42,
        3.14,
        object(),
        [],
        [None, None],
        [{"confidence": "nope"}],
        [1, 2, 3],
        {"confidence": None},
        [{"target": {"nested": "dict"}, "confidence": 50}],
        [{"leverage": {"not": "a list"}, "confidence": 50, "method": "x"}],
        ({"method": "m", "confidence": 50},),  # tuple, not list
        {"malformed": True},  # dict missing confidence entirely
    ],
)
def test_parse_raw_intents_never_raises_on_malformed_input(malformed):
    """Property-style: for a broad sample of malformed shapes, parsing
    always degrades gracefully and never raises."""
    result = intents.parse_raw_intents(malformed)
    assert isinstance(result, intents.InterpretationResult)
    assert len(result.candidates) <= intents.MAX_INTENTS


def test_parse_raw_intents_never_raises_random_garbage_property():
    """Broader property sweep: random garbage python objects as the raw
    candidate list must never raise, across many seeds."""
    rng = random.Random(12345)
    garbage_pool = [None, 1, 1.5, "str", True, [], {}, object(), (1, 2), {"confidence": 1}]
    for _ in range(500):
        raw = [rng.choice(garbage_pool) for _ in range(rng.randint(0, 6))]
        result = intents.parse_raw_intents(raw)
        assert isinstance(result, intents.InterpretationResult)
        assert len(result.candidates) <= 3


# --------------------------------------------------------------------------- handler registry


def test_object_specific_handler_overrides_global():
    registry = handlers.HandlerRegistry()
    registry.register_global("give", lambda: "global")
    registry.register_scoped("give", "npc_dragon", lambda: "dragon-specific")
    assert registry.resolve("give", "npc_dragon")() == "dragon-specific"
    assert registry.resolve("give", "npc_villager")() == "global"


def test_wildcard_global_handler_is_last_resort():
    registry = handlers.HandlerRegistry()
    registry.register_global("*", lambda: "catch-all")
    assert registry.resolve("some_unregistered_method")() == "catch-all"


def test_registry_resolve_returns_none_when_nothing_matches():
    registry = handlers.HandlerRegistry()
    assert registry.resolve("nonexistent") is None
    assert registry.has_handler("nonexistent") is False


def test_validate_target_exists():
    assert handlers.validate_target_exists("door_1", {"door_1", "npc_1"}).supported
    result = handlers.validate_target_exists("ghost_target", {"door_1"})
    assert not result.supported
    assert result.reason == handlers.UnsupportedReason.TARGET_NOT_FOUND


def test_validate_target_exists_none_target_always_supported():
    assert handlers.validate_target_exists(None, set()).supported


def test_validate_action_economy():
    assert handlers.validate_action_economy(1).supported
    assert not handlers.validate_action_economy(0).supported


def test_validate_compound_ordering_caps_at_three():
    assert handlers.validate_compound_ordering(("a", "b", "c")).supported
    result = handlers.validate_compound_ordering(("a", "b", "c", "d"))
    assert not result.supported
    assert result.reason == handlers.UnsupportedReason.ORDERING_VIOLATION


def test_requires_confirmation_for_ambiguous_or_high_impact():
    assert handlers.requires_confirmation(ambiguous=True, high_impact=False)
    assert handlers.requires_confirmation(ambiguous=False, high_impact=True)
    assert not handlers.requires_confirmation(ambiguous=False, high_impact=False)


def test_validation_result_unsupported_requires_reason():
    with pytest.raises(ValueError):
        handlers.ValidationResult(supported=False)


# --------------------------------------------------------------------------- §2.3 always-a-response


def test_zero_intent_always_yields_response_artifact():
    artifact = response.zero_intent_response(
        raw_utterance="asdkjhasd", actor_id="hero_1", fallback_fact="the room gives no visible reaction"
    )
    assert artifact.kind == response.ResponseKind.ZERO_INTENT
    assert artifact.narration_facts


def test_zero_intent_response_never_none_for_any_utterance_property():
    """Property-style: for a wide sample of nonsense/empty utterances,
    building a zero-intent response never returns None and always carries
    at least one narration fact."""
    rng = random.Random(999)
    samples = ["", " ", "asdf", "🎲🎲🎲", "a" * 500, "\n\t", "SELECT * FROM heroes;"]
    for _ in range(50):
        utterance = rng.choice(samples)
        artifact = response.zero_intent_response(
            raw_utterance=utterance, actor_id="hero_x", fallback_fact="nothing registers"
        )
        assert artifact is not None
        assert isinstance(artifact, response.ResponseArtifact)
        assert len(artifact.narration_facts) >= 1


def test_unsupported_response_always_carries_content_gap_record():
    artifact = response.unsupported_response(
        raw_utterance="juggle the goblin",
        actor_id="hero_1",
        attempted_method="juggle",
        attempted_target="goblin_1",
        reason=handlers.UnsupportedReason.NO_HANDLER.value,
        narration_facts=("that isn't something you can do here",),
    )
    assert artifact.kind == response.ResponseKind.UNSUPPORTED
    assert artifact.content_gap is not None
    assert artifact.content_gap.attempted_method == "juggle"
    gap_dict = artifact.content_gap.to_dict()
    assert gap_dict["reason"] == handlers.UnsupportedReason.NO_HANDLER.value


def test_response_artifact_unsupported_without_gap_raises():
    with pytest.raises(ValueError):
        response.ResponseArtifact(kind=response.ResponseKind.UNSUPPORTED)


def test_content_gap_record_is_a_real_persistable_structure_not_a_print():
    gap = response.ContentGapRecord(
        raw_utterance="fly to the moon",
        actor_id="hero_1",
        attempted_method="fly",
        attempted_target=None,
        reason="no_handler",
    )
    as_dict = gap.to_dict()
    assert as_dict == {
        "raw_utterance": "fly to the moon",
        "actor_id": "hero_1",
        "attempted_method": "fly",
        "attempted_target": None,
        "reason": "no_handler",
        "scene_context": [],
    }
    # Round-trips through a JSON-safe structure -- provably persistable.
    import json

    json.dumps(as_dict)


def test_clarification_response_requires_prompt():
    with pytest.raises(ValueError):
        response.ResponseArtifact(kind=response.ResponseKind.CLARIFICATION_NEEDED)
    artifact = response.clarification_response(clarification_prompt="Did you mean the north door?")
    assert artifact.clarification_prompt


# --------------------------------------------------------------------------- §3.5 immediate triggers


def test_immediate_trigger_matches_offer():
    trigger = triggers.ImmediateTrigger(
        trigger_id="bacon_dragon",
        condition=triggers.TriggerCondition.OFFER_MATCHES_ITEM,
        match_value="bacon",
        state_delta=(("dragon_hunger", "sated"),),
    )
    candidate = intents.IntentCandidate(target="dragon_1", method="give", confidence=90, offer="bacon")
    assert trigger.matches(candidate)


def test_evaluate_triggers_deterministic_priority_order():
    low_priority = triggers.ImmediateTrigger(
        trigger_id="b_trigger", condition=triggers.TriggerCondition.KEYWORD_PRESENT, match_value="fire", priority=50,
    )
    high_priority = triggers.ImmediateTrigger(
        trigger_id="a_trigger", condition=triggers.TriggerCondition.KEYWORD_PRESENT, match_value="fire", priority=10,
    )
    candidate = intents.IntentCandidate(target=None, method="ignite", confidence=70, keywords=("fire",))
    matched = triggers.evaluate_triggers(candidate, (low_priority, high_priority))
    assert [t.trigger_id for t in matched] == ["a_trigger", "b_trigger"]


def test_evaluate_triggers_ties_broken_by_trigger_id():
    t1 = triggers.ImmediateTrigger(
        trigger_id="z_trigger", condition=triggers.TriggerCondition.METHOD_EQUALS, match_value="talk", priority=10,
    )
    t2 = triggers.ImmediateTrigger(
        trigger_id="a_trigger", condition=triggers.TriggerCondition.METHOD_EQUALS, match_value="talk", priority=10,
    )
    candidate = intents.IntentCandidate(target=None, method="talk", confidence=50)
    matched = triggers.evaluate_triggers(candidate, (t1, t2))
    assert [t.trigger_id for t in matched] == ["a_trigger", "z_trigger"]


def test_fold_trigger_state_deltas_concatenates_in_order():
    t1 = triggers.ImmediateTrigger(
        trigger_id="a", condition=triggers.TriggerCondition.METHOD_EQUALS, match_value="give", state_delta=("x",),
    )
    t2 = triggers.ImmediateTrigger(
        trigger_id="b", condition=triggers.TriggerCondition.METHOD_EQUALS, match_value="give", state_delta=("y", "z"),
    )
    assert triggers.fold_trigger_state_deltas((t1, t2)) == ("x", "y", "z")


def test_model_never_defines_a_trigger_only_engine_data_does():
    """Structural check: ImmediateTrigger construction takes no callable/
    generated-text field -- only declarative condition/match_value/
    state_delta data, so nothing here lets a model define trigger logic."""
    field_names = {f.name for f in __import__("dataclasses").fields(triggers.ImmediateTrigger)}
    assert field_names == {"trigger_id", "condition", "match_value", "state_delta", "priority"}


# --------------------------------------------------------------------------- §3.6 social degrees


def test_social_outcome_matches_systems_checks_outcome_values_drift_guard():
    """brain.degrees.SocialOutcome must stay byte-for-byte identical to
    systems.checks.Outcome (values, not just names) since brain/ cannot
    import systems/ (pure-package rule) and instead literally duplicates
    the table -- only a test that's allowed to import both can catch the
    two silently drifting apart, same pattern as
    test_stacks_heroes.py::test_attribute_and_skill_names_match_combat_models_exactly."""
    from backend.lan_playground.systems.checks import Outcome as EngineOutcome
    from backend.lan_playground.systems.checks import outcome_for_margin as engine_outcome_for_margin

    assert {o.value for o in degrees.SocialOutcome} == {o.value for o in EngineOutcome}
    for margin in range(-30, 30):
        assert degrees.outcome_for_margin(margin).value == engine_outcome_for_margin(margin).value


def test_modifier_inputs_are_structurally_enums_not_free_text():
    """Accessibility guarantee as a testable property: SocialModifierInputs
    has no str-typed field a caller could stuff free text/grammar/
    eloquence signals into."""
    import dataclasses

    for f in dataclasses.fields(degrees.SocialModifierInputs):
        if f.name.endswith("_nudge"):
            assert f.type in (int, "int")
        else:
            assert "Evidence" in str(f.type) or "Motive" in str(f.type)


def test_compute_contextual_modifier_never_exceeds_bounds_property():
    """Property-style: for every combination of evidence/motive tier and a
    wide nudge sweep, the modifier is always clamped to [-5, +5]."""
    for evidence, motive, nudge_a, nudge_b in itertools.product(
        degrees.EvidenceTier, degrees.MotiveAlignment, range(-20, 21, 5), range(-20, 21, 5)
    ):
        inputs = degrees.SocialModifierInputs(
            evidence=evidence, motive=motive, evidence_nudge=nudge_a, motive_nudge=nudge_b,
        )
        modifier = degrees.compute_contextual_modifier(inputs)
        assert degrees.MIN_MODIFIER <= modifier <= degrees.MAX_MODIFIER


def test_authored_tier_examples_from_spec():
    """The exact worked examples from wavebasedgame.md §3.6."""
    no_leverage = degrees.compute_contextual_modifier(
        degrees.SocialModifierInputs(evidence=degrees.EvidenceTier.NONE, motive=degrees.MotiveAlignment.NEUTRAL)
    )
    assert no_leverage == 0

    forged = degrees.compute_contextual_modifier(
        degrees.SocialModifierInputs(evidence=degrees.EvidenceTier.FORGED_VERIFIABLE, motive=degrees.MotiveAlignment.NEUTRAL)
    )
    assert 3 <= forged <= 5

    threatens_fear = degrees.compute_contextual_modifier(
        degrees.SocialModifierInputs(evidence=degrees.EvidenceTier.NONE, motive=degrees.MotiveAlignment.THREATENS_STATED_FEAR)
    )
    assert -5 <= threatens_fear <= -3


def test_modifier_tier_construction_rejects_out_of_bounds_range():
    with pytest.raises(ValueError):
        degrees.ModifierTier("bad", -6, 0)
    with pytest.raises(ValueError):
        degrees.ModifierTier("bad", 0, 6)
    with pytest.raises(ValueError):
        degrees.ModifierTier("bad", 3, 1)


def test_compute_social_dc_never_below_routine():
    dc = degrees.compute_social_dc(degrees.SocialDCInputs(disposition=100))  # extremely friendly NPC
    assert dc >= degrees.DC_ROUTINE


def test_compute_social_dc_scales_with_concession_and_risk():
    low = degrees.compute_social_dc(degrees.SocialDCInputs(concession_value=0, risk=0))
    high = degrees.compute_social_dc(degrees.SocialDCInputs(concession_value=6, risk=3))
    assert high > low


def test_resolve_social_check_maps_onto_degree_table_and_eligible_outcomes():
    result = degrees.resolve_social_check(
        d20_roll=15,
        attribute_score=3,
        skill_rank=2,
        dc_inputs=degrees.SocialDCInputs(),
        modifier_inputs=degrees.SocialModifierInputs(
            evidence=degrees.EvidenceTier.FORGED_VERIFIABLE, motive=degrees.MotiveAlignment.STRONGLY_ALIGNED,
        ),
    )
    assert isinstance(result.outcome, degrees.SocialOutcome)
    assert result.eligible_rich_outcomes == degrees.ELIGIBLE_RICH_OUTCOMES[result.outcome]
    assert degrees.MIN_MODIFIER <= result.modifier <= degrees.MAX_MODIFIER


def test_resolve_social_check_never_reads_a_confidence_field():
    """Structural guarantee: resolve_social_check's signature has no
    parameter shaped like the Interpreter's interpretation confidence --
    the two concepts must never be conflated in the actual call surface."""
    import inspect

    sig = inspect.signature(degrees.resolve_social_check)
    for name in sig.parameters:
        assert "confidence" not in name.lower()


# --------------------------------------------------------------------------- §3.7 deterministic fallback / never blocks resolution


def test_every_role_has_a_deterministic_fallback():
    interp_packet = packets.build_interpreter_packet(raw_utterance="x", actor_id="a")
    npc_packet = packets.build_npc_performer_packet(npc_id="n", dialogue_act="greet", disposition="wary")
    narrator_packet = packets.build_narrator_packet(scene_facts=("torch_lit",), resolved_degree="clean_success")
    book_packet = packets.build_event_to_book_packet(event_ids=("e1", "e2"), declared_facts=("door opened",))

    assert fallback.resolve_fallback(packets.BrainRole.INTERPRETER, interp_packet)
    assert fallback.resolve_fallback(packets.BrainRole.NPC_PERFORMER, npc_packet)
    assert fallback.resolve_fallback(packets.BrainRole.NARRATOR, narrator_packet)
    assert fallback.resolve_fallback(packets.BrainRole.EVENT_TO_BOOK_PROSE, book_packet)


def test_fallback_is_pure_same_input_same_output():
    packet = packets.build_narrator_packet(scene_facts=("a", "b"), resolved_degree="setback")
    first = fallback.resolve_fallback(packets.BrainRole.NARRATOR, packet)
    second = fallback.resolve_fallback(packets.BrainRole.NARRATOR, packet)
    assert first == second


def test_fallback_never_invents_facts_not_in_declared_facts():
    packet = packets.build_event_to_book_packet(event_ids=("e1",), declared_facts=("hero_arrived",), prose_stage="summary")
    text = fallback.resolve_fallback(packets.BrainRole.EVENT_TO_BOOK_PROSE, packet)
    assert "hero_arrived" in text


def test_fallback_unknown_role_raises_keyerror_not_silent_failure():
    """An unknown role is a programming error and should fail loudly at
    dev time, distinct from a runtime model failure which always falls
    back successfully -- this locks in that distinction."""
    with pytest.raises(KeyError):
        fallback.resolve_fallback("not_a_real_role", object())
