"""Tests for the Loremaster full-story understanding pass (Phase 0 keystone).

The central guarantee: the Loremaster reads the WHOLE story, so entities and events that
live in the middle of a long manuscript — which the old 6k head+tail excerpt dropped — are
recovered. We prove this against the real burning-barrel test asset.
"""

import os

import studio_loremaster as L

ASSET = os.path.join(os.path.dirname(__file__), "..", "docs", "assets", "burningbarreltest.md")


def _story():
    with open(ASSET, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #

def test_chunk_text_splits_and_preserves_order():
    text = "\n\n".join(f"Paragraph number {i} with some words." for i in range(50))
    chunks = L.chunk_text(text, max_chars=200)
    assert len(chunks) > 1
    # Every chunk is within budget (allowing one paragraph of slack).
    assert all(len(c) <= 260 for c in chunks)
    # Order is preserved: "number 0" before "number 49".
    joined = "\n".join(chunks)
    assert joined.index("number 0 ") < joined.index("number 49")


def test_chunk_text_hardwraps_oversized_paragraph():
    big = "word " * 400  # ~2000 chars, single paragraph
    chunks = L.chunk_text(big, max_chars=300)
    assert len(chunks) > 1
    assert all(len(c) <= 320 for c in chunks)


def test_chunk_text_empty():
    assert L.chunk_text("") == []
    assert L.chunk_text("   ") == []


# --------------------------------------------------------------------------- #
# Offline (analyzer-fallback) understanding
# --------------------------------------------------------------------------- #

def test_offline_recovers_middle_of_story_entities():
    """Rodney (~23%), Wesley (~25%) live in the middle the old excerpt dropped."""
    u = L.analyze_full(_story())  # no llm_call -> analyzer-fallback
    assert u["_grounding"] == "analyzer-fallback"
    names = " ".join(d["name"] for d in u["character_dossiers"]).lower()
    assert "rodney" in names
    assert "wesley" in names
    world = " ".join(str(w) for w in u["world_facts"]).lower()
    assert "darkside" in world


def test_offline_timeline_is_richer_than_three_beats():
    """The old planner forced exactly 3 beats; the full read yields many more events."""
    u = L.analyze_full(_story())
    assert len(u["timeline"]) > 3
    # Timeline is ordered.
    orders = [e["order"] for e in u["timeline"]]
    assert orders == sorted(orders)


def test_understanding_has_full_shape():
    u = L.analyze_full(_story())
    for key in L.UNDERSTANDING_KEYS:
        assert key in u


def test_empty_story_returns_empty_understanding():
    u = L.analyze_full("")
    assert u["character_dossiers"] == []
    assert u["timeline"] == []


# --------------------------------------------------------------------------- #
# Map-reduce path with a fake LLM
# --------------------------------------------------------------------------- #

def test_map_reduce_path_with_fake_llm():
    """A fake llm_call drives the map + synthesize calls; grounding flips to map-reduce."""
    calls = {"map": 0, "synth": 0}

    def fake_llm(prompt, system_prompt, fallback, max_tokens=None):
        if "ONE section" in system_prompt:
            calls["map"] += 1
            return {
                "events": [{"event": "Something happens", "characters": ["Louis"],
                            "location": "Darkside", "significance": "turn"}],
                "characters_seen": [{"name": "Louis", "traits": ["watchful", "petty"],
                                     "want": "one last job", "wound": "betrayal",
                                     "secret": "owes Goldstein", "key_lines": ["One last job."]}],
                "motifs": ["smoke = truth"], "world_facts": ["Grimstow City"],
                "notable_lines": [{"speaker": "Louis", "line": "One last job."}],
            }
        if "synthesize" in system_prompt.lower() or "story understanding" in system_prompt.lower():
            calls["synth"] += 1
            return {
                "title": "Burning Barrel", "premise": "A betrayed enforcer is reborn.",
                "themes": ["loyalty vs betrayal"], "tone": "noir",
                "motifs": ["smoke = truth"],
                "character_dossiers": [{"name": "Louis", "role": "protagonist",
                                        "traits": ["watchful"], "want": "one last job",
                                        "need": "trust", "wound": "betrayal", "secret": "debt",
                                        "relationships": [{"who": "Goldstein", "bond": "mentor-betrayer"}],
                                        "voice": "clipped", "key_lines": []}],
                "setup_payoff_candidates": [{"setup": "smoke reveals truth", "possible_payoff": "ending"}],
            }
        return fallback()

    u = L.analyze_full("Para one.\n\nPara two.\n\nPara three.", llm_call=fake_llm, max_chunk_chars=20)
    assert u["_grounding"] == "map-reduce"
    assert calls["map"] >= 1
    assert calls["synth"] == 1
    louis = u["character_dossiers"][0]
    assert louis["name"] == "Louis"
    # Synthesis dropped key_lines; the reduce step's real quote is restored onto the dossier.
    assert any("One last job" in l for l in louis["key_lines"])
    # The deterministic timeline is carried through verbatim (authoritative record).
    assert u["timeline"] and u["timeline"][0]["order"] == 1


def test_grounding_is_honest_when_llm_always_falls_back():
    """A dead/corrupt model: a callable is passed but every call returns the fallback. The label
    must say analyzer-fallback, not lie 'map-reduce'."""
    def dead_llm(prompt, system_prompt, fallback, max_tokens=None):
        return fallback()  # engine never ready -> always fall back

    u = L.analyze_full("Para one.\n\nPara two.\n\nPara three.", llm_call=dead_llm, max_chunk_chars=20)
    assert u["_grounding"] == "analyzer-fallback"


def test_dossier_grounding_renders_fields():
    from studio_workflow import _dossier_grounding
    text = _dossier_grounding({
        "traits": ["petty", "masterful"], "want": "respect", "wound": "betrayal",
        "voice": "clipped", "relationships": [{"who": "Goldstein", "bond": "betrayer"}],
        "key_lines": ["One last job."],
    })
    assert "petty" in text and "respect" in text and "Goldstein" in text and "One last job" in text
