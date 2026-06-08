"""Tests for the scene continuity audit — verifying setups actually pay off (§9.2b)."""

import studio_continuity as C


def _scene(sid, chars, lines, **kw):
    return {"id": sid, "characters": chars,
            "narration_script": [{"speaker": sp, "line": ln} for sp, ln in lines],
            "duration_seconds": kw.get("duration", 12), "target_seconds": 12,
            "function": kw.get("function", ""), "setup_seeds": kw.get("setup_seeds", [])}


# --------------------------------------------------------------------------- #
# The headline check: an unpaid setup is flagged HIGH
# --------------------------------------------------------------------------- #

def test_unpaid_setup_is_flagged_high():
    scenes = [
        _scene("s1", ["Louis"], [("Narrator", "He lit the ritual cigarette and waited.")],
               setup_seeds=["the ritual cigarette"]),
        _scene("s2", ["Louis"], [("Narrator", "He walked into the rain and never looked back.")]),
    ]
    blueprint = {"setups": [{"id": "seed-cig", "planted_in": "s1", "paid_off_in": "s2",
                             "note": "the ritual cigarette"}]}
    warns = C.audit_scenes(scenes, blueprint)
    high = [w for w in warns if w["severity"] == "high"]
    assert high and high[0]["scene_id"] == "s2"
    assert high[0]["repair_target"] == "script"


def test_paid_setup_passes():
    scenes = [
        _scene("s1", ["Louis"], [("Narrator", "He lit the ritual cigarette.")],
               setup_seeds=["the ritual cigarette"]),
        _scene("s2", ["Louis"], [("Narrator", "The same cigarette burned down to his fingers as it ended.")]),
    ]
    blueprint = {"setups": [{"id": "seed-cig", "planted_in": "s1", "paid_off_in": "s2",
                             "note": "the ritual cigarette"}]}
    warns = C.audit_scenes(scenes, blueprint)
    assert not [w for w in warns if w["severity"] == "high"]


def test_dangling_seed_is_low_warning():
    scenes = [_scene("s1", ["Louis"], [("Narrator", "A locket, never explained.")],
                     setup_seeds=["a silver locket"])]
    warns = C.audit_scenes(scenes, {"setups": []})
    assert any("silver locket" in w["message"] and w["severity"] == "low" for w in warns)


# --------------------------------------------------------------------------- #
# Roster / length / arc
# --------------------------------------------------------------------------- #

def test_off_roster_speaker_flagged():
    scenes = [_scene("s1", ["Louis"], [("Rodney", "You never saw it coming.")])]
    warns = C.audit_scenes(scenes, {})
    assert any("Rodney" in w["message"] and w["severity"] == "medium" for w in warns)


def test_thin_scene_flagged_low():
    scenes = [_scene("s1", ["Louis"], [("Narrator", "Cold.")], duration=3)]
    warns = C.audit_scenes(scenes, {})
    assert any("short" in w["message"].lower() for w in warns)


def test_early_climax_flagged():
    scenes = [_scene(f"s{i+1}", ["Louis"], [("Narrator", "x y z w")],
                     function="climax" if i == 0 else "rising action") for i in range(5)]
    warns = C.audit_scenes(scenes, {})
    assert any("climax" in w["message"].lower() for w in warns)


def test_clean_reel_has_no_high_warnings():
    scenes = [
        _scene("s1", ["Louis"], [("Narrator", "An ordinary night."), ("Louis", "One last job.")],
               function="ordinary world"),
        _scene("s2", ["Louis"], [("Narrator", "And it ended where it began.")], function="resolution"),
    ]
    warns = C.audit_scenes(scenes, {"setups": []})
    assert not [w for w in warns if w["severity"] == "high"]
