"""Content pipeline tests for The Lost Meaning: Infinite Stacks (board task #2).

Covers:
  - the core pack loads and validates cleanly, and meets the §23.3 wave-1
    content quotas (4 backgrounds, 5 skills, >=8 cards, >=10 items, 6
    statuses, 3 enemies);
  - validators reject seeded-bad fixtures: an unknown cross-file reference,
    an unknown effect op, missing fallback prose, a condition with no
    treatment, and an enemy with no intent (§23.2).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.lan_playground.content import loader as L
from backend.lan_playground.content import schemas as S
from backend.lan_playground.content import validators as V
from backend.lan_playground.content.loader import load_core_pack, load_pack
from backend.lan_playground.content.validators import validate_pack_dir, validate_pack_strict

CORE_PACK_DIR = Path(__file__).resolve().parents[1] / "backend" / "lan_playground" / "content" / "packs" / "core"


# ---------------------------------------------------------------------------
# Core pack loads clean and meets the wave-1 content quotas
# ---------------------------------------------------------------------------


def test_core_pack_loads_and_validates_clean():
    pack = load_core_pack()
    validate_pack_strict(pack)  # must not raise


def test_core_pack_meets_wave1_quotas():
    pack = load_core_pack()

    assert len(pack.backgrounds) == 4
    assert len(pack.skills) == 5
    assert len(pack.cards) >= 8
    assert len(pack.items) >= 10
    assert len(pack.conditions) == 6
    assert len(pack.enemies) == 3
    assert "core_ordering_sequence" in pack.puzzle_templates


def test_core_pack_abilities_cover_the_migrated_offender_cards():
    """Wave-6 (board task #20, playtest §E1): read_the_room/plain_warning
    (general) and veteran_instinct/trophy_notes (retired_monster_hunter) were
    filler cards that did nothing mechanically; they moved out of the deck
    into abilities with real triggers and mechanic effects."""

    pack = load_core_pack()
    assert len(pack.abilities) >= 4
    migrated_ids = {"keen_observer", "plain_speaking", "veteran_instinct", "trophy_notes"}
    assert migrated_ids <= set(pack.abilities)
    for ability_id in migrated_ids:
        ability = pack.abilities[ability_id]
        assert ability.trigger.strip()
        assert ability.frequency.strip()
        assert ability.effects
    # the 5 named offenders are gone from the deck (signature_flourish was
    # redesigned in place, not migrated -- see cards.yaml's header comment).
    for offender in ("read_the_room", "plain_warning", "veteran_instinct", "trophy_notes"):
        assert offender not in pack.cards


def test_every_background_has_a_signature_ability_and_valid_bonus():
    pack = load_core_pack()
    assert len(pack.backgrounds) == 4
    for bg in pack.backgrounds.values():
        assert bg.attribute_bonus in S.ATTRIBUTE_IDS
        assert bg.signature_ability is not None
        assert bg.signature_ability.prose.fallback.strip()
        assert bg.skill_ranks


def test_every_card_has_full_card_contract_fields():
    pack = load_core_pack()
    for card in pack.cards.values():
        assert card.accessible_text.strip()
        assert card.prose.fallback.strip()
        assert card.legal_targets
        assert card.check is not None or card.base_effects
        assert card.keywords, card.id
        assert card.art_ref.strip(), card.id


def test_every_knowledge_item_has_zero_slot_cost():
    """§13.6, playtest E4: family_notes is a few pages, not equipment."""

    pack = load_core_pack()
    assert pack.items["family_notes"].knowledge is True
    assert pack.items["family_notes"].slot_cost == 0
    for item in pack.items.values():
        if item.knowledge:
            assert item.slot_cost == 0, item.id


def test_every_condition_has_one_primary_effect_and_a_treatment():
    pack = load_core_pack()
    assert len(pack.conditions) == 6
    for cond in pack.conditions.values():
        assert cond.primary_effect is not None
        assert cond.duration.strip()
        assert len(cond.treatments) >= 1


def test_every_enemy_has_threat_cost_and_telegraphed_intent():
    pack = load_core_pack()
    assert len(pack.enemies) == 3
    for enemy in pack.enemies.values():
        assert enemy.threat_cost > 0
        assert enemy.intents
        for intent in enemy.intents:
            assert intent.counterplay.strip()
            assert intent.prose.fallback.strip()


# ---------------------------------------------------------------------------
# Minimal-pack fixture builder, for seeded-bad-fixture tests below
# ---------------------------------------------------------------------------


def _minimal_pack_files() -> dict[str, Any]:
    """A minimal, individually-valid set of the six pack YAML files. Tests
    mutate one file at a time to introduce exactly one defect."""

    return {
        "skills.yaml": {
            "skills": [
                {
                    "id": "bonk",
                    "name": "Bonk",
                    "prose": {"fallback": "Force applied directly.", "accessible": "Skill: Bonk."},
                    "typical_uses": ["melee"],
                }
            ]
        },
        "backgrounds.yaml": {
            "backgrounds": [
                {
                    "id": "test_background",
                    "name": "Test Background",
                    "prose": {"fallback": "A test background.", "accessible": "Background: Test."},
                    "attribute_bonus": "force",
                    "skill_ranks": {"bonk": 1},
                    "starting_item_ids": ["test_item"],
                    "signature_ability": {
                        "id": "test_signature",
                        "name": "Test Signature",
                        "prose": {"fallback": "A signature move.", "accessible": "Signature: test."},
                        "frequency": "once_per_floor",
                        "effects": [],
                    },
                }
            ]
        },
        "cards.yaml": {
            "cards": [
                {
                    "id": "test_card",
                    "name": "Test Card",
                    "prose": {"fallback": "A test card.", "accessible": "Card: test."},
                    "accessible_text": "Test Card. Main action. Target: one enemy.",
                    "timing": "main_action",
                    "range": "melee",
                    "legal_targets": ["enemy"],
                    "keywords": ["Combat"],
                    "art_ref": "src/assets/cards/bonk.png",
                    "base_effects": [{"op": "emit_fact", "args": {"fact_id": "test_fact"}}],
                    "source": "general",
                }
            ]
        },
        "abilities.yaml": {
            "abilities": [
                {
                    "id": "test_ability",
                    "name": "Test Ability",
                    "prose": {"fallback": "A test ability.", "accessible": "Ability: test."},
                    "trigger": "passive",
                    "frequency": "unlimited",
                    "effects": [{"op": "emit_fact", "args": {"fact_id": "test_ability_fired"}}],
                    "source": "general",
                }
            ]
        },
        "items.yaml": {
            "items": [
                {
                    "id": "test_item",
                    "name": "Test Item",
                    "prose": {"fallback": "A test item.", "accessible": "Item: test."},
                    "use_effects": [{"op": "emit_fact", "args": {"fact_id": "test_item_used"}}],
                }
            ]
        },
        "conditions.yaml": {
            "conditions": [
                {
                    "id": "test_condition",
                    "name": "Test Condition",
                    "prose": {"fallback": "A test condition.", "accessible": "Condition: test."},
                    "primary_effect": {"op": "emit_fact", "args": {"fact_id": "test_cond"}},
                    "duration": "until_treated",
                    "treatments": [
                        {
                            "id": "test_treatment",
                            "prose": {"fallback": "Apply the fix.", "accessible": "Treatment: test."},
                            "effects": [],
                        }
                    ],
                }
            ]
        },
        "enemies.yaml": {
            "enemies": [
                {
                    "id": "test_enemy",
                    "name": "Test Enemy",
                    "family": "test_family",
                    "prose": {"fallback": "A test enemy.", "accessible": "Enemy: test."},
                    "threat_tier": "minion",
                    "threat_cost": 1,
                    "hp": 5,
                    "defense": 10,
                    "intents": [
                        {
                            "id": "test_intent",
                            "prose": {"fallback": "It winds up.", "accessible": "Intent: test."},
                            "trigger": "always",
                            "effects": [],
                            "counterplay": "Dodge or Block before it lands.",
                        }
                    ],
                }
            ]
        },
    }


def _write_pack(tmp_path: Path, files: dict[str, Any]) -> Path:
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    for filename, content in files.items():
        (pack_dir / filename).write_text(yaml.safe_dump(content), encoding="utf-8")
    return pack_dir


def test_minimal_fixture_itself_loads_and_validates_clean(tmp_path):
    """Sanity check on the fixture builder: before mutating it for each
    seeded-bad-fixture test, confirm the unmodified fixture is valid."""

    pack_dir = _write_pack(tmp_path, _minimal_pack_files())
    pack = validate_pack_dir(pack_dir, pack_id="fixture")
    assert pack.backgrounds and pack.cards and pack.items and pack.conditions and pack.enemies


# ---------------------------------------------------------------------------
# Seeded-bad fixtures the validators/loader must reject
# ---------------------------------------------------------------------------


def test_unknown_reference_rejected(tmp_path):
    files = _minimal_pack_files()
    files["backgrounds.yaml"]["backgrounds"][0]["starting_item_ids"] = ["nonexistent_item"]
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(V.ValidationError) as exc_info:
        validate_pack_dir(pack_dir, pack_id="fixture")
    assert any(f.rule == "unknown_reference" for f in exc_info.value.findings)


def test_unknown_effect_op_rejected(tmp_path):
    files = _minimal_pack_files()
    files["items.yaml"]["items"][0]["use_effects"] = [{"op": "frobnicate_the_enemy", "args": {}}]
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_missing_fallback_prose_rejected(tmp_path):
    files = _minimal_pack_files()
    files["skills.yaml"]["skills"][0]["prose"]["fallback"] = ""
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_missing_accessible_text_rejected(tmp_path):
    files = _minimal_pack_files()
    files["skills.yaml"]["skills"][0]["prose"]["accessible"] = ""
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_condition_missing_treatment_rejected(tmp_path):
    files = _minimal_pack_files()
    files["conditions.yaml"]["conditions"][0]["treatments"] = []
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_enemy_without_intent_rejected(tmp_path):
    files = _minimal_pack_files()
    files["enemies.yaml"]["enemies"][0]["intents"] = []
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_enemy_intent_missing_counterplay_rejected(tmp_path):
    files = _minimal_pack_files()
    files["enemies.yaml"]["enemies"][0]["intents"][0]["counterplay"] = ""
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_card_missing_keywords_rejected(tmp_path):
    files = _minimal_pack_files()
    files["cards.yaml"]["cards"][0]["keywords"] = []
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_card_missing_art_ref_rejected(tmp_path):
    files = _minimal_pack_files()
    files["cards.yaml"]["cards"][0]["art_ref"] = ""
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_ability_missing_trigger_rejected(tmp_path):
    files = _minimal_pack_files()
    files["abilities.yaml"]["abilities"][0]["trigger"] = ""
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_ability_missing_effects_rejected(tmp_path):
    files = _minimal_pack_files()
    files["abilities.yaml"]["abilities"][0]["effects"] = []
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_ability_with_unwired_trigger_rejected(tmp_path):
    """Director ruling 2026-07-20: an ability whose trigger the engine does
    not dispatch this wave must fail loudly, not ship as shelf-ware."""

    files = _minimal_pack_files()
    files["abilities.yaml"]["abilities"][0]["trigger"] = "on_enemy_sighted"
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_ability_with_non_executable_op_rejected(tmp_path):
    """grant_advantage is a real KNOWN_OPS op (Effect() accepts it) but is
    not in stacks-abilities' published executable set for abilities -- must
    still be rejected at the ability layer, same "no shelf-ware" rule."""

    files = _minimal_pack_files()
    files["abilities.yaml"]["abilities"][0]["effects"] = [{"op": "grant_advantage", "args": {}}]
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_ability_manual_trigger_requires_charge_frequency_rejected(tmp_path):
    files = _minimal_pack_files()
    files["abilities.yaml"]["abilities"][0]["trigger"] = "manual"
    files["abilities.yaml"]["abilities"][0]["frequency"] = "unlimited"
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_knowledge_item_with_nonzero_slot_cost_rejected(tmp_path):
    files = _minimal_pack_files()
    files["items.yaml"]["items"][0]["knowledge"] = True
    files["items.yaml"]["items"][0]["slot_cost"] = 1
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(S.ContentError):
        load_pack(pack_dir, pack_id="fixture")


def test_duplicate_id_rejected(tmp_path):
    files = _minimal_pack_files()
    files["skills.yaml"]["skills"].append(copy.deepcopy(files["skills.yaml"]["skills"][0]))
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(L.LoaderError):
        load_pack(pack_dir, pack_id="fixture")


def test_unknown_field_rejected(tmp_path):
    files = _minimal_pack_files()
    files["skills.yaml"]["skills"][0]["totally_made_up_field"] = "x"
    pack_dir = _write_pack(tmp_path, files)

    with pytest.raises(L.LoaderError):
        load_pack(pack_dir, pack_id="fixture")


# ---------------------------------------------------------------------------
# Effect IR reconciliation: unknown ops fail at construction, not runtime
# ---------------------------------------------------------------------------


def test_effect_rejects_unknown_op_directly():
    with pytest.raises(S.ContentError):
        S.Effect(op="not_a_real_op", args={})


def test_known_ops_marked_live_have_a_real_systems_handler():
    """Wave 2 update (2026-07-19, board task #5, stacks-effects): reveal_room,
    spend_energy, grant_check, and emit_fact now have real handlers wired
    through systems/effects.py's dispatch table (reached via systems/
    puzzles.py's Mystery Chamber success/failure consequences), so
    content/schemas.py marks all four OpStatus.LIVE. This replaces the
    wave-1 guard (which asserted the opposite -- that no op was LIVE yet,
    because no dispatcher existed at all) with the general rule going
    forward: nothing may be marked LIVE in KNOWN_OPS unless
    systems/effects.py actually dispatches it.

    Wave 5 update (2026-07-19, stacks-shopwire, board task #18):
    apply_condition/remove_condition join the LIVE set -- systems/effects.py
    now wires HeroState.active_condition_ids (§16.4-16.5), reached from
    shop_treat's dispatched treatment effects and any other authored content
    (enemies.yaml, cards.yaml, items.yaml) that already referenced these ops."""

    live_ops = {name for name, spec in S.KNOWN_OPS.items() if spec.status is S.OpStatus.LIVE}
    assert live_ops == {
        "reveal_room",
        "spend_energy",
        "grant_check",
        "emit_fact",
        "apply_condition",
        "remove_condition",
    }

    from backend.lan_playground.systems import effects as E

    for op_name in live_ops:
        assert op_name in E.LIVE_OPS, f"{op_name} is marked LIVE but systems/effects.py has no handler for it"


def test_compile_effects_round_trips_to_event_dict_ir():
    effects = [S.Effect(op="emit_fact", args={"fact_id": "example"})]
    compiled = S.compile_effects(effects)
    assert compiled == [{"op": "emit_fact", "args": {"fact_id": "example"}}]
