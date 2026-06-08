"""
Visual Prompt Compiler (MEDIA_DISPATCHER §4) — structured spec -> generation-ready PromptPacket.

The rule that keeps image generation sane: **the LLM decides WHAT is seen; deterministic code
decides HOW to ask the model.** The agent emits a structured visual spec (shot, action, mood,
continuity locks); this compiler turns it into a reproducible `PromptPacket` (positive/negative
text + model + steps/cfg/seed/sampler/scheduler) by drawing on three project bibles:

    style_bible        — the project's visual identity (palette, line style, camera, avoid[])
    character_visuals  — per character: base look, body, outfit, palette, negative locks
    location_visuals   — per location: visual identity, mood, recurring props

It is deliberately dumb and deterministic: same spec + bibles -> same packet, which is what makes
panels reproducible, re-rolls meaningful, and characters consistent. It builds on the existing
`studio_visual` assembler (shared base negatives) rather than replacing it.

Bibles are derived from the data the studio already holds (world + character bibles), so nothing
new has to be authored to get a working compile; richer hand-authored bibles simply improve it.
"""

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

import studio_visual

# House defaults for a 16 GB SDXL-class anime/comic workflow (overridable per project/model).
DEFAULT_MODEL_PROFILE = {
    "model": "sdxl_anime_default",
    "width": 768,
    "height": 768,
    "steps": 24,
    "cfg": 6.5,
    "sampler": "dpmpp_2m",
    "scheduler": "karras",
    "seed": -1,            # -1 => derive a stable per-scene seed (reproducible re-rolls)
}


@dataclass
class PromptPacket:
    positive_prompt: str
    negative_prompt: str
    model: str
    width: int
    height: int
    steps: int
    cfg: float
    seed: int
    sampler: str
    scheduler: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean(v) -> str:
    return str(v or "").strip().strip(".,;").strip()


def join_clean(parts: List[str]) -> str:
    out, seen = [], set()
    for p in parts:
        p = _clean(p)
        k = p.lower()
        if p and k not in seen:
            seen.add(k)
            out.append(p)
    return ", ".join(out)


# --------------------------------------------------------------------------- #
# Bible builders — derive the three bibles from existing world/character data
# --------------------------------------------------------------------------- #

def build_style_bible(world: Dict[str, Any]) -> Dict[str, Any]:
    world = world or {}
    return {
        "project_style": _clean(world.get("medium")) or "cinematic comic panel, clean line art, cel shading",
        "palette": _clean(world.get("palette")) or _clean(world.get("aesthetic")),
        "line_style": _clean(world.get("line_style")) or "clean line art, high detail",
        "camera_language": _clean(world.get("camera_language")),
        "lighting_rules": _clean(world.get("lighting")),
        "materials": _clean(world.get("materials")),
        "avoid": list(world.get("avoid") or []),
    }


