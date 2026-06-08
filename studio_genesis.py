"""
Genesis — the Inventor. Fabricates a `story_understanding` when there is NO manuscript.

Phase §9.3 of the overhaul. The owner's explicit ask: *"click a button and it generates a
beautiful story regardless of whether I gave it anything."* Today seed mode has only a thin
2-sentence premise, so `run_loremaster` returns None and the Showrunner has no timeline to
shape. Genesis fills that hole: from a premise (and optional seed), it INVENTS the same
structured `story_understanding` the Loremaster emits — a real arc, a cast with wants/wounds,
motifs, and setup/payoff candidates — so every downstream stage is identical whether the story
was *read* or *invented*. Giving a manuscript enriches; it is never required.

Output contract == `studio_loremaster.UNDERSTANDING_KEYS` (so the Showrunner/Scriptwriter can't
tell the difference). Graceful like the rest: with no LLM it lays down a coherent hero's-journey
skeleton built from the premise, so even offline the "surprise me" button produces a shaped story.
"""

import logging

logger = logging.getLogger("studio_genesis")

# A generic hero's-journey skeleton (function, beat-template). The {lead}/{foil} slots are filled
# from the invented/derived cast; this gives the deterministic fallback a real arc, not filler.
_SKELETON = [
    ("ordinary world", "{lead} lives inside a fragile normal, one quiet ache away from change."),
    ("inciting incident", "Something breaks the calm and pulls {lead} toward a threshold they can't un-cross."),
    ("rising action", "{lead} tests the new world, gathers allies and enemies, and {foil} enters the frame."),
    ("midpoint turn", "A reversal rewrites the stakes: what {lead} wanted is not what {lead} needs."),
    ("raising the stakes", "The cost climbs. {foil} closes in and {lead}'s flaw starts to show its teeth."),
    ("dark night", "{lead} loses what mattered and faces the truth they've been avoiding."),
    ("climax", "{lead} confronts {foil} and chooses — paying the price, claiming the change."),
    ("resolution", "The world settles, altered. {lead} returns transformed, the old ache answered."),
]


def invent_understanding(premise, seed_text="", llm_call=None, profile=None, progress=None, taste=""):
    """Invent a full `story_understanding` from a premise (and optional seed)."""
    premise = premise or {}
    title = (premise.get("title") or "").strip() or "Untitled"
    theme = (premise.get("theme") or "").strip()
    premise_text = (premise.get("premise") or "").strip() or seed_text.strip()

    if progress:
        try:
            progress("Inventing a story from your seed...")
        except Exception:
            pass

    def fallback():
        u = _skeleton_understanding(title, theme, premise_text, seed_text)
        u["_grounding"] = "invented-fallback"
        return u

    if not callable(llm_call):
        return fallback()

    import json
    system_prompt = (
        "You are the story Inventor. The user gave only a short seed/premise — invent a COMPLETE, "
        "original short story worth watching, then return it as structured understanding. Give it a "
        "real dramatic arc (ordinary world → inciting incident → rising action → midpoint turn → "
        "raising stakes → dark night → climax → resolution), a small cast with real wants, needs, "
        "wounds and secrets, recurring motifs, and a few setups that pay off later. Be specific and "
        "evocative, not generic. Output ONLY a JSON object: "
        '{"title": "", "premise": "2-3 sentences", "themes": ["theme"], "tone": "", '
        '"motifs": ["image = meaning"], '
        '"timeline": [{"order": 1, "event": "what concretely happens", "location": "", '
        '"characters": ["Name"], "significance": "why it matters"}], '
        '"character_dossiers": [{"name": "", "role": "protagonist|antagonist|ally|mentor|supporting", '
        '"traits": ["edge-y adjective"], "want": "", "need": "", "wound": "", "secret": "", '
        '"relationships": [{"who": "", "bond": ""}], "voice": "", "key_lines": [""]}], '
        '"world_facts": [""], '
        '"setup_payoff_candidates": [{"setup": "what is planted", "possible_payoff": "how it lands"}]}'
    ) + (taste or "")
    prompt = json.dumps({"title": title, "theme": theme, "premise": premise_text, "seed": seed_text},
                        ensure_ascii=False)
    max_tokens = _tokens(profile, "large", 2000)

    result = llm_call(prompt, system_prompt, fallback, max_tokens)
    if not _is_valid(result):
        return fallback()
    out = _ensure_shape(result, title, theme, premise_text)
    out["_grounding"] = "invented" if (result.get("_grounding") != "invented-fallback") else "invented-fallback"
    return out


# --------------------------------------------------------------------------- #
# Deterministic skeleton
# --------------------------------------------------------------------------- #

