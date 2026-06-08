"""
Scene continuity audit — protects the craft (gpt §5 / §9.2b).

The Showrunner plants setups and the Scriptwriter is *told* to pay them off; this module is the
check that they actually did. It audits the scene spine (not the legacy panels) and emits
user-readable warnings with a concrete repair target, so a planted callback that never lands —
the failure mode that makes a story feel hollow — gets caught and routed back to scene-level
regeneration.

Deterministic and cheap (string/token echo, roster checks, length checks) so it always runs,
even with no LLM. Returns a list of warnings:

    {"target_type": "scene", "scene_id": "s8", "severity": "high|medium|low",
     "message": "...", "suggestion": "...", "repair_target": "script|image|all"}
"""

import re

_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "from",
    "that", "this", "it", "is", "was", "be", "as", "by", "his", "her", "their", "they", "he",
    "she", "you", "your", "what", "when", "then", "had", "has", "have", "into", "out", "back",
    "again", "came", "around", "there", "here", "its", "one", "all", "not", "no", "so", "up",
}


def _tokens(text):
    return [w for w in re.findall(r"[a-z']{3,}", (text or "").lower()) if w not in _STOP]


def _content_words(text):
    """Salient content tokens (deduped, length>3) used for echo matching."""
    return [w for w in dict.fromkeys(_tokens(text)) if len(w) > 3]


def _scene_text(scene):
    return " ".join(b.get("line", "") for b in (scene.get("narration_script") or []))


def audit_scenes(scenes, blueprint=None, voice_guide=None, understanding=None):
    """Run all deterministic continuity checks and return a flat list of warnings."""
    scenes = scenes or []
    blueprint = blueprint or {}
    by_id = {s.get("id"): s for s in scenes}
    warnings = []

    warnings += _check_setups_land(scenes, by_id, blueprint)
    warnings += _check_roster(scenes)
    warnings += _check_length(scenes)
    warnings += _check_emotional_arc(scenes, blueprint)
    return warnings


# --------------------------------------------------------------------------- #
# §9.2b — every planted setup must actually be echoed in its payoff scene
# --------------------------------------------------------------------------- #

def _check_setups_land(scenes, by_id, blueprint):
    out = []
    setups = blueprint.get("setups") or []
    for seed in setups:
        note = (seed.get("note") or "").strip()
        payoff_id = seed.get("paid_off_in")
        if not note or not payoff_id:
            continue
        payoff = by_id.get(payoff_id)
        if not payoff:
            out.append({
                "target_type": "scene", "scene_id": payoff_id, "severity": "medium",
                "message": f"Setup '{note}' names a payoff scene '{payoff_id}' that doesn't exist.",
                "suggestion": "Re-run the Showrunner blueprint or repoint the setup.",
                "repair_target": "all",
            })
            continue
        cues = _content_words(note)
        text_tokens = set(_content_words(_scene_text(payoff)))
        landed = any(c in text_tokens for c in cues)
        if not landed:
            out.append({
                "target_type": "scene", "scene_id": payoff_id, "severity": "high",
                "message": f"Planted setup '{note}' is never paid off — scene {payoff_id} doesn't "
                           f"call it back.",
                "suggestion": f"Refine scene {payoff_id}: land the callback to '{note}' with weight.",
                "repair_target": "script",
            })
    # Dangling seeds: a scene plants something the blueprint never schedules a payoff for.
    scheduled = {(s.get("note") or "").strip().lower() for s in setups}
    for sc in scenes:
        for seed in sc.get("setup_seeds") or []:
            if str(seed).strip().lower() not in scheduled:
                out.append({
                    "target_type": "scene", "scene_id": sc.get("id"), "severity": "low",
                    "message": f"Scene {sc.get('id')} plants '{seed}' but nothing pays it off.",
                    "suggestion": "Either pay it off in a later scene or drop it as intentional texture.",
                    "repair_target": "script",
                })
    return out


# --------------------------------------------------------------------------- #
# Roster: a character should not speak in a scene they're not in
# --------------------------------------------------------------------------- #

def _check_roster(scenes):
    out = []
    for sc in scenes:
        present = {str(c).strip().lower() for c in (sc.get("characters") or [])}
        for beat in sc.get("narration_script") or []:
            speaker = str(beat.get("speaker") or "").strip()
            if not speaker or speaker.lower() == "narrator":
                continue
            if present and speaker.lower() not in present:
                out.append({
                    "target_type": "scene", "scene_id": sc.get("id"), "severity": "medium",
                    "message": f"{speaker} speaks in scene {sc.get('id')} but isn't listed as present.",
                    "suggestion": f"Add {speaker} to the scene's cast or reassign the line.",
                    "repair_target": "script",
                })
                break  # one per scene is enough signal
    return out


# --------------------------------------------------------------------------- #
# Length: a scene far under its target reads as thin
# --------------------------------------------------------------------------- #

def _check_length(scenes):
    out = []
    for sc in scenes:
        target = sc.get("target_seconds", 12) or 12
        dur = sc.get("duration_seconds", 0) or 0
        if dur and dur < max(4, target * 0.4):
            out.append({
                "target_type": "scene", "scene_id": sc.get("id"), "severity": "low",
                "message": f"Scene {sc.get('id')} is short ({dur}s vs ~{target}s target) — it may feel thin.",
                "suggestion": "Refine the scene to give the moment room to breathe.",
                "repair_target": "script",
            })
    return out


# --------------------------------------------------------------------------- #
# Emotional arc: the climax shouldn't sit at the very start
# --------------------------------------------------------------------------- #

def _check_emotional_arc(scenes, blueprint):
    funcs = [(s.get("id"), (s.get("function") or "").lower()) for s in scenes]
    n = len(funcs)
    if n < 4:
        return []
    for pos, (sid, func) in enumerate(funcs):
        if func == "climax" and pos < n * 0.4:
            return [{
                "target_type": "scene", "scene_id": sid, "severity": "low",
                "message": f"The climax ({sid}) lands early (scene {pos + 1} of {n}); the build may feel rushed.",
                "suggestion": "Reorder the blueprint so the climax sits in the final third.",
                "repair_target": "all",
            }]
    return []