def build_character_visuals(characters: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for ch in characters or []:
        if not isinstance(ch, dict) or not ch.get("name"):
            continue
        visual = ch.get("visual")
        if not isinstance(visual, dict):
            meta = ch.get("metadata") if isinstance(ch.get("metadata"), dict) else {}
            visual = meta.get("visual") if isinstance(meta.get("visual"), dict) else {}
        out[str(ch["name"]).lower()] = {
            "name": ch["name"],
            "base_description": join_clean([visual.get("face"), visual.get("hair")]),
            "body": _clean(visual.get("build")),
            "outfit": _clean(visual.get("outfit")),
            "palette": _clean(visual.get("palette")),
            "negative_locks": list(ch.get("negative_locks") or visual.get("negative_locks") or []),
        }
    return out


def build_location_visuals(world: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for loc in (world or {}).get("locations") or []:
        if not isinstance(loc, dict) or not loc.get("name"):
            continue
        out[str(loc["name"]).lower()] = {
            "name": loc["name"],
            "visual_identity": _clean(loc.get("visual_prompt")) or _clean(loc.get("visual_identity")),
            "mood": _clean(loc.get("mood")),
            "recurring_props": list(loc.get("recurring_props") or []),
        }
    return out


# --------------------------------------------------------------------------- #
# Seed (reproducible re-rolls + character consistency)
# --------------------------------------------------------------------------- #

def stable_seed(scene_id: str, character_names: List[str], reroll_count: int = 0) -> int:
    """A deterministic seed from the scene id + its cast, so the same scene re-renders the same
    base composition and characters keep their identity across re-rolls. Bumping the reroll count
    changes the seed."""
    key = f"{scene_id}|{reroll_count}|{'|'.join(sorted(str(c).lower() for c in (character_names or [])))}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------- #
# Compile
# --------------------------------------------------------------------------- #

def compile_visual_prompt(scene, style_bible=None, character_visuals=None,
                          location_visuals=None, model_profile=None) -> PromptPacket:
    """Compile one scene's visual spec into a PromptPacket. ``scene`` is a cinematic scene dict
    (id, title, location, characters, purpose, emotional_shift, optional shot/camera/lighting)."""
    scene = scene or {}
    style_bible = style_bible or {}
    character_visuals = character_visuals or {}
    location_visuals = location_visuals or {}
    profile = {**DEFAULT_MODEL_PROFILE, **(model_profile or {})}

    present = scene.get("characters") or scene.get("visible_characters") or []
    loc_name = _clean(scene.get("location") or scene.get("location_ref"))
    loc = location_visuals.get(loc_name.lower(), {})

    # Character descriptors — the key to cross-panel consistency.
    char_bits, char_negatives = [], []
    for name in present:
        name_str = name.get("name") if isinstance(name, dict) else name
        c = character_visuals.get(str(name_str).lower())
        if not c:
            continue
        desc = join_clean([c["name"], c["base_description"], c["body"], c["outfit"], c["palette"]])
        if desc:
            char_bits.append(desc)
        for lock in c.get("negative_locks", []):
            char_negatives.append(_clean(lock))
        char_negatives.append(f"{c['name']} wrong outfit")

    positive = join_clean([
        style_bible.get("project_style", ""),
        scene.get("shot_type", ""),
        scene.get("camera", "") or style_bible.get("camera_language", ""),
        scene.get("composition", ""),
        scene.get("action", "") or scene.get("purpose", ""),
        loc.get("visual_identity", "") or (f"setting: {loc_name}" if loc_name else ""),
        scene.get("lighting", "") or style_bible.get("lighting_rules", ""),
        scene.get("mood", "") or scene.get("emotional_shift", ""),
        style_bible.get("line_style", ""),
        style_bible.get("palette", ""),
        style_bible.get("materials", ""),
        *char_bits,
        *(loc.get("recurring_props") or []),
        "cinematic composition", "high detail", "consistent character design",
    ])

    negative = join_clean([
        *studio_visual.BASE_NEGATIVE,
        "warped eyes", "wrong character design", "bad anatomy",
        *char_negatives,
        *style_bible.get("avoid", []),
    ])

    rerolls = scene.get("image_rerolls", 0)
    seed = int(profile["seed"]) if int(profile.get("seed", -1)) >= 0 else \
        stable_seed(scene.get("id", "scene"), present, rerolls)

    return PromptPacket(
        positive_prompt=positive,
        negative_prompt=negative,
        model=profile["model"],
        width=int(profile["width"]),
        height=int(profile["height"]),
        steps=int(profile["steps"]),
        cfg=float(profile["cfg"]),
        seed=seed,
        sampler=profile["sampler"],
        scheduler=profile["scheduler"],
        metadata={
            "scene_id": scene.get("id"),
            "title": scene.get("title"),
            "location": loc_name,
            "characters": list(present),
            "compiler_version": "visual_prompt_compiler_v0.1",
        },
    )


def compile_for_scenes(scenes, world, characters, model_profile=None) -> List[Dict[str, Any]]:
    """Compile a PromptPacket for every scene and attach it as ``scene['prompt_packet']`` (a dict).
    Returns the list of packet dicts (also mutates scenes in place). Pure + deterministic."""
    style = build_style_bible(world)
    cvis = build_character_visuals(characters)
    lvis = build_location_visuals(world)
    packets = []
    for scene in scenes or []:
        packet = compile_visual_prompt(scene, style, cvis, lvis, model_profile).to_dict()
        scene["prompt_packet"] = packet
        # Keep the flat fields the player/exports already read in sync with the packet.
        scene["image_prompt"] = packet["positive_prompt"]
        scene["negative_prompt"] = packet["negative_prompt"]
        packets.append(packet)
    return packets
