"""
Scriptwriter — the missing narrator. Writes the AUTHORED script for one scene.

Phase 3 of the Studio overhaul. The old back half made the model do layout math: it
sliced a story into 12 comic balloons and asked for "a short line per panel"
(`studio_workflow._apply_dialogue`). When no quote existed, "narration" was a truncated
stage direction (`sentence_safe_trim(shot.action, 160)`). No agent ever wrote the
flowing prose that gets read aloud and scrolled — which is exactly why narration lagged
behind the (structured, deterministic) image side.

The Scriptwriter fixes that. Given ONE scene from the Showrunner blueprint plus the
whole-story understanding and the character bibles, it writes a `narration_script` — a
sequence of beats that are real prose narration and in-voice dialogue, paced to the
scene's target read-aloud length. No balloon limits; the unit is a *scene*, not a box.

It pairs each scene with a single evocative image prompt by reusing the already-strong
deterministic `studio_visual` assembler at scene granularity (the Cinematographer role).

Decoupled and graceful like the other new agents: with no LLM it still composes a
faithful script from the scene's purpose, the story's real motifs/tone, and the
characters' real quoted lines.
"""

import logging

import studio_visual

logger = logging.getLogger("studio_scriptwriter")

SCRIPT_BEAT_KEYS = ["speaker", "line"]
_WORDS_PER_SECOND = 2.5


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #

def build_scenes(blueprint, understanding=None, world=None, characters=None,
                 llm_call=None, profile=None, progress=None, taste=""):
    """Turn a Showrunner blueprint into a list of fully-written cinematic scenes.

    Each output scene = {scene_number, id, title, location, image_prompt,
    negative_prompt, narration_script[], duration_seconds, setup_refs, status}.
    """
    blueprint = blueprint or {}
    scenes_in = blueprint.get("scenes") or []
    understanding = understanding or {}
    characters = characters or []
    by_name = studio_visual.index_characters(characters)
    # The setup→payoff registry lets a paying scene actually LAND its callback (§9.2b), and the
    # voice guide keeps each character sounding the same across scenes (§9.2d).
    setups = {s.get("id"): s for s in (blueprint.get("setups") or []) if s.get("id")}
    voice_guide = build_voice_guide(characters, understanding)

    out = []
    total = len(scenes_in)
    for i, scene in enumerate(scenes_in):
        if progress:
            try:
                progress(f"Writing scene {i + 1} of {total}: {scene.get('title', '')}")
            except Exception:
                pass
        out.append(write_scene(
            scene, i, understanding, world, characters, by_name,
            llm_call=llm_call, profile=profile, setups=setups, voice_guide=voice_guide, taste=taste,
        ))
    return out


def build_voice_guide(characters, understanding=None):
    """A stable per-character voice anchor (style + canonical sample lines), so a character
    sounds the same in scene 8 as in scene 1. Mirrors the visual_consistency_guide pattern."""
    guide = {}
    for ch in characters or []:
        if not isinstance(ch, dict) or not ch.get("name"):
            continue
        # Key lines can live in ch["key_lines"], ch["bible"]["key_lines"], or ch["metadata"]["bible"]["key_lines"]
        key_lines = (ch.get("key_lines") 
                     or (ch.get("bible") or {}).get("key_lines") 
                     or (ch.get("metadata") or {}).get("bible", {}).get("key_lines") 
                     or [])
        guide[str(ch["name"]).lower()] = {
            "name": ch["name"],
            "voice": ch.get("speech_style") or ch.get("voice") or "natural, in-character",
            "samples": [l for l in key_lines if l][:3],
        }
    # Backfill from dossiers for any character the bible step didn't expand.
    for d in (understanding or {}).get("character_dossiers", []):
        key = str(d.get("name", "")).lower()
        if key and key not in guide:
            guide[key] = {"name": d.get("name"), "voice": d.get("voice", "natural, in-character"),
                          "samples": [l for l in (d.get("key_lines") or []) if l][:3]}
    return guide


