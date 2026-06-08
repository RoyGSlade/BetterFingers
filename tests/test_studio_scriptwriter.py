"""Tests for the Scriptwriter — authored per-scene narration + scene imagery (Phase 3)."""

import studio_scriptwriter as W


def _blueprint():
    return {
        "summary": "A betrayed enforcer is reborn.",
        "scene_count": 2,
        "scenes": [
            {"id": "s1", "title": "One Last Cigarette", "location": "The car",
             "characters": ["Louis"], "purpose": "Louis waits in the cold and reflects. One last job.",
             "emotional_shift": "calm to unease", "target_seconds": 12,
             "setup_seeds": ["the ritual cigarette"], "pays_off": []},
            {"id": "s2", "title": "The Shot in the Back", "location": "Wesley's office",
             "characters": ["Louis", "Rodney"], "purpose": "Rodney betrays Louis and shoots him.",
             "emotional_shift": "trust to betrayal", "target_seconds": 14,
             "setup_seeds": [], "pays_off": ["seed-1"]},
        ],
    }


def _understanding():
    return {"tone": "noir", "motifs": ["smoke = truth"],
            "character_dossiers": [{"name": "Louis", "key_lines": ["One last job."]}]}


def _characters():
    return [
        {"name": "Louis", "speech_style": "clipped, dry", "visual": {"hair": "dark", "outfit": "trench coat"},
         "key_lines": ["One last job."]},
        {"name": "Rodney", "speech_style": "whiny, nervous", "visual": {"build": "lanky"}},
    ]


def _world():
    return {"setting": "Grimstow City", "palette": "sodium amber", "lighting": "low-key",
            "locations": [{"name": "The car", "visual_prompt": "a cold sedan at night"}]}


# --------------------------------------------------------------------------- #
# Deterministic script (no LLM)
# --------------------------------------------------------------------------- #

def test_deterministic_scenes_have_authored_narration_not_balloons():
    scenes = W.build_scenes(_blueprint(), understanding=_understanding(),
                            world=_world(), characters=_characters())
    assert len(scenes) == 2
    s1 = scenes[0]
    assert s1["narration_script"], "scene must have a script"
    # Narrator beats are present (authored prose, not just dialogue balloons).
    assert any(b["speaker"] == "Narrator" for b in s1["narration_script"])
    # Every beat carries non-empty text + a duration (this is what fixes the empty-line crash).
    assert all(b["line"].strip() and b["duration_seconds"] >= 2 for b in s1["narration_script"])


def test_real_character_lines_are_voiced():
    scenes = W.build_scenes(_blueprint(), understanding=_understanding(),
                            world=_world(), characters=_characters())
    louis_lines = [b["line"] for s in scenes for b in s["narration_script"] if b["speaker"] == "Louis"]
    assert any("One last job" in l for l in louis_lines)


def test_each_scene_has_one_image_prompt():
    scenes = W.build_scenes(_blueprint(), understanding=_understanding(),
                            world=_world(), characters=_characters())
    for s in scenes:
        assert s["image_prompt"] and isinstance(s["image_prompt"], str)
        assert s["negative_prompt"]  # studio_visual always supplies base negatives
        # The location reference reaches the prompt.
    assert "car" in scenes[0]["image_prompt"].lower()


def test_scene_duration_sums_beats():
    scenes = W.build_scenes(_blueprint(), understanding=_understanding(),
                            world=_world(), characters=_characters())
    for s in scenes:
        assert s["duration_seconds"] == sum(b["duration_seconds"] for b in s["narration_script"])


def test_scene_carries_setup_payoff_refs():
    scenes = W.build_scenes(_blueprint(), understanding=_understanding(),
                            world=_world(), characters=_characters())
    assert "the ritual cigarette" in scenes[0]["setup_refs"]
    assert "seed-1" in scenes[1]["setup_refs"]


# --------------------------------------------------------------------------- #
# LLM path
# --------------------------------------------------------------------------- #

def test_llm_script_path():
    def fake_llm(prompt, system_prompt, fallback, max_tokens=None):
        if "Scriptwriter" in system_prompt:
            return [
                {"speaker": "Narrator", "line": "Cold settled over the car like a verdict, and the city held its breath.",
                 "emotion": "weary", "delivery": "slow"},
                {"speaker": "Louis", "line": "One last job.", "emotion": "resolved", "delivery": "quiet"},
            ]
        return fallback()

    scenes = W.build_scenes(_blueprint(), understanding=_understanding(), world=_world(),
                            characters=_characters(), llm_call=fake_llm, profile={"tier": "medium"})
    s1 = scenes[0]
    assert s1["narration_script"][0]["speaker"] == "Narrator"
    assert "verdict" in s1["narration_script"][0]["line"]
    # Longer narration => longer estimated duration.
    assert s1["narration_script"][0]["duration_seconds"] >= 4


def test_invalid_llm_script_falls_back():
    def bad_llm(prompt, system_prompt, fallback, max_tokens=None):
        return {"not": "a list"}

    scenes = W.build_scenes(_blueprint(), understanding=_understanding(), world=_world(),
                            characters=_characters(), llm_call=bad_llm, profile={"tier": "medium"})
    assert scenes[0]["narration_script"]  # deterministic fallback filled it


def test_empty_blueprint_yields_no_scenes():
    assert W.build_scenes({"scenes": []}) == []
    # A scene with nothing still produces a safe non-empty script (no crash downstream).
    scenes = W.build_scenes({"scenes": [{"id": "s1"}]})
    assert scenes[0]["narration_script"][0]["line"].strip()


# --------------------------------------------------------------------------- #
# Craft: authored payoff (§9.2b) + voice consistency (§9.2d)
# --------------------------------------------------------------------------- #

def _blueprint_with_setup():
    bp = _blueprint()
    bp["scenes"][1]["pays_off"] = ["seed-cig"]
    bp["setups"] = [{"id": "seed-cig", "planted_in": "s1", "paid_off_in": "s2",
                     "note": "the ritual cigarette"}]
    return bp


def test_payoff_scene_actually_lands_the_callback():
    scenes = W.build_scenes(_blueprint_with_setup(), understanding=_understanding(),
                            world=_world(), characters=_characters())
    # The paying scene's script must mention the planted detail — a tracked-but-unwritten
    # callback is the failure mode we guard against.
    s2_text = " ".join(b["line"] for b in scenes[1]["narration_script"]).lower()
    assert "cigarette" in s2_text
    # The non-paying scene does not force the callback.
    s1_text = " ".join(b["line"] for b in scenes[0]["narration_script"]).lower()
    assert "come back around" not in s1_text


def test_build_voice_guide_anchors_style_and_samples():
    guide = W.build_voice_guide(_characters(), _understanding())
    assert guide["louis"]["voice"] == "clipped, dry"
    assert any("One last job" in s for s in guide["louis"]["samples"])


def test_voice_guide_feeds_the_llm_prompt():
    seen = {}

    def fake_llm(prompt, system_prompt, fallback, max_tokens=None):
        seen["prompt"] = prompt
        seen["system"] = system_prompt
        return [{"speaker": "Louis", "line": "One last job.", "emotion": "resolved", "delivery": "quiet"}]

    W.build_scenes(_blueprint_with_setup(), understanding=_understanding(), world=_world(),
                   characters=_characters(), llm_call=fake_llm, profile={"tier": "medium"})
    # The character voice guide (style + samples) reaches the model, and the payoff is demanded.
    assert "clipped, dry" in seen["prompt"]
    assert "must_pay_off" in seen["prompt"]
    assert "PAYS OFF" in seen["system"]
