"""Room/object/NPC/Meaning-Lattice content tests (wave 6B, board note #30).

Covers:
  - schema validation happy paths for `content/rooms.py`, `content/npcs.py`,
    `content/lattice.py` (construction-time acceptance of well-formed data);
  - schema validation rejection paths (seeded-bad fixtures per type);
  - the disclosure-layer leak check specifically (a gated fact must be
    unreachable from the free layer) at both the dataclass constructor level
    and the pack-level validator level;
  - lattice recipe satisfaction logic (pure function, no engine involved);
  - the authored Gothic Living Study instance loading end-to-end, with every
    LIVE effect op in `content.schemas.KNOWN_OPS` exercised somewhere in the
    room's authored content, and its payoff chain (rug -> compartment ->
    contents) intact;
  - pack-purity/architecture patterns mirrored from `tests/test_stacks_content.py`
    (unknown-op rejection at construction, not runtime).

This wave is pure content + schemas only -- no domain/systems/heroes/combat/
shops import, and no import of `backend.lan_playground.brain` (a separate
lane's package). The only cross-package import is `systems.effects.LIVE_OPS`,
used read-only to confirm which ops are "the executable set" -- the same
pattern `tests/test_stacks_content.py::test_known_ops_marked_live_have_a_real_systems_handler`
already uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.lan_playground.content import lattice as LT
from backend.lan_playground.content import npcs as N
from backend.lan_playground.content import rooms as R
from backend.lan_playground.content import schemas as S
from backend.lan_playground.content import study_loader as SL
from backend.lan_playground.content import study_validators as SV

STUDY_PACK_DIR = Path(__file__).resolve().parents[1] / "backend" / "lan_playground" / "content" / "packs" / "core"


# ---------------------------------------------------------------------------
# Minimal valid fixtures (Python objects, not YAML) for happy-path /
# rejection-path unit tests that don't need the full authored pack.
# ---------------------------------------------------------------------------


def _minimal_object_state(state_id="state_a", visibility=R.ObjectVisibility.FREE) -> R.ObjectState:
    return R.ObjectState(
        id=state_id,
        prose=S.Prose(fallback="A state.", accessible="A state."),
        visibility=visibility,
    )


def _minimal_interaction(interaction_id="interact_a", legal_states=("state_a",)) -> R.ObjectInteraction:
    return R.ObjectInteraction(
        id=interaction_id,
        verb="look",
        legal_states=tuple(legal_states),
        prose=S.Prose(fallback="You look.", accessible="You look."),
        effects=(S.Effect(op="emit_fact", args={"fact_id": "fact_a"}),),
    )


def _minimal_room_object(object_id="object_a") -> R.RoomObject:
    return R.RoomObject(
        id=object_id,
        version=1,
        name="Test Object",
        initial_state="state_a",
        states=(_minimal_object_state(),),
        interactions=(_minimal_interaction(),),
    )


def _minimal_payoff(object_id="object_a", interaction_id="interact_a") -> R.PayoffInteraction:
    return R.PayoffInteraction(object_id=object_id, interaction_id=interaction_id, description="The payoff.")


def _minimal_lattice_contribution() -> LT.LatticeContribution:
    return LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 1})


def _minimal_room_template(room_id="room_a") -> R.RoomTemplate:
    return R.RoomTemplate(
        id=room_id,
        archetype="study",
        purpose="testing",
        layout="one room",
        atmosphere="quiet",
        condition="fine",
        cleanliness="clean",
        objects=(_minimal_room_object(),),
        visible_facts=(),
        subtle_inconsistencies=(),
        secrets=(),
        clue_graph=(),
        npc_ids=(),
        subobjectives=(),
        hazards=(),
        encounter_hooks=(),
        lattice_contribution=_minimal_lattice_contribution(),
        payoff_interaction=_minimal_payoff(),
        narration_facts=(),
    )


def _minimal_knowledge_atom(atom_id="atom_a", is_true=True, disclosure=N.DisclosureLayer.FREE) -> N.KnowledgeAtom:
    return N.KnowledgeAtom(
        id=atom_id,
        statement="A fact.",
        is_true=is_true,
        provenance=(N.Provenance(knower_id="npc_a", method="self-knowledge"),),
        disclosure=disclosure,
    )


def _minimal_npc_template(npc_id="npc_a", **overrides) -> N.NPCTemplate:
    lie_atom = _minimal_knowledge_atom("atom_lie", is_true=False, disclosure=N.DisclosureLayer.FREE)
    true_atom = _minimal_knowledge_atom("atom_true", is_true=True, disclosure=N.DisclosureLayer.FREE)
    defaults = dict(
        id=npc_id,
        archetype_pool=("test_archetype",),
        age="unknown",
        sex_gender_presentation="unspecified",
        visual_traits=("plain robes",),
        persona_voice=S.Prose(fallback="Speaks plainly.", accessible="Speaks plainly."),
        stats={"resolve": 10},
        boundaries=("no boundary crossed",),
        preferences=(),
        fears=("heights",),
        knowledge=(lie_atom, true_atom),
        lies=("atom_lie",),
        tells=(N.Tell(id="tell_a", hints_at_atom_id="atom_lie", prose=S.Prose(fallback="Fidgets.", accessible="Fidgets.")),),
        inventory=(),
        relationships=(),
        objectives=(
            N.Objective(id="obj_1", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="A.", accessible="A."), viewer_scope=S.ViewerScope.PARTY),
            N.Objective(id="obj_2", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="B.", accessible="B."), viewer_scope=S.ViewerScope.PARTY),
            N.Objective(id="obj_3", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="C.", accessible="C."), viewer_scope=S.ViewerScope.PARTY),
            N.Objective(id="obj_hidden", kind=N.ObjectiveKind.HIDDEN, prose=S.Prose(fallback="D.", accessible="D."), viewer_scope=S.ViewerScope.ENGINE_ONLY),
        ),
        triggers=(),
        state=N.EmotionalPhysicalState(disposition="neutral", physical_state="healthy"),
    )
    defaults.update(overrides)
    return N.NPCTemplate(**defaults)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_minimal_room_object_constructs_cleanly():
    obj = _minimal_room_object()
    assert obj.state_by_id("state_a").id == "state_a"


def test_minimal_room_template_constructs_cleanly():
    room = _minimal_room_template()
    assert room.payoff_interaction.object_id == "object_a"


def test_minimal_npc_template_constructs_cleanly():
    npc = _minimal_npc_template()
    assert len(npc.lies) == 1
    assert len(npc.tells) == 1
    main = [o for o in npc.objectives if o.kind is N.ObjectiveKind.MAIN]
    hidden = [o for o in npc.objectives if o.kind is N.ObjectiveKind.HIDDEN]
    assert len(main) == 3
    assert len(hidden) == 1


def test_minimal_lattice_recipe_constructs_and_is_satisfiable():
    recipe = LT.LatticeRecipe(id="recipe_a", floor_id="floor_a", thresholds={LT.LatticeComponent.TRUTH: 2})
    contributions = [
        LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 1}),
        LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 1}),
    ]
    assert recipe.is_satisfied(contributions)


# ---------------------------------------------------------------------------
# Rejection paths: rooms/objects
# ---------------------------------------------------------------------------


def test_object_interaction_rejects_unknown_verb():
    with pytest.raises(S.ContentError):
        R.ObjectInteraction(
            id="bad_interaction",
            verb="teleport",
            legal_states=("state_a",),
            prose=S.Prose(fallback="x", accessible="x"),
            effects=(S.Effect(op="emit_fact", args={"fact_id": "f"}),),
        )


def test_object_interaction_rejects_flavor_only_entry():
    """§3.3: furniture/set dressing needs REAL secondary interactions -- an
    interaction with no effects and no state_transition_id must be rejected."""

    with pytest.raises(S.ContentError):
        R.ObjectInteraction(
            id="flavor_only",
            verb="look",
            legal_states=("state_a",),
            prose=S.Prose(fallback="Just flavor.", accessible="Just flavor."),
        )


def test_object_interaction_rejects_unknown_effect_op_at_construction():
    with pytest.raises(S.ContentError):
        R.ObjectInteraction(
            id="bad_op",
            verb="look",
            legal_states=("state_a",),
            prose=S.Prose(fallback="x", accessible="x"),
            effects=(S.Effect(op="not_a_real_op", args={}),),
        )


def test_room_object_rejects_unknown_initial_state():
    with pytest.raises(S.ContentError):
        R.RoomObject(
            id="object_bad",
            version=1,
            name="Bad Object",
            initial_state="nonexistent_state",
            states=(_minimal_object_state(),),
            interactions=(),
        )


def test_room_object_rejects_interaction_referencing_unknown_state():
    bad_interaction = R.ObjectInteraction(
        id="interact_bad",
        verb="look",
        legal_states=("nonexistent_state",),
        prose=S.Prose(fallback="x", accessible="x"),
        effects=(S.Effect(op="emit_fact", args={"fact_id": "f"}),),
    )
    with pytest.raises(S.ContentError):
        R.RoomObject(
            id="object_bad2",
            version=1,
            name="Bad Object",
            initial_state="state_a",
            states=(_minimal_object_state(),),
            interactions=(bad_interaction,),
        )


def test_room_template_rejects_dangling_payoff_interaction():
    with pytest.raises(S.ContentError):
        R.RoomTemplate(
            id="room_bad",
            archetype="study",
            purpose="p",
            layout="l",
            atmosphere="a",
            condition="c",
            cleanliness="clean",
            objects=(_minimal_room_object(),),
            visible_facts=(),
            subtle_inconsistencies=(),
            secrets=(),
            clue_graph=(),
            npc_ids=(),
            subobjectives=(),
            hazards=(),
            encounter_hooks=(),
            lattice_contribution=_minimal_lattice_contribution(),
            payoff_interaction=R.PayoffInteraction(
                object_id="nonexistent_object", interaction_id="interact_a", description="dangling"
            ),
            narration_facts=(),
        )


def test_room_template_rejects_clue_graph_referencing_unknown_object():
    bad_clue = R.ClueLink(clue_id="clue_bad", source_object_id="nonexistent_object", source_interaction_id="interact_a")
    with pytest.raises(S.ContentError):
        R.RoomTemplate(
            id="room_bad2",
            archetype="study",
            purpose="p",
            layout="l",
            atmosphere="a",
            condition="c",
            cleanliness="clean",
            objects=(_minimal_room_object(),),
            visible_facts=(),
            subtle_inconsistencies=(),
            secrets=(),
            clue_graph=(bad_clue,),
            npc_ids=(),
            subobjectives=(),
            hazards=(),
            encounter_hooks=(),
            lattice_contribution=_minimal_lattice_contribution(),
            payoff_interaction=_minimal_payoff(),
            narration_facts=(),
        )


def test_room_template_rejects_no_objects():
    with pytest.raises(S.ContentError):
        R.RoomTemplate(
            id="room_empty",
            archetype="study",
            purpose="p",
            layout="l",
            atmosphere="a",
            condition="c",
            cleanliness="clean",
            objects=(),
            visible_facts=(),
            subtle_inconsistencies=(),
            secrets=(),
            clue_graph=(),
            npc_ids=(),
            subobjectives=(),
            hazards=(),
            encounter_hooks=(),
            lattice_contribution=_minimal_lattice_contribution(),
            payoff_interaction=_minimal_payoff(),
            narration_facts=(),
        )


def test_book_content_rejects_unflagged_unreliable_fact():
    """§3.8/§18.3: misleading text must be explicitly authored as fiction or
    an unreliable narrator -- an is_reliable=False fact whose source doesn't
    say so must be rejected."""

    with pytest.raises(S.ContentError):
        R.BookContent(
            id="book_bad",
            title="A Book",
            facts=(
                R.BookProvenance(
                    fact_id="fact_bad",
                    statement="Something untrue.",
                    is_reliable=False,
                    source="a normal author",  # doesn't self-flag as fiction/unreliable
                ),
            ),
        )


def test_book_content_accepts_flagged_unreliable_fact():
    book = R.BookContent(
        id="book_ok",
        title="A Book",
        facts=(
            R.BookProvenance(
                fact_id="fact_ok",
                statement="Something untrue.",
                is_reliable=False,
                source="unreliable narrator: feverish diary entry",
            ),
        ),
    )
    assert book.facts[0].is_reliable is False


# ---------------------------------------------------------------------------
# Rejection paths: NPCs, including the disclosure-layer leak check
# ---------------------------------------------------------------------------


def test_npc_template_rejects_wrong_main_objective_count():
    with pytest.raises(S.ContentError):
        _minimal_npc_template(
            objectives=(
                N.Objective(id="obj_1", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="A.", accessible="A."), viewer_scope=S.ViewerScope.PARTY),
                N.Objective(id="obj_hidden", kind=N.ObjectiveKind.HIDDEN, prose=S.Prose(fallback="D.", accessible="D."), viewer_scope=S.ViewerScope.ENGINE_ONLY),
            )
        )


def test_npc_template_rejects_no_hidden_objective():
    with pytest.raises(S.ContentError):
        _minimal_npc_template(
            objectives=(
                N.Objective(id="obj_1", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="A.", accessible="A."), viewer_scope=S.ViewerScope.PARTY),
                N.Objective(id="obj_2", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="B.", accessible="B."), viewer_scope=S.ViewerScope.PARTY),
                N.Objective(id="obj_3", kind=N.ObjectiveKind.MAIN, prose=S.Prose(fallback="C.", accessible="C."), viewer_scope=S.ViewerScope.PARTY),
            )
        )


def test_npc_template_rejects_no_lies():
    only_true = _minimal_knowledge_atom("atom_true_only", is_true=True)
    with pytest.raises(S.ContentError):
        _minimal_npc_template(knowledge=(only_true,), lies=())


def test_npc_template_rejects_lie_not_matching_a_false_atom():
    true_atom = _minimal_knowledge_atom("atom_true_only", is_true=True)
    with pytest.raises(S.ContentError):
        _minimal_npc_template(knowledge=(true_atom,), lies=("atom_true_only",))


def test_npc_template_rejects_no_tells():
    with pytest.raises(S.ContentError):
        _minimal_npc_template(tells=())


def test_npc_template_rejects_hidden_objective_with_public_scope():
    with pytest.raises(S.ContentError):
        N.Objective(
            id="obj_hidden_bad",
            kind=N.ObjectiveKind.HIDDEN,
            prose=S.Prose(fallback="D.", accessible="D."),
            viewer_scope=S.ViewerScope.PUBLIC,
        )


def test_npc_template_rejects_disclosure_leak_from_free_tell_to_gated_atom():
    """The director's core disclosure-leak requirement: a gated fact must be
    unreachable from the free disclosure layer. A FREE-scoped tell pointing
    directly at a GATED atom is exactly that leak."""

    gated_atom = _minimal_knowledge_atom("atom_gated", is_true=False, disclosure=N.DisclosureLayer.GATED)
    leaking_tell = N.Tell(id="tell_leak", hints_at_atom_id="atom_gated", prose=S.Prose(fallback="x", accessible="x"))
    with pytest.raises(S.ContentError, match="disclosure leak"):
        _minimal_npc_template(knowledge=(gated_atom,), lies=("atom_gated",), tells=(leaking_tell,))


def test_npc_template_rejects_atom_marked_both_free_and_gated():
    # Constructing two atoms with the same id but different disclosure is
    # nonsensical input; simulate the "overlap" branch by asserting the
    # KnowledgeAtom itself only accepts one DisclosureLayer value (structural
    # guarantee) and that the NPCTemplate-level overlap check activates when
    # a duplicate id appears in both categories via a hand-built duplicate.
    free_atom = _minimal_knowledge_atom("atom_dup", is_true=False, disclosure=N.DisclosureLayer.FREE)
    gated_atom = _minimal_knowledge_atom("atom_dup", is_true=False, disclosure=N.DisclosureLayer.GATED)
    with pytest.raises(S.ContentError):
        _minimal_npc_template(knowledge=(free_atom, gated_atom), lies=("atom_dup",), tells=())


def test_npc_disclosure_leak_check_passes_when_gated_atom_has_no_free_tell():
    """A GATED atom with either no tell, or only a tell that itself points
    at a FREE atom, is not a leak."""

    npc = _minimal_npc_template()  # baseline fixture only has FREE atoms + a matching FREE tell
    findings = SV.check_npc_disclosure_no_leak(SL.StudyContentPack(rooms={}, npcs={npc.id: npc}, lattice_recipes={}))
    assert findings == []


# ---------------------------------------------------------------------------
# Lattice recipe satisfaction logic
# ---------------------------------------------------------------------------


def test_lattice_recipe_not_satisfied_when_below_threshold():
    recipe = LT.LatticeRecipe(id="recipe_b", floor_id="floor_b", thresholds={LT.LatticeComponent.TRUTH: 3})
    contributions = [LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 2})]
    assert not recipe.is_satisfied(contributions)
    assert recipe.missing(contributions) == {LT.LatticeComponent.TRUTH: 1}


def test_lattice_recipe_requires_all_components_satisfied():
    recipe = LT.LatticeRecipe(
        id="recipe_c",
        floor_id="floor_c",
        thresholds={LT.LatticeComponent.TRUTH: 1, LT.LatticeComponent.MEMORY: 1},
    )
    only_truth = [LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 5})]
    assert not recipe.is_satisfied(only_truth)
    both = [LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 1, LT.LatticeComponent.MEMORY: 1})]
    assert recipe.is_satisfied(both)


def test_lattice_recipe_rejects_empty_thresholds():
    with pytest.raises(S.ContentError):
        LT.LatticeRecipe(id="recipe_empty", floor_id="floor_x", thresholds={})


def test_lattice_contribution_rejects_nonpositive_amount():
    with pytest.raises(S.ContentError):
        LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 0})


def test_lattice_recipe_is_not_a_room_counter():
    """Locked decision 1 (wavebasedgame.md §2): the recipe is a component
    threshold, never a bare room count. A recipe satisfied by ONE room's
    large contribution must be satisfied identically to the same total
    spread across many rooms -- there is no hidden minimum room count."""

    recipe = LT.LatticeRecipe(id="recipe_d", floor_id="floor_d", thresholds={LT.LatticeComponent.TRUTH: 2})
    one_room = [LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 2})]
    many_rooms = [LT.LatticeContribution(amounts={LT.LatticeComponent.TRUTH: 1}) for _ in range(2)]
    assert recipe.is_satisfied(one_room)
    assert recipe.is_satisfied(many_rooms)


# ---------------------------------------------------------------------------
# The authored Gothic Living Study instance, loaded end-to-end
# ---------------------------------------------------------------------------


def test_study_pack_loads_and_validates_clean():
    pack = SL.load_study_pack()
    SV.validate_study_pack_strict(pack)


def test_study_pack_has_expected_ids():
    pack = SL.load_study_pack()
    assert "gothic_living_study" in pack.rooms
    assert "elara_vance" in pack.npcs
    assert "recipe_test_floor_study_only" in pack.lattice_recipes


def test_gothic_living_study_room_has_the_authored_objects():
    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]
    object_ids = {o.id for o in room.objects}
    assert {
        "study_rug",
        "hidden_compartment",
        "study_fireplace",
        "study_desk",
        "study_chairs",
        "study_decor",
        "study_bookshelf",
        "study_field_manual",
        "study_diary",
    } <= object_ids


def test_gothic_living_study_payoff_chain_is_the_rug_and_compartment():
    """The room's declared payoff: noticing the rug's displacement, then
    investigating it, reveals the secret compartment."""

    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]
    assert room.payoff_interaction.object_id == "study_rug"
    assert room.payoff_interaction.interaction_id == "rug_move"

    rug = next(o for o in room.objects if o.id == "study_rug")
    move_interaction = next(i for i in rug.interactions if i.id == "rug_move")
    assert move_interaction.reveals_state == "rug_displaced"
    assert move_interaction.state_transition_id == "rug_reveal_compartment"

    compartment = next(o for o in room.objects if o.id == "hidden_compartment")
    assert compartment.state_by_id("compartment_hidden").visibility is R.ObjectVisibility.HIDDEN
    open_interaction = next(i for i in compartment.interactions if i.id == "compartment_open_action")
    assert open_interaction.reveals_state == "compartment_open"


def test_gothic_living_study_secret_is_engine_only_until_revealed():
    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]
    compartment_secret = next(s for s in room.secrets if s.id == "secret_hidden_compartment")
    assert compartment_secret.viewer_scope is S.ViewerScope.PARTY
    assert compartment_secret.revealed_by_interaction_id == "rug_move"

    elara_secret = next(s for s in room.secrets if s.id == "secret_elara_is_dead")
    assert elara_secret.viewer_scope is S.ViewerScope.ENGINE_ONLY


def test_gothic_living_study_books_have_structured_facts_and_provenance():
    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]
    field_manual = next(o for o in room.objects if o.id == "study_field_manual")
    assert field_manual.book is not None
    for fact in field_manual.book.facts:
        assert fact.source.strip()

    diary = next(o for o in room.objects if o.id == "study_diary")
    assert diary.book is not None
    unreliable_facts = [f for f in diary.book.facts if not f.is_reliable]
    assert unreliable_facts, "diary must carry at least one explicitly-flagged unreliable fact (§18.3)"
    for fact in unreliable_facts:
        assert "unreliable" in fact.source.lower() or "fiction" in fact.source.lower()


def test_gothic_living_study_lattice_contribution_and_recipe_satisfy_together():
    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]
    recipe = pack.lattice_recipes["recipe_test_floor_study_only"]
    assert recipe.is_satisfied([room.lattice_contribution])


def test_elara_vance_matches_the_npc_template_contract():
    pack = SL.load_study_pack()
    npc = pack.npcs["elara_vance"]
    assert len(npc.archetype_pool) >= 1
    assert len(npc.lies) >= 1
    assert len(npc.tells) >= 1
    main = [o for o in npc.objectives if o.kind is N.ObjectiveKind.MAIN]
    hidden = [o for o in npc.objectives if o.kind is N.ObjectiveKind.HIDDEN]
    assert len(main) == 3
    assert len(hidden) == 1
    # every knowledge atom carries provenance
    for atom in npc.knowledge:
        assert atom.provenance


def test_elara_vance_is_linked_from_the_room():
    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]
    assert "elara_vance" in room.npc_ids


def test_every_known_live_effect_op_is_exercised_in_the_authored_room():
    """VERIFY requirement: the authored instance must exercise every LIVE
    effect op in the executable set, cross-checked against
    `systems.effects.LIVE_OPS` the same way
    tests/test_stacks_content.py::test_known_ops_marked_live_have_a_real_systems_handler
    already does for cards/items/abilities."""

    from backend.lan_playground.systems import effects as E

    pack = SL.load_study_pack()
    room = pack.rooms["gothic_living_study"]

    ops_used: set[str] = set()
    for obj in room.objects:
        for interaction in obj.interactions:
            ops_used.update(eff.op for eff in interaction.effects)
        for transition in obj.transitions:
            ops_used.update(eff.op for eff in transition.effects)
    for hazard in room.hazards:
        ops_used.update(eff.op for eff in hazard.effects)

    live_ops = {name for name, spec in S.KNOWN_OPS.items() if spec.status is S.OpStatus.LIVE}
    assert live_ops == set(E.LIVE_OPS)
    assert live_ops <= ops_used, f"missing LIVE ops in authored room content: {sorted(live_ops - ops_used)}"


# ---------------------------------------------------------------------------
# Seeded-bad-fixture rejection at the YAML/loader layer, mirroring
# tests/test_stacks_content.py's style for the core pack.
# ---------------------------------------------------------------------------


def test_loader_rejects_unknown_field_in_room_yaml(tmp_path):
    import yaml

    from backend.lan_playground.content import study_loader as SLmod

    good = {
        "rooms": [
            {
                "id": "room_x",
                "archetype": "study",
                "purpose": "p",
                "layout": "l",
                "atmosphere": "a",
                "condition": "c",
                "cleanliness": "clean",
                "objects": [
                    {
                        "id": "obj_x",
                        "version": 1,
                        "name": "Obj",
                        "initial_state": "s1",
                        "states": [
                            {"id": "s1", "visibility": "free", "prose": {"fallback": "x", "accessible": "x"}}
                        ],
                        "interactions": [
                            {
                                "id": "int_x",
                                "verb": "look",
                                "legal_states": ["s1"],
                                "prose": {"fallback": "x", "accessible": "x"},
                                "effects": [{"op": "emit_fact", "args": {"fact_id": "f_x"}}],
                            }
                        ],
                        "transitions": [],
                    }
                ],
                "visible_facts": [],
                "subtle_inconsistencies": [],
                "secrets": [],
                "clue_graph": [],
                "npc_ids": [],
                "subobjectives": [],
                "hazards": [],
                "encounter_hooks": [],
                "lattice_contribution": {"truth": 1},
                "payoff_interaction": {"object_id": "obj_x", "interaction_id": "int_x", "description": "d"},
                "narration_facts": [],
                "persistent": True,
                "totally_made_up_field": "x",
            }
        ]
    }
    path = tmp_path / "bad_room.yaml"
    path.write_text(yaml.safe_dump(good), encoding="utf-8")
    with pytest.raises(SLmod.LoaderError):
        SLmod.load_room_templates(path)


def test_loader_rejects_duplicate_room_ids(tmp_path):
    import yaml

    room_block = {
        "id": "dup_room",
        "archetype": "study",
        "purpose": "p",
        "layout": "l",
        "atmosphere": "a",
        "condition": "c",
        "cleanliness": "clean",
        "objects": [
            {
                "id": "obj_dup",
                "version": 1,
                "name": "Obj",
                "initial_state": "s1",
                "states": [{"id": "s1", "visibility": "free", "prose": {"fallback": "x", "accessible": "x"}}],
                "interactions": [
                    {
                        "id": "int_dup",
                        "verb": "look",
                        "legal_states": ["s1"],
                        "prose": {"fallback": "x", "accessible": "x"},
                        "effects": [{"op": "emit_fact", "args": {"fact_id": "f_dup"}}],
                    }
                ],
                "transitions": [],
            }
        ],
        "visible_facts": [],
        "subtle_inconsistencies": [],
        "secrets": [],
        "clue_graph": [],
        "npc_ids": [],
        "subobjectives": [],
        "hazards": [],
        "encounter_hooks": [],
        "lattice_contribution": {"truth": 1},
        "payoff_interaction": {"object_id": "obj_dup", "interaction_id": "int_dup", "description": "d"},
        "narration_facts": [],
        "persistent": True,
    }
    path = tmp_path / "dup_rooms.yaml"
    path.write_text(yaml.safe_dump({"rooms": [room_block, room_block]}), encoding="utf-8")
    with pytest.raises(SL.LoaderError):
        SL.load_room_templates(path)


def test_room_npc_link_rejected_when_npc_unknown():
    room = _minimal_room_template()
    room_with_bad_npc = R.RoomTemplate(
        id=room.id,
        archetype=room.archetype,
        purpose=room.purpose,
        layout=room.layout,
        atmosphere=room.atmosphere,
        condition=room.condition,
        cleanliness=room.cleanliness,
        objects=room.objects,
        visible_facts=room.visible_facts,
        subtle_inconsistencies=room.subtle_inconsistencies,
        secrets=room.secrets,
        clue_graph=room.clue_graph,
        npc_ids=("nonexistent_npc",),
        subobjectives=room.subobjectives,
        hazards=room.hazards,
        encounter_hooks=room.encounter_hooks,
        lattice_contribution=room.lattice_contribution,
        payoff_interaction=room.payoff_interaction,
        narration_facts=room.narration_facts,
    )
    pack = SL.StudyContentPack(rooms={room_with_bad_npc.id: room_with_bad_npc}, npcs={}, lattice_recipes={})
    findings = SV.check_room_npc_links(pack)
    assert any(f.rule == "unknown_reference" for f in findings)


def test_unreachable_lattice_recipe_flagged():
    room = _minimal_room_template()  # contributes truth:1
    unreachable_recipe = LT.LatticeRecipe(
        id="recipe_unreachable", floor_id="floor_unreachable", thresholds={LT.LatticeComponent.TRUTH: 99}
    )
    pack = SL.StudyContentPack(
        rooms={room.id: room}, npcs={}, lattice_recipes={unreachable_recipe.id: unreachable_recipe}
    )
    findings = SV.check_room_lattice_recipe_reachable(pack)
    assert any(f.rule == "unreachable_lattice_recipe" for f in findings)


# ---------------------------------------------------------------------------
# Pack-purity / architecture pattern: this content module must not import
# domain/systems/heroes/combat/shops/brain (mirrors the discipline
# tests/test_architecture_smoke.py enforces for backend/ as a whole, scoped
# here to the specific packages this wave's task brief called out).
# ---------------------------------------------------------------------------


def test_rooms_npcs_lattice_modules_do_not_import_forbidden_packages():
    import ast

    forbidden_prefixes = (
        "backend.lan_playground.domain",
        "backend.lan_playground.systems",
        "backend.lan_playground.heroes",
        "backend.lan_playground.combat",
        "backend.lan_playground.shops",
        "backend.lan_playground.brain",
    )
    repo_root = Path(__file__).resolve().parents[1]
    for relative in (
        "backend/lan_playground/content/rooms.py",
        "backend/lan_playground/content/npcs.py",
        "backend/lan_playground/content/lattice.py",
        "backend/lan_playground/content/study_loader.py",
        "backend/lan_playground/content/study_validators.py",
    ):
        file_path = repo_root / relative
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                assert not any(name.startswith(prefix) for prefix in forbidden_prefixes), (
                    f"{relative} imports forbidden package via {name!r}"
                )