def write_scene(scene, index, understanding, world, characters, by_name=None,
                llm_call=None, profile=None, setups=None, voice_guide=None, taste=""):
    """Write one scene: its narration_script + image prompt + timing."""
    scene = scene or {}
    world = world or {}
    understanding = understanding or {}
    if by_name is None:
        by_name = studio_visual.index_characters(characters or [])
    if voice_guide is None:
        voice_guide = build_voice_guide(characters or [], understanding)
    setups = setups or {}

    script = _write_script(scene, understanding, world, characters or [], by_name,
                           llm_call, profile, setups, voice_guide, taste)
    script = _finalize_script(script)

    image_prompt, negative_prompt = _scene_image(scene, understanding, world, by_name)
    duration = sum(b.get("duration_seconds", 0) for b in script) or scene.get("target_seconds", 12)

    return {
        "scene_number": index + 1,
        "id": scene.get("id") or f"s{index + 1}",
        "title": scene.get("title") or f"Scene {index + 1}",
        "location": scene.get("location", ""),
        "characters": scene.get("characters", []),
        "emotional_shift": scene.get("emotional_shift", ""),
        "image_prompt": image_prompt,
        "negative_prompt": negative_prompt,
        "narration_script": script,
        "duration_seconds": duration,
        "setup_refs": list(scene.get("setup_seeds", [])) + list(scene.get("pays_off", [])),
        "status": "draft",
    }


# --------------------------------------------------------------------------- #
# Script writing (the narration author)
# --------------------------------------------------------------------------- #

def _resolve_payoffs(scene, setups):
    """For a scene's `pays_off` seed ids, pull the setup notes it must land (§9.2b)."""
    out = []
    for sid in scene.get("pays_off") or []:
        seed = (setups or {}).get(sid)
        if seed and seed.get("note"):
            out.append({"id": sid, "note": seed["note"]})
    return out


def _scene_voices(present, by_name, voice_guide):
    """Voice entries for the present cast, pulled from the stable cross-scene guide (§9.2d)."""
    voices = []
    for name in present:
        entry = (voice_guide or {}).get(str(name).lower())
        if entry:
            voices.append({"name": name, "voice": entry.get("voice", ""), "samples": entry.get("samples", [])})
        else:
            ch = by_name.get(str(name).lower())
            voices.append({"name": name,
                           "voice": (ch or {}).get("speech_style") or (ch or {}).get("voice") or "natural, in-character",
                           "samples": []})
    return voices


def _write_script(scene, understanding, world, characters, by_name, llm_call, profile,
                  setups=None, voice_guide=None, taste=""):
    present = scene.get("characters") or []
    voices = _scene_voices(present, by_name, voice_guide)
    payoffs = _resolve_payoffs(scene, setups)

    def fallback():
        return _deterministic_script(scene, understanding, present, by_name, payoffs)

    if not callable(llm_call):
        return fallback()

    import json
    target_seconds = scene.get("target_seconds", 12)
    target_words = int(target_seconds * _WORDS_PER_SECOND)
    payoff_clause = (
        " THIS SCENE PAYS OFF a planted setup — you MUST call it back and land it with weight "
        "(echo the planted detail so the audience feels the connection)."
        if payoffs else ""
    )
    system_prompt = (
        "You are the Scriptwriter. Write the spoken script for ONE scene of a cinematic reel: "
        "evocative narration and in-character dialogue that will be read aloud by TTS while it "
        "scrolls over a single background image. This is NOT a comic — do not write tiny balloon "
        "lines. Write flowing, atmospheric prose narration interleaved with real dialogue, paced "
        f"to about {target_words} words ({target_seconds}s). Stay faithful to the scene's purpose "
        "and the story's tone/motifs; honor the emotional shift; serve the scene's dramatic "
        "FUNCTION in the arc. Voice each character EXACTLY per their guide (style + sample lines) "
        "so they sound identical across scenes." + payoff_clause +
        " Output ONLY a JSON list of beats in order: "
        '[{"speaker": "Narrator" or a character name, "line": "the spoken text", '
        '"emotion": "one word", "delivery": "short performance note"}]'
    ) + (taste or "")
    prompt = json.dumps({
        "scene": {
            "title": scene.get("title", ""),
            "function": scene.get("function", ""),
            "purpose": scene.get("purpose", ""),
            "location": scene.get("location", ""),
            "emotional_shift": scene.get("emotional_shift", ""),
            "setup_seeds": scene.get("setup_seeds", []),
        },
        "must_pay_off": payoffs,
        "tone": understanding.get("tone", ""),
        "motifs": understanding.get("motifs", []),
        "character_voices": voices,
        "world_setting": world.get("setting", ""),
    }, ensure_ascii=False)
    max_tokens = _tokens(profile, "large", 1500)

    result = llm_call(prompt, system_prompt, fallback, max_tokens)
    if not _is_valid_script(result):
        return fallback()
    return result


