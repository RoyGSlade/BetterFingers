"""
Visual Prompt agent — deterministic image-prompt assembly.

The old pipeline built an image prompt as `visual_description + ". " + style_prompt`, with the
`negative_prompt` field left empty and no character/location anchoring. That produced generic,
inconsistent art. This module assembles a prompt from *structured* parts so the same character
looks the same across panels and the world's palette/lighting actually reach the image backend:

    [shot subject + action]
    + [visual refs of the characters present, pulled from their bibles]
    + [location reference]
    + [world palette / lighting / materials]
    + [medium + camera + composition]
    + a real negative prompt (shared guards + per-character "off-model" terms)

It is deterministic (system code, not an LLM call): given the same structured inputs it always
produces the same prompt, which is what makes panels reproducible and consistent.
"""

# Shared negative-prompt guards applied to every panel.
BASE_NEGATIVE = [
    "blurry", "lowres", "deformed hands", "extra fingers", "extra limbs", "fused fingers",
    "watermark", "signature", "text", "caption", "jpeg artifacts", "melted faces",
    "off-model", "inconsistent character design", "duplicate characters",
]

# House style applied unless the world overrides the medium.
DEFAULT_MEDIUM = "cinematic comic panel, clean line art, cel shading, high detail"


def _clean(value):
    return str(value or "").strip().strip(".,;").strip()


def _character_descriptor(character):
    """Build a stable visual descriptor for one character from their bible's visual block."""
    visual = character.get("visual") if isinstance(character, dict) else None
    if not isinstance(visual, dict):
        # Fall back to the metadata.visual block if the flat field isn't present.
        meta = character.get("metadata") if isinstance(character, dict) else None
        if isinstance(meta, dict):
            visual = meta.get("visual")
    name = _clean(character.get("name")) if isinstance(character, dict) else ""
    if not isinstance(visual, dict):
        return name or ""
    look = ", ".join(
        _clean(v) for v in (
            visual.get("face"), visual.get("hair"), visual.get("build"),
            visual.get("outfit"), visual.get("palette"),
        ) if _clean(v)
    )
    if name and look:
        return f"{name}: {look}"
    return name or look


def _character_negatives(characters_present, characters_by_name):
    """Per-character off-model guards (e.g. 'not blonde' is hard, but 'consistent <name>' helps)."""
    terms = []
    for name in characters_present or []:
        ch = characters_by_name.get(str(name).lower())
        if not ch:
            continue
        # Encourage the backend to keep palettes from bleeding between characters.
        terms.append(f"{name} wrong outfit")
    return terms


def index_characters(characters):
    """Map lowercased character name -> character dict, for quick lookup during assembly."""
    out = {}
    for ch in characters or []:
        if isinstance(ch, dict) and ch.get("name"):
            out[str(ch["name"]).lower()] = ch
    return out


def build_image_prompt(panel, world, characters_by_name):
    """Return (image_prompt, negative_prompt) for one assembled panel.

    `panel` is an assembled-panel dict (visual_description, action, camera, composition,
    visible_characters, location_ref, continuity_state). `world` is the structured world
    bible. `characters_by_name` comes from index_characters().
    """
    parts = []

    subject = _clean(panel.get("visual_description"))
    if subject:
        parts.append(subject)

    # Character visual references — the key to cross-panel consistency.
    descriptors = []
    present = panel.get("visible_characters") or []
    for name in present:
        ch = characters_by_name.get(str(name).lower())
        if ch:
            desc = _character_descriptor(ch)
            if desc:
                descriptors.append(desc)
    if descriptors:
        parts.append("characters — " + "; ".join(descriptors))

    # Location reference (prefer the named world location's own visual prompt).
    location_ref = _clean(panel.get("location_ref"))
    loc_visual = ""
    for loc in (world.get("locations") or []):
        if isinstance(loc, dict) and _clean(loc.get("name")).lower() == location_ref.lower() and location_ref:
            loc_visual = _clean(loc.get("visual_prompt"))
            break
    if loc_visual:
        parts.append(f"setting: {location_ref} — {loc_visual}")
    elif location_ref:
        parts.append(f"setting: {location_ref}")

    # World look: palette, lighting, materials.
    palette = _clean(world.get("palette")) or _clean(world.get("aesthetic"))
    if palette:
        parts.append(f"palette: {palette}")
    lighting = _clean(world.get("lighting"))
    if lighting:
        parts.append(f"lighting: {lighting}")
    materials = _clean(world.get("materials"))
    if materials:
        parts.append(f"textures: {materials}")

    # Continuity cues (props/injury/mood) so the look tracks the story state.
    cont = panel.get("continuity_state") or {}
    if isinstance(cont, dict):
        cues = ", ".join(_clean(cont.get(k)) for k in ("props", "injury", "mood") if _clean(cont.get(k)))
        if cues:
            parts.append(f"continuity: {cues}")

    # Medium + camera grammar.
    camera = _clean(panel.get("camera"))
    composition = _clean(panel.get("composition"))
    cam_bits = ", ".join(x for x in (camera, composition) if x)
    parts.append(f"{DEFAULT_MEDIUM}{(', ' + cam_bits) if cam_bits else ''}")

    image_prompt = ". ".join(parts)

    negatives = list(BASE_NEGATIVE) + _character_negatives(present, characters_by_name)
    negative_prompt = ", ".join(dict.fromkeys(negatives))  # dedupe, preserve order

    return image_prompt, negative_prompt
