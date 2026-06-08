"""
Showrunner — the Director that turns whole-story understanding into a SCENE BLUEPRINT.

Phase 2 of the Studio overhaul. The old planner forced every story into exactly three
beats / twelve panels / sixty seconds (`studio_workflow.run_story_planning`), which
crushed a slow-burn novella into a shape it could never breathe in. The Showrunner
replaces that with a *dynamic* blueprint:

  - It decides HOW MANY scenes the story needs (≈ one per major timeline event, clamped
    to a sane range scaled by the model tier) instead of a hardcoded 3/12.
  - It emits a per-scene plan — location, characters present, narrative purpose, the
    emotional shift, and a target read-aloud length — that the Scriptwriter and
    Cinematographer consume one scene at a time.
  - It tracks setup→payoff as first-class objects, so a seed planted in scene 1 can be
    deliberately paid off in scene N (the "you sacrificed your footing" callback that is
    mechanically impossible when the data model is just {name, summary}).

The blueprint is the hard USER GATE: the orchestrator pauses here so the user can edit
the scene list before any expensive script/image generation runs.

Like the Loremaster, this module is decoupled and degrades gracefully: with no LLM it
builds a faithful blueprint deterministically from the timeline + setup/payoff candidates.
"""

import logging

logger = logging.getLogger("studio_showrunner")

# Per-tier ceilings on scene count. A bigger model can sustain a longer reel coherently.
_SCENE_CAP = {"small": 6, "medium": 9, "large": 12}
_SCENE_FLOOR = 4

# Keys a scene object always carries.
SCENE_KEYS = ["id", "title", "function", "location", "characters", "purpose",
              "emotional_shift", "significance", "target_seconds", "setup_seeds", "pays_off"]

# Canonical dramatic arc (a three-act / hero's-journey hybrid). Each scene is mapped to the
# nearest beat by its normalized position, so the reel has a SHAPE (setup → turn → climax →
# release) instead of evenly-sliced summary. (function, felt-tone) — the tone seeds the
# emotional contour and the scene's default delivery.
_FUNCTION_ARC = [
    (0.00, "ordinary world", "calm, grounded"),
    (0.12, "inciting incident", "disruption"),
    (0.30, "rising action", "mounting tension"),
    (0.50, "midpoint turn", "reversal"),
    (0.68, "raising the stakes", "pressure"),
    (0.80, "dark night", "despair"),
    (0.92, "climax", "explosive release"),
    (1.00, "resolution", "quiet aftermath"),
]


def assign_functions(n):
    """Map n scenes onto the canonical arc by position, returning [(function, tone)] in order.

    For a 1-scene reel you get the climax; for 2 you get setup+resolution; for >=4 you get a
    full arc. This is what turns "N chunks" into "a story with a shape."
    """
    if n <= 0:
        return []
    if n == 1:
        return [(_FUNCTION_ARC[6][1], _FUNCTION_ARC[6][2])]  # a single scene is its climax
    last = len(_FUNCTION_ARC) - 1
    out = []
    for i in range(n):
        # Index-based mapping (not nearest-value) so beats are walked in order without being
        # skipped: at n == len(arc) every beat appears exactly once, climax included.
        bi = round(i / (n - 1) * last)
        func, tone = _FUNCTION_ARC[bi][1], _FUNCTION_ARC[bi][2]
        out.append((func, tone))
    return out


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def decide_scene_count(understanding, profile=None):
    """Pick a scene count from the real story size, clamped + tier-scaled. No hardcoded 3."""
    timeline = (understanding or {}).get("timeline") or []
    n_events = len(timeline)
    tier = (profile or {}).get("tier", "small")
    cap = _SCENE_CAP.get(tier, _SCENE_CAP["small"])
    if n_events <= 0:
        return _SCENE_FLOOR
    return max(_SCENE_FLOOR, min(cap, n_events))


