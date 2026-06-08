"""Tests for Genesis — inventing a story_understanding from nothing (§9.3)."""

import studio_genesis as G
import studio_loremaster as L
import studio_showrunner as S


def _premise():
    return {"title": "The Last Signal", "theme": "letting go",
            "premise": "A lighthouse keeper named Mara guards a coast that ships no longer visit."}


# --------------------------------------------------------------------------- #
# Offline (skeleton) invention
# --------------------------------------------------------------------------- #

def test_offline_invents_full_understanding_contract():
    u = G.invent_understanding(_premise())
    # Same contract the Loremaster emits — downstream stages can't tell the difference.
    for key in L.UNDERSTANDING_KEYS:
        assert key in u
    assert u["timeline"], "invented story must have a timeline"
    assert u["character_dossiers"], "invented story must have a cast"


def test_offline_has_a_real_dramatic_arc():
    u = G.invent_understanding(_premise())
    sig = [e["significance"] for e in u["timeline"]]
    assert sig[0] == "ordinary world"
    assert "climax" in sig
    assert sig[-1] == "resolution"


def test_offline_uses_a_name_from_the_premise():
    u = G.invent_understanding(_premise())
    names = " ".join(d["name"] for d in u["character_dossiers"])
    assert "Mara" in names  # pulled the protagonist's name out of the premise


def test_empty_premise_still_produces_a_story():
    u = G.invent_understanding({})
    assert u["timeline"] and u["character_dossiers"]


# --------------------------------------------------------------------------- #
# LLM path
# --------------------------------------------------------------------------- #

def test_llm_invention_is_shaped_and_validated():
    def fake_llm(prompt, system_prompt, fallback, max_tokens=None):
        return {
            "title": "The Last Signal", "premise": "invented", "themes": ["letting go"],
            "tone": "elegiac", "motifs": ["light = memory"],
            "timeline": [{"event": "Mara lights the lamp for no one", "significance": "ordinary world",
                          "characters": ["Mara"]}],
            "character_dossiers": [{"name": "Mara", "role": "protagonist", "want": "to be needed"}],
            "world_facts": ["a dead coast"],
            "setup_payoff_candidates": [{"setup": "the lamp", "possible_payoff": "the final dark"}],
        }

    u = G.invent_understanding(_premise(), llm_call=fake_llm, profile={"tier": "medium"})
    assert u["tone"] == "elegiac"
    # order stamped even though the model omitted it
    assert u["timeline"][0]["order"] == 1


def test_invalid_llm_falls_back_to_skeleton():
    def bad_llm(prompt, system_prompt, fallback, max_tokens=None):
        return {"nope": True}

    u = G.invent_understanding(_premise(), llm_call=bad_llm, profile={"tier": "medium"})
    assert len(u["timeline"]) == len(G._SKELETON)  # skeleton took over


# --------------------------------------------------------------------------- #
# Genesis output drives the Showrunner like a real understanding
# --------------------------------------------------------------------------- #

def test_genesis_feeds_the_showrunner():
    u = G.invent_understanding(_premise())
    bp = S.build_blueprint(u, profile={"tier": "medium"})
    assert bp["scene_count"] >= 4
    assert bp["scenes"][0]["function"] == "ordinary world"
    assert any(s["purpose"] for s in bp["scenes"])