def _skeleton_understanding(title, theme, premise_text, seed_text):
    lead, foil = _invent_cast(premise_text or seed_text or title)
    motifs = _motifs_from(premise_text or seed_text or theme)
    timeline = []
    for i, (func, template) in enumerate(_SKELETON):
        timeline.append({
            "order": i + 1,
            "event": template.format(lead=lead["name"], foil=foil["name"]),
            "location": "",
            "characters": [lead["name"]] + ([foil["name"]] if "{foil}" in template else []),
            "significance": func,
        })
    dossiers = [
        {"name": lead["name"], "role": "protagonist", "traits": lead["traits"],
         "want": "to hold on to what they have", "need": "to let it change them",
         "wound": "a loss they never named", "secret": "they caused more of it than they admit",
         "relationships": [{"who": foil["name"], "bond": "rival / mirror"}],
         "voice": "guarded, dry, more feeling than they show", "key_lines": []},
        {"name": foil["name"], "role": "antagonist", "traits": foil["traits"],
         "want": "to win on their own terms", "need": "to be seen",
         "wound": "was discarded once", "secret": "wants what the lead has",
         "relationships": [{"who": lead["name"], "bond": "rival / mirror"}],
         "voice": "sharp, performative, never quite honest", "key_lines": []},
    ]
    return _ensure_shape({
        "title": title,
        "premise": premise_text or f"A story about {theme or 'change'}.",
        "themes": [theme] if theme else ["transformation"],
        "tone": "grounded, building",
        "motifs": motifs,
        "timeline": timeline,
        "character_dossiers": dossiers,
        "world_facts": [],
        "setup_payoff_candidates": [
            {"setup": (motifs[0] if motifs else "an early promise"),
             "possible_payoff": "returns, transformed, at the climax"},
        ],
    }, title, theme, premise_text)


def _invent_cast(text):
    """Pick two workable names. Prefer an explicitly named character ("named/called X"); else the
    first plausible proper noun in the seed; else defaults."""
    import re
    text = text or ""
    # Strongest signal: "a keeper named Mara" / "called Vex".
    named = re.findall(r"\b(?:named|called)\s+([A-Z][a-z]{2,})", text)
    caps = [w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", text)
            if w not in _STOP_NAMES and w.lower() not in _COMMON]
    ordered = list(dict.fromkeys(named + caps))
    lead_name = ordered[0] if ordered else "Rowan"
    foil_name = next((c for c in ordered[1:] if c != lead_name), "Vex")
    return ({"name": lead_name, "traits": ["watchful", "stubborn", "loyal"]},
            {"name": foil_name, "traits": ["clever", "hungry", "wounded"]})


# Capitalized words that show up in procedural premises but are never character names.
_STOP_NAMES = {"Based", "Source", "Arcanum", "Untitled", "Story", "Adventure", "Project", "Seed",
               "Opening", "Premise", "Theme", "Title"}


def _motifs_from(text):
    """Cheap motif seeds from salient nouns in the premise (keeps the offline reel themed)."""
    import re
    words = [w.lower() for w in re.findall(r"\b[a-z]{4,}\b", (text or "").lower())]
    stop = _COMMON | {"about", "story", "which", "their", "there", "where", "while"}
    salient = [w for w in dict.fromkeys(words) if w not in stop][:3]
    return [f"{w} = what it costs" for w in salient] or ["the threshold = no way back"]


_COMMON = {"The", "A", "An", "He", "She", "They", "It", "This", "That", "When", "Then",
           "the", "and", "with", "from", "into", "they", "that", "this", "have", "been"}


# --------------------------------------------------------------------------- #
# Shape helpers
# --------------------------------------------------------------------------- #

def _is_valid(value):
    return isinstance(value, dict) and isinstance(value.get("timeline"), list) and value.get("timeline") \
        and isinstance(value.get("character_dossiers"), list) and value.get("character_dossiers")


def _ensure_shape(u, title, theme, premise_text):
    out = dict(u or {})
    out.setdefault("title", title)
    out["title"] = out.get("title") or title
    out.setdefault("premise", premise_text)
    out.setdefault("themes", [theme] if theme else [])
    out.setdefault("tone", "grounded")
    out.setdefault("motifs", [])
    out.setdefault("timeline", [])
    out.setdefault("character_dossiers", [])
    out.setdefault("world_facts", [])
    out.setdefault("setup_payoff_candidates", [])
    # Stamp order on the timeline if the model omitted it.
    for i, e in enumerate(out["timeline"]):
        if isinstance(e, dict):
            e.setdefault("order", i + 1)
    return out


def _tokens(profile, shape, default):
    if not profile:
        return default
    try:
        import studio_generation
        return studio_generation.max_tokens_for(profile, shape)
    except Exception:
        return default