def build_blueprint(understanding, world=None, characters=None, llm_call=None,
                    profile=None, progress=None, taste=""):
    """Return a scene-blueprint dict (see module docstring / bible §3.2).

    Args mirror the Loremaster: ``llm_call`` is the optional
    ``runner._call_llm_with_fallback``-shaped callable; with ``None`` the blueprint is
    built deterministically from the understanding. ``taste`` is the learned user-taste
    clause (§9.4) appended to the system prompt.
    """
    understanding = understanding or {}
    target = decide_scene_count(understanding, profile)

    def _note(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    _note(f"Breaking the story into {target} scenes...")

    if not callable(llm_call):
        return _deterministic_blueprint(understanding, target)

    blueprint = _llm_blueprint(understanding, world, characters, target, llm_call, profile, taste)
    if not _is_valid_blueprint(blueprint):
        return _deterministic_blueprint(understanding, target)
    return normalize_blueprint(blueprint, understanding, target)


# --------------------------------------------------------------------------- #
# LLM path
# --------------------------------------------------------------------------- #

def _llm_blueprint(understanding, world, characters, target, llm_call, profile, taste=""):
    import json

    dossiers = understanding.get("character_dossiers") or []
    cast = [{"name": d.get("name", ""), "want": d.get("want", ""), "role": d.get("role", "")}
            for d in dossiers if d.get("name")]
    compact = {
        "premise": understanding.get("premise", ""),
        "themes": understanding.get("themes", []),
        "tone": understanding.get("tone", ""),
        "motifs": understanding.get("motifs", []),
        "timeline": [
            {"order": e.get("order"), "event": e.get("event", ""), "location": e.get("location", ""),
             "significance": e.get("significance", "")}
            for e in (understanding.get("timeline") or [])
        ][:40],
        "cast": cast,
        "setup_payoff_candidates": understanding.get("setup_payoff_candidates", []),
        "locations": [l.get("name", "") for l in (world or {}).get("locations", []) if l.get("name")],
    }
    system_prompt = (
        "You are the Showrunner (the director). Turn the whole-story understanding below into a "
        f"scene-by-scene blueprint of about {target} scenes — let the story's real arc decide the "
        "exact number; do NOT force a fixed count. Each scene is one continuous moment the audience "
        "experiences as a single image with narrated text scrolling over it.\n"
        "SHAPE THE REEL like a film, not a summary: give it a dramatic arc (ordinary world → "
        "inciting incident → rising action → midpoint turn → raising stakes → dark night → climax → "
        "resolution). WEIGHT BY SIGNIFICANCE: a pivotal beat earns its own scene; slow stretches "
        "compress. Tag each scene's `function` in that arc. PLANT setups early and PAY THEM OFF later "
        "with weight (track them in `setups` and mark the paying scene's `pays_off`). Be faithful to "
        "the timeline; never invent events that contradict it. Also return `emotional_arc`: the "
        "ordered felt-tone of the whole reel so it builds and releases. Output ONLY a JSON object: "
        '{"summary": "one-paragraph spine", "scenes": [{"id": "s1", "title": "", '
        '"function": "ordinary world|inciting incident|rising action|midpoint turn|raising stakes|'
        'dark night|climax|resolution", "location": "", "characters": ["Name"], '
        '"purpose": "what this scene accomplishes", "emotional_shift": "from X to Y", '
        '"target_seconds": 12, "setup_seeds": ["something planted here"], '
        '"pays_off": ["a seed id planted earlier"]}], '
        '"setups": [{"id": "seed-1", "planted_in": "s1", "paid_off_in": "s8", "note": "what it is"}], '
        '"emotional_arc": [{"scene_id": "s1", "function": "", "tone": ""}]}'
    ) + (taste or "")
    prompt = "Whole-story understanding:\n" + json.dumps(compact, ensure_ascii=False)
    max_tokens = _tokens(profile, "large", 1800)

    def fallback():
        return _deterministic_blueprint(understanding, target)

    return llm_call(prompt, system_prompt, fallback, max_tokens)


# --------------------------------------------------------------------------- #
# Deterministic path
# --------------------------------------------------------------------------- #

def _deterministic_blueprint(understanding, target):
    """Build a faithful blueprint with zero LLM: bucket the timeline into `target` scenes."""
    timeline = understanding.get("timeline") or []
    buckets = _bucket_events(timeline, target)
    dossiers = understanding.get("character_dossiers") or []
    char_names = [d.get("name") for d in dossiers if d.get("name")]
    motifs = understanding.get("motifs") or []
    candidates = understanding.get("setup_payoff_candidates") or []
    functions = assign_functions(len(buckets))

    scenes = []
    for i, bucket in enumerate(buckets):
        events = bucket or []
        chars = _dedupe([c for e in events for c in (e.get("characters") or [])])
        location = _most_common([e.get("location") for e in events if e.get("location")])
        purpose = " ".join(e.get("event", "") for e in events).strip() or \
            (understanding.get("premise", "") if i == 0 else "")
        func, tone = functions[i] if i < len(functions) else ("carry the throughline", "steady")
        # A scene built from a high-significance event is the reel's weight; keep it noted.
        significance = _most_common([e.get("significance") for e in events if e.get("significance")])
        title = _title_for(events, i)

        if not chars:
            scan_text = (title + " " + purpose).lower()
            for name in char_names:
                name_lower = name.lower()
                last_name = name_lower.split()[-1] if name_lower.split() else name_lower
                if name_lower in scan_text or last_name in scan_text:
                    chars.append(name)
            chars = _dedupe(chars)

        scenes.append({
            "id": f"s{i + 1}",
            "title": title,
            "function": func,
            "location": location,
            "characters": chars,
            "purpose": _trim(purpose, 280),
            "emotional_shift": tone,
            "significance": significance,
            "target_seconds": 12,
            "setup_seeds": [],
            "pays_off": [],
        })

    # Place setup→payoff candidates: plant in the first third, pay off in the last third.
    setups = []
    if scenes:
        plant_idx = 0
        payoff_idx = len(scenes) - 1
        for j, cand in enumerate(candidates[:4]):
            note = cand.get("setup") if isinstance(cand, dict) else str(cand)
            if not note:
                continue
            sid = f"seed-{j + 1}"
            p_in = scenes[min(plant_idx + j, max(0, len(scenes) // 3))]["id"]
            p_off = scenes[payoff_idx]["id"]
            setups.append({"id": sid, "planted_in": p_in, "paid_off_in": p_off, "note": _trim(note, 160)})
            # Reflect onto the scenes themselves.
            for s in scenes:
                if s["id"] == p_in:
                    s["setup_seeds"].append(note)
                if s["id"] == p_off:
                    s["pays_off"].append(sid)
        # If no explicit candidates, let the dominant motif be the through-line seed.
        if not setups and motifs:
            scenes[0]["setup_seeds"].append(motifs[0])
            setups.append({"id": "seed-motif", "planted_in": scenes[0]["id"],
                           "paid_off_in": scenes[-1]["id"], "note": motifs[0]})

    summary = understanding.get("premise", "") or (scenes[0]["purpose"] if scenes else "")
    return {
        "summary": _trim(summary, 320),
        "scene_count": len(scenes),
        "scenes": scenes,
        "setups": setups,
        "emotional_arc": _emotional_arc(scenes),
    }


def _emotional_arc(scenes):
    """The reel's overall shape: ordered (scene id, dramatic function, felt tone). Downstream
    stages (Scriptwriter delivery, sound) read this so the whole reel builds and releases."""
    return [{"scene_id": s.get("id"), "function": s.get("function", ""),
             "tone": s.get("emotional_shift", "")} for s in scenes]


def _bucket_events(timeline, target):
    """Distribute timeline events across `target` ordered buckets, WEIGHTED by significance so a
    pivotal beat tends to claim its own scene instead of being averaged in with filler.

    Chronology is always preserved (buckets are contiguous). A flagged-significant event carries
    more weight, so the cumulative split lands a boundary around it. Empty buckets are repaired by
    stealing from the heaviest neighbor, guaranteeing exactly `target` non-empty buckets when n>=target.
    """
    if target <= 0:
        return []
    if not timeline:
        return [[] for _ in range(target)]
    n = len(timeline)
    if n <= target:
        # One event per scene; trailing scenes get an empty bucket (Scriptwriter pads).
        return [[timeline[i]] if i < n else [] for i in range(target)]

    weights = [2.0 if str(e.get("significance") or "").strip() else 1.0 for e in timeline]
    total = sum(weights)
    buckets = [[] for _ in range(target)]
    cum = 0.0
    for event, w in zip(timeline, weights):
        # Place by the midpoint of this event's weight span, so a heavy event occupies a bucket
        # rather than straddling a boundary.
        bi = min(target - 1, int((cum + w / 2.0) / total * target))
        buckets[bi].append(event)
        cum += w

    # Repair empties (a heavy event can skip a bucket): pull one event from the fullest neighbor.
    for i in range(target):
        if buckets[i]:
            continue
        donor = max(range(target), key=lambda j: len(buckets[j]) if j != i else -1)
        if len(buckets[donor]) > 1:
            if donor < i:
                buckets[i].insert(0, buckets[donor].pop())  # keep chronology
            else:
                buckets[i].append(buckets[donor].pop(0))
    return buckets


# --------------------------------------------------------------------------- #
# Normalization / validation
# --------------------------------------------------------------------------- #

def normalize_blueprint(blueprint, understanding=None, target=None):
    """Coerce an (LLM) blueprint into the guaranteed shape with stable ids."""
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    raw_scenes = blueprint.get("scenes") if isinstance(blueprint.get("scenes"), list) else []
    scenes = []
    for i, sc in enumerate(raw_scenes):
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("id") or f"s{i + 1}").strip() or f"s{i + 1}"
        default_func, default_tone = (assign_functions(len(raw_scenes))[i]
                                      if i < len(raw_scenes) else ("", ""))
        scenes.append({
            "id": sid,
            "title": str(sc.get("title") or f"Scene {i + 1}").strip(),
            "function": str(sc.get("function") or default_func).strip(),
            "location": str(sc.get("location") or "").strip(),
            "characters": [str(c).strip() for c in (sc.get("characters") or []) if str(c).strip()],
            "purpose": _trim(str(sc.get("purpose") or ""), 280),
            "emotional_shift": str(sc.get("emotional_shift") or default_tone).strip(),
            "significance": str(sc.get("significance") or "").strip(),
            "target_seconds": _as_int(sc.get("target_seconds"), 12),
            "setup_seeds": [str(s).strip() for s in (sc.get("setup_seeds") or []) if str(s).strip()],
            "pays_off": [str(p).strip() for p in (sc.get("pays_off") or []) if str(p).strip()],
        })
    if not scenes and understanding is not None:
        return _deterministic_blueprint(understanding, target or decide_scene_count(understanding))

    setups = []
    for s in (blueprint.get("setups") or []):
        if isinstance(s, dict) and s.get("id"):
            setups.append({
                "id": str(s["id"]).strip(),
                "planted_in": str(s.get("planted_in") or "").strip(),
                "paid_off_in": str(s.get("paid_off_in") or "").strip(),
                "note": _trim(str(s.get("note") or ""), 160),
            })
    arc = blueprint.get("emotional_arc")
    if not isinstance(arc, list) or not arc:
        arc = _emotional_arc(scenes)
    return {
        "summary": _trim(str(blueprint.get("summary") or ""), 320),
        "scene_count": len(scenes),
        "scenes": scenes,
        "setups": setups,
        "emotional_arc": arc,
    }


def _is_valid_blueprint(value):
    if not isinstance(value, dict):
        return False
    scenes = value.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return False
    return any(isinstance(s, dict) and str(s.get("purpose") or s.get("title") or "").strip()
               for s in scenes)


def gate_blueprint(blueprint):
    """The setup/payoff gate (the cinematic 'gate' stage between Showrunner and Scriptwriter).

    Inspect a finished blueprint and return a list of human-readable problems. An empty list
    means it is sound enough to commit to scriptwriting; a non-empty list routes the Producer to
    the repair flow instead of writing scripts onto a broken story spine. Deterministic and cheap
    — no model call. The deterministic blueprint builder always passes; this exists to catch a
    malformed LLM blueprint (no usable scenes, or a setup that pays off in a scene that doesn't
    exist) before any tokens are spent on scriptwriting.
    """
    if not _is_valid_blueprint(blueprint):
        return ["The Showrunner produced no usable scenes — there is nothing to script."]
    scenes = blueprint.get("scenes") or []
    scene_ids = {str(s.get("id")) for s in scenes if isinstance(s, dict) and s.get("id")}
    problems = []
    for s in blueprint.get("setups") or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("id") or "setup"
        planted, paid = str(s.get("planted_in") or ""), str(s.get("paid_off_in") or "")
        if planted and planted not in scene_ids:
            problems.append(f"Setup '{sid}' is planted in a scene that doesn't exist ('{planted}').")
        if paid and paid not in scene_ids:
            problems.append(f"Setup '{sid}' never pays off — '{paid}' is not a real scene.")
    return problems


def blueprint_to_storyboard(blueprint):
    """Map a scene blueprint onto the legacy {summary, episodes, canon_events} storyboard
    shape so the existing storyboard editor / approval gate keeps working unchanged."""
    blueprint = blueprint or {}
    scenes = blueprint.get("scenes") or []
    episodes = [{"name": s.get("title") or f"Scene {i + 1}", "summary": s.get("purpose") or ""}
                for i, s in enumerate(scenes)]
    canon_events = [{"description": s.get("purpose") or s.get("title") or "",
                     "time_index": f"scene {i + 1}"} for i, s in enumerate(scenes)]
    return {
        "summary": blueprint.get("summary", ""),
        "episodes": episodes,
        "canon_events": canon_events,
        # Carry the rich blueprint alongside so scene-aware consumers can use it.
        "scene_blueprint": blueprint,
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _title_for(events, index):
    if events:
        first = (events[0].get("event") or "").strip()
        if first:
            words = first.split()
            return " ".join(words[:6]).rstrip(".,;:") or f"Scene {index + 1}"
    return f"Scene {index + 1}"


def _dedupe(items):
    out, seen = [], set()
    for x in items or []:
        k = str(x).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(str(x).strip())
    return out


def _most_common(items):
    items = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not items:
        return ""
    from collections import Counter
    return Counter(items).most_common(1)[0][0]


def _trim(text, n):
    text = str(text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(".,;: ") + "…"


def _as_int(value, default):
    try:
        return max(3, min(30, int(value)))
    except (TypeError, ValueError):
        return default


def _tokens(profile, shape, default):
    if not profile:
        return default
    try:
        import studio_generation
        return studio_generation.max_tokens_for(profile, shape)
    except Exception:
        return default
