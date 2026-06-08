"""Tests for the Showrunner — dynamic scene blueprint + setup/payoff (Phase 2)."""

import studio_showrunner as S


def _understanding(n_events=8):
    return {
        "premise": "A betrayed enforcer is reborn by a burning barrel.",
        "themes": ["loyalty vs betrayal"],
        "tone": "noir",
        "motifs": ["smoke = truth", "jazz = the past"],
        "timeline": [
            {"order": i + 1, "event": f"Event {i + 1} happens", "location": "Darkside" if i % 2 else "Dockside",
             "characters": ["Louis"] + (["Rodney"] if i == 4 else [])}
            for i in range(n_events)
        ],
        "character_dossiers": [
            {"name": "Louis", "role": "protagonist", "want": "one last job"},
            {"name": "Rodney", "role": "antagonist", "want": "the promotion"},
        ],
        "setup_payoff_candidates": [
            {"setup": "Father Time: truth reveals itself in smoke", "possible_payoff": "the final scene"},
        ],
    }


# --------------------------------------------------------------------------- #
# Dynamic scene count
# --------------------------------------------------------------------------- #

def test_scene_count_scales_with_timeline_not_fixed_three():
    assert S.decide_scene_count(_understanding(8), {"tier": "medium"}) == 8
    # Floors at 4 for a tiny story.
    assert S.decide_scene_count(_understanding(1), {"tier": "medium"}) == 4
    # Caps by tier.
    assert S.decide_scene_count(_understanding(50), {"tier": "small"}) == 6
    assert S.decide_scene_count(_understanding(50), {"tier": "large"}) == 12


def test_scene_count_handles_empty():
    assert S.decide_scene_count({}, None) == 4


# --------------------------------------------------------------------------- #
# Deterministic blueprint
# --------------------------------------------------------------------------- #

def test_deterministic_blueprint_shape_and_ids():
    bp = S.build_blueprint(_understanding(8), profile={"tier": "medium"})
    assert bp["scene_count"] == len(bp["scenes"]) == 8
    ids = [s["id"] for s in bp["scenes"]]
    assert ids == [f"s{i + 1}" for i in range(8)]
    for s in bp["scenes"]:
        for key in S.SCENE_KEYS:
            assert key in s


def test_scenes_carry_a_dramatic_arc_not_flat_chunks():
    bp = S.build_blueprint(_understanding(8), profile={"tier": "medium"})
    funcs = [s["function"] for s in bp["scenes"]]
    # A real arc: opens on the ordinary world, ends on resolution, and hits a climax late.
    assert funcs[0] == "ordinary world"
    assert funcs[-1] == "resolution"
    assert "climax" in funcs
    # The blueprint exposes the whole-reel emotional contour.
    assert len(bp["emotional_arc"]) == 8
    assert bp["emotional_arc"][0]["scene_id"] == "s1"


def test_assign_functions_edges():
    assert S.assign_functions(1)[0][0]  # a single scene gets a function (its climax)
    two = [f for f, _ in S.assign_functions(2)]
    assert two[0] == "ordinary world" and two[-1] == "resolution"


def test_significant_events_get_their_own_scene_weighting():
    # 12 events, one flagged highly significant in the middle; with 6 scenes the heavy
    # event should not be averaged away — it lands in a bucket by itself.
    u = _understanding(12)
    u["timeline"][6]["significance"] = "the betrayal — turning point"
    bp = S.build_blueprint(u, profile={"tier": "small"})  # cap 6
    assert bp["scene_count"] == 6
    # The significant event's text surfaces as a scene purpose somewhere.
    assert any("Event 7" in s["purpose"] for s in bp["scenes"])
    # Every scene is non-empty (bucket repair guarantee).
    assert all(s["purpose"] for s in bp["scenes"])


def test_setup_payoff_is_first_class():
    bp = S.build_blueprint(_understanding(8), profile={"tier": "medium"})
    assert bp["setups"], "expected at least one setup thread"
    seed = bp["setups"][0]
    assert seed["planted_in"] and seed["paid_off_in"]
    # The payoff scene actually references the seed id.
    payoff_scene = next(s for s in bp["scenes"] if s["id"] == seed["paid_off_in"])
    assert seed["id"] in payoff_scene["pays_off"]
    # The plant scene carries the seed note.
    plant_scene = next(s for s in bp["scenes"] if s["id"] == seed["planted_in"])
    assert plant_scene["setup_seeds"]


def test_more_events_than_scenes_preserves_chronology():
    bp = S.build_blueprint(_understanding(20), profile={"tier": "small"})  # cap 6
    assert bp["scene_count"] == 6
    # Every scene has at least one event's worth of purpose, in order.
    assert all(s["purpose"] for s in bp["scenes"])


def test_characters_propagate_into_scenes():
    bp = S.build_blueprint(_understanding(8), profile={"tier": "medium"})
    all_chars = {c for s in bp["scenes"] for c in s["characters"]}
    assert "Louis" in all_chars
    assert "Rodney" in all_chars  # appears in a middle event


# --------------------------------------------------------------------------- #
# LLM path + normalization
# --------------------------------------------------------------------------- #

def test_llm_blueprint_is_normalized():
    def fake_llm(prompt, system_prompt, fallback, max_tokens=None):
        return {
            "summary": "spine",
            "scenes": [
                {"title": "Open", "location": "car", "characters": ["Louis"],
                 "purpose": "establish", "emotional_shift": "calm to unease",
                 "target_seconds": 14, "setup_seeds": ["ritual cigarette"], "pays_off": []},
                {"title": "Betrayal", "characters": ["Louis", "Rodney"],
                 "purpose": "the shot in the back", "pays_off": []},
            ],
            "setups": [{"id": "seed-1", "planted_in": "s1", "paid_off_in": "s2", "note": "cigarette"}],
        }

    bp = S.build_blueprint(_understanding(8), llm_call=fake_llm, profile={"tier": "medium"})
    assert bp["scene_count"] == 2
    # Ids were assigned even though the model omitted them.
    assert [s["id"] for s in bp["scenes"]] == ["s1", "s2"]
    assert bp["scenes"][0]["target_seconds"] == 14
    assert bp["setups"][0]["id"] == "seed-1"


def test_invalid_llm_blueprint_falls_back_to_deterministic():
    def bad_llm(prompt, system_prompt, fallback, max_tokens=None):
        return {"nonsense": True}  # no scenes

    bp = S.build_blueprint(_understanding(8), llm_call=bad_llm, profile={"tier": "medium"})
    assert bp["scene_count"] == 8  # deterministic path took over


def test_blueprint_to_storyboard_legacy_shape():
    bp = S.build_blueprint(_understanding(5), profile={"tier": "medium"})
    sb = S.blueprint_to_storyboard(bp)
    assert sb["summary"] == bp["summary"]
    assert len(sb["episodes"]) == len(bp["scenes"])
    assert all("name" in e and "summary" in e for e in sb["episodes"])
    assert sb["scene_blueprint"] is bp  # rich blueprint carried alongside
