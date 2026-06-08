"""Tests for the Visual Prompt Compiler (MEDIA_DISPATCHER §4)."""

import studio_prompt_compiler as C


def _world():
    return {
        "palette": "sodium amber, rain-slick black",
        "lighting": "low-key, hard shadows",
        "materials": "wet asphalt, brushed brass",
        "avoid": ["bright comedy lighting", "generic fantasy armor"],
        "locations": [
            {"name": "The Waterfront", "visual_prompt": "fog over black water, shipping containers",
             "mood": "cold, exposed", "recurring_props": ["dock light", "gulls"]},
        ],
    }


def _characters():
    return [
        {"name": "Louis", "visual": {"face": "lived-in, alert eyes", "hair": "dark, unfussed",
                                     "build": "lean, tense", "outfit": "dark coat, loosened tie",
                                     "palette": "charcoal, tobacco"},
         "negative_locks": ["do not make him bulky"]},
        {"name": "Rodney", "visual": {"outfit": "charcoal overcoat", "hair": "slicked back"}},
    ]


def _scene():
    return {"id": "s4", "title": "The Betrayal", "location": "The Waterfront",
            "characters": ["Louis", "Rodney"], "purpose": "Rodney smirks as Louis realizes the betrayal",
            "emotional_shift": "trust to dread"}


# --------------------------------------------------------------------------- #
# Bible builders
# --------------------------------------------------------------------------- #

def test_build_bibles_from_existing_data():
    style = C.build_style_bible(_world())
    assert "sodium amber" in style["palette"]
    assert "bright comedy lighting" in style["avoid"]
    cvis = C.build_character_visuals(_characters())
    assert "alert eyes" in cvis["louis"]["base_description"]
    assert cvis["louis"]["outfit"] == "dark coat, loosened tie"
    assert "do not make him bulky" in cvis["louis"]["negative_locks"]
    lvis = C.build_location_visuals(_world())
    assert "black water" in lvis["the waterfront"]["visual_identity"]


# --------------------------------------------------------------------------- #
# Compile
# --------------------------------------------------------------------------- #

def test_compile_packet_shape_and_content():
    style = C.build_style_bible(_world())
    cvis = C.build_character_visuals(_characters())
    lvis = C.build_location_visuals(_world())
    packet = C.compile_visual_prompt(_scene(), style, cvis, lvis)
    pos, neg = packet.positive_prompt.lower(), packet.negative_prompt.lower()
    # Action, location, characters, palette and house quality terms all reach the positive prompt.
    assert "realizes the betrayal" in pos
    assert "black water" in pos
    assert "louis" in pos and "rodney" in pos
    assert "sodium amber" in pos
    # Negative carries base guards, style avoids, and per-character locks.
    assert "deformed hands" in neg
    assert "bright comedy lighting" in neg
    assert "do not make him bulky" in neg
    assert "rodney wrong outfit" in neg
    # Generation params come from the default model profile.
    assert packet.steps == 24 and packet.sampler == "dpmpp_2m"


def test_seed_is_stable_and_cast_sensitive():
    s1 = C.stable_seed("s4", ["Louis", "Rodney"])
    s2 = C.stable_seed("s4", ["Rodney", "Louis"])  # order-independent
    s3 = C.stable_seed("s5", ["Louis", "Rodney"])  # different scene
    assert s1 == s2 and s1 != s3 and s1 >= 0


def test_locked_seed_overrides_derived():
    packet = C.compile_visual_prompt(_scene(), {}, {}, {}, model_profile={"seed": 12345})
    assert packet.seed == 12345


def test_compile_for_scenes_attaches_packets_and_syncs_flat_fields():
    scenes = [_scene(), {"id": "s5", "characters": ["Louis"], "purpose": "Louis walks alone"}]
    packets = C.compile_for_scenes(scenes, _world(), _characters())
    assert len(packets) == 2
    assert scenes[0]["prompt_packet"]["positive_prompt"] == scenes[0]["image_prompt"]
    assert scenes[0]["prompt_packet"]["negative_prompt"] == scenes[0]["negative_prompt"]
    # Deterministic: recompiling yields the same seed.
    again = C.compile_for_scenes([_scene()], _world(), _characters())
    assert again[0]["seed"] == scenes[0]["prompt_packet"]["seed"]


def test_empty_inputs_still_compile():
    packet = C.compile_visual_prompt({"id": "s1"})
    assert packet.positive_prompt and packet.negative_prompt
    assert packet.seed >= 0