def _deterministic_script(scene, understanding, present, by_name, payoffs=None):
    """Compose a faithful script with no LLM: narration from the scene's purpose + the
    story's tone, plus each present character's real quoted line where we have one, and an
    explicit callback beat when this scene must pay off a planted setup (§9.2b)."""
    beats = []
    purpose = (scene.get("purpose") or "").strip()
    tone = understanding.get("tone", "")
    # `emotional_shift` is director shorthand ("the turn", "calm to unease") — it shapes the
    # delivery, it is NOT spoken. The narration is the scene's actual substance.
    delivery = scene.get("emotional_shift") or "even"

    for sentence in _sentences(purpose)[:4]:
        beats.append({"speaker": "Narrator", "line": sentence,
                      "emotion": tone or "neutral", "delivery": delivery})

    # One real, in-voice line per present character (from their dossier key_lines).
    for name in present:
        ch = by_name.get(str(name).lower())
        line = _first_key_line(ch)
        if line:
            beats.append({"speaker": name, "line": line, "emotion": "in-character",
                          "delivery": (ch or {}).get("speech_style", "")[:60]})

    # Land any planted setup this scene is responsible for paying off, so the callback text
    # actually EXISTS (continuity can then verify it echoed the setup).
    for p in payoffs or []:
        note = str(p.get("note") or "").strip()
        if note:
            beats.append({"speaker": "Narrator",
                          "line": _cap(f"And there it was again — {note}. It had come back around."),
                          "emotion": "resonant", "delivery": "callback, let it land"})

    if not beats:
        beats.append({"speaker": "Narrator",
                      "line": _cap((scene.get("title") or "The scene") + " unfolds."),
                      "emotion": "neutral", "delivery": "even"})
    return beats


# --------------------------------------------------------------------------- #
# Cinematographer (reuse studio_visual at scene scale)
# --------------------------------------------------------------------------- #

def _scene_image(scene, understanding, world, by_name):
    """One evocative image prompt per scene, via the deterministic studio_visual assembler."""
    motif = ""
    motifs = understanding.get("motifs") or []
    if motifs:
        motif = str(motifs[0]).split("=")[0].strip()
    # Prefer the richer purpose; only add the title when it isn't already its prefix
    # (the deterministic title is the first few words of the purpose, so avoid echoing it).
    title = (scene.get("title") or "").strip()
    purpose = (scene.get("purpose") or "").strip()
    subject_bits = []
    if title and not purpose.lower().startswith(title.lower()):
        subject_bits.append(title)
    subject_bits.append(purpose or title)
    if scene.get("emotional_shift"):
        subject_bits.append(scene["emotional_shift"])
    visual_description = ". ".join(b for b in subject_bits if b)[:240]

    panel_like = {
        "visual_description": visual_description,
        "visible_characters": scene.get("characters", []),
        "location_ref": scene.get("location", ""),
        "camera": "cinematic wide establishing shot",
        "composition": "single evocative frame, atmospheric depth",
        "continuity_state": {"mood": scene.get("emotional_shift", ""), "props": motif},
    }
    return studio_visual.build_image_prompt(panel_like, world, by_name)


# --------------------------------------------------------------------------- #
# Finalize / timing
# --------------------------------------------------------------------------- #

def _finalize_script(script):
    out = []
    for beat in script or []:
        if not isinstance(beat, dict):
            continue
        line = str(beat.get("line") or "").strip()
        if not line:
            continue
        out.append({
            "speaker": str(beat.get("speaker") or "Narrator").strip() or "Narrator",
            "line": line,
            "emotion": str(beat.get("emotion") or "neutral").strip(),
            "delivery": str(beat.get("delivery") or "").strip(),
            "duration_seconds": _line_duration(line),
        })
    if not out:
        out.append({"speaker": "Narrator", "line": "The scene unfolds in silence.",
                    "emotion": "neutral", "delivery": "", "duration_seconds": 3})
    return out


def _line_duration(text):
    words = len((text or "").split())
    return max(2, min(20, round(words / _WORDS_PER_SECOND)))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _is_valid_script(value):
    return isinstance(value, list) and any(
        isinstance(b, dict) and str(b.get("line") or "").strip() for b in value
    )


def _sentences(text):
    import re
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _first_key_line(ch):
    if not isinstance(ch, dict):
        return ""
    sources = (
        ch.get("key_lines"),
        (ch.get("bible") or {}).get("key_lines"),
        (ch.get("metadata") or {}).get("bible", {}).get("key_lines")
    )
    for src in sources:
        if isinstance(src, list) and src:
            for line in src:
                if str(line or "").strip():
                    return str(line).strip()
    return ""


def _cap(text):
    text = str(text or "").strip()
    return text[:1].upper() + text[1:] if text else text


def _tokens(profile, shape, default):
    if not profile:
        return default
    try:
        import studio_generation
        return studio_generation.max_tokens_for(profile, shape)
    except Exception:
        return default
