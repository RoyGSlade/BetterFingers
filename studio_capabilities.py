from copy import deepcopy


REGISTRY_VERSION = "studio-director-exploration-v1"
VALID_CATEGORIES = ("regions", "skins", "pois", "actions")

REGISTRY = {
    "regions": [
        {
            "id": "archive_hall",
            "name": "Archive Hall",
            "description": "A vaulted archive with ladder rails, dust-lit aisles, and sealed artifact cases.",
            "mood_tags": ["mystery", "quiet", "ancient"],
            "valid_pois": ["archive_table", "sealed_case", "upper_balcony"],
        },
        {
            "id": "rain_market",
            "name": "Rain Market",
            "description": "A neon night market under awnings with steam, puddles, and crowded stalls.",
            "mood_tags": ["busy", "noir", "urban"],
            "valid_pois": ["ramen_stall", "alley_corner", "tram_stop"],
        },
        {
            "id": "rooftop_shrine",
            "name": "Rooftop Shrine",
            "description": "A wind-bent shrine above the city, framed by antennas and paper wards.",
            "mood_tags": ["lonely", "spiritual", "windy"],
            "valid_pois": ["shrine_gate", "water_basin", "roof_edge"],
        },
    ],
    "skins": [
        {
            "id": "young_archivist",
            "name": "Young Archivist",
            "description": "A curious lead with layered coats, ink-stained gloves, and a satchel of notes.",
            "roles": ["lead", "investigator", "student"],
            "style_tags": ["anime", "bookish", "grounded"],
        },
        {
            "id": "masked_rival",
            "name": "Masked Rival",
            "description": "A quick rival with a half mask, sharp silhouette, and hidden motives.",
            "roles": ["rival", "thief", "foil"],
            "style_tags": ["anime", "mysterious", "agile"],
        },
        {
            "id": "old_caretaker",
            "name": "Old Caretaker",
            "description": "A weathered caretaker with impossible keys and a patient voice.",
            "roles": ["mentor", "guardian", "witness"],
            "style_tags": ["warm", "worn", "wise"],
        },
    ],
    "pois": [
        {"id": "archive_table", "name": "Archive Table", "region_id": "archive_hall", "capacity": 3, "supports": ["stand_at", "sit_at", "inspect_object", "write_note", "give_object"]},
        {"id": "sealed_case", "name": "Sealed Artifact Case", "region_id": "archive_hall", "capacity": 1, "supports": ["stand_at", "inspect_object", "unlock", "take_object"]},
        {"id": "upper_balcony", "name": "Upper Balcony", "region_id": "archive_hall", "capacity": 2, "supports": ["stand_at", "observe", "call_out"]},
        {"id": "ramen_stall", "name": "Ramen Stall", "region_id": "rain_market", "capacity": 4, "supports": ["sit_at", "talk", "eat", "give_object"]},
        {"id": "alley_corner", "name": "Alley Corner", "region_id": "rain_market", "capacity": 2, "supports": ["stand_at", "hide", "observe", "chase_start"]},
        {"id": "tram_stop", "name": "Tram Stop", "region_id": "rain_market", "capacity": 5, "supports": ["stand_at", "wait", "talk", "depart"]},
        {"id": "shrine_gate", "name": "Shrine Gate", "region_id": "rooftop_shrine", "capacity": 2, "supports": ["stand_at", "bow", "observe", "enter"]},
        {"id": "water_basin", "name": "Water Basin", "region_id": "rooftop_shrine", "capacity": 1, "supports": ["stand_at", "wash_hands", "inspect_object"]},
        {"id": "roof_edge", "name": "Roof Edge", "region_id": "rooftop_shrine", "capacity": 1, "supports": ["stand_at", "observe", "call_out"]},
    ],
    "actions": [
        {"id": "stand_at", "name": "Stand At POI", "description": "Move into a standing posture at a point of interest.", "requires_posture": ["standing", "sitting"], "result_posture": "standing", "requires_object": None, "next_actions": ["inspect_object", "talk", "observe", "give_object", "sit_at"]},
        {"id": "sit_at", "name": "Sit At POI", "description": "Sit at a supported point of interest.", "requires_posture": ["standing"], "result_posture": "sitting", "requires_object": None, "next_actions": ["talk", "eat", "write_note", "stand_at"]},
        {"id": "inspect_object", "name": "Inspect Object", "description": "Examine an object or scene detail without changing ownership.", "requires_posture": ["standing", "sitting"], "result_posture": None, "requires_object": None, "next_actions": ["take_object", "unlock", "write_note", "talk"]},
        {"id": "take_object", "name": "Take Object", "description": "Pick up an available object and add it to held inventory.", "requires_posture": ["standing"], "result_posture": None, "requires_object": None, "next_actions": ["give_object", "inspect_object", "hide", "depart"]},
        {"id": "give_object", "name": "Give Object", "description": "Transfer a held object to another actor; requires a receiver.", "requires_posture": ["standing", "sitting"], "result_posture": None, "requires_object": "held_object", "requires_receiver": True, "next_actions": ["talk", "observe", "stand_at"]},
        {"id": "talk", "name": "Talk", "description": "Exchange dialogue with another actor in the same region.", "requires_posture": ["standing", "sitting"], "result_posture": None, "requires_object": None, "next_actions": ["observe", "give_object", "stand_at"]},
        {"id": "observe", "name": "Observe", "description": "Notice another actor, object, or environmental change.", "requires_posture": ["standing", "sitting"], "result_posture": None, "requires_object": None, "next_actions": ["call_out", "talk", "hide", "stand_at"]},
        {"id": "hide", "name": "Hide", "description": "Move into concealment at a supported POI.", "requires_posture": ["standing"], "result_posture": "standing", "requires_object": None, "next_actions": ["observe", "chase_start", "stand_at"]},
        {"id": "unlock", "name": "Unlock", "description": "Open a locked object or passage using a held key-like object.", "requires_posture": ["standing"], "result_posture": None, "requires_object": "key", "next_actions": ["inspect_object", "take_object", "enter"]},
        {"id": "write_note", "name": "Write Note", "description": "Record a clue or deduction into project memory.", "requires_posture": ["sitting", "standing"], "result_posture": None, "requires_object": None, "next_actions": ["talk", "inspect_object", "stand_at"]},
    ],
}


def _normalize_category(category):
    value = str(category or "").strip().lower()
    if value not in VALID_CATEGORIES:
        allowed = ", ".join(VALID_CATEGORIES)
        raise ValueError(f"Capability category must be one of: {allowed}.")
    return value


def _page_bounds(page, page_size):
    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValueError("page and page_size must be integers.")
    if page < 1:
        raise ValueError("page must be at least 1.")
    if page_size < 1 or page_size > 100:
        raise ValueError("page_size must be between 1 and 100.")
    start = (page - 1) * page_size
    return page, page_size, start, start + page_size


def list_categories():
    return [{"category": category, "count": len(REGISTRY[category])} for category in VALID_CATEGORIES]


def list_capabilities(category, page=1, page_size=20, query=None):
    category = _normalize_category(category)
    page, page_size, start, end = _page_bounds(page, page_size)
    items = deepcopy(REGISTRY[category])
    if query:
        needle = str(query).strip().lower()
        items = [
            item for item in items
            if needle in item.get("id", "").lower()
            or needle in item.get("name", "").lower()
            or needle in item.get("description", "").lower()
        ]
    return {
        "registry_version": REGISTRY_VERSION,
        "category": category,
        "page": page,
        "page_size": page_size,
        "total": len(items),
        "items": items[start:end],
    }


def get_capability(category, capability_id):
    category = _normalize_category(category)
    capability_id = str(capability_id or "").strip()
    for item in REGISTRY[category]:
        if item["id"] == capability_id:
            return deepcopy(item)
    return None


def get_next_actions(action_id):
    action = get_capability("actions", action_id)
    if not action:
        return []
    return [item for item in (get_capability("actions", next_id) for next_id in action.get("next_actions", [])) if item]


def exploration_snapshot(page_size=20):
    return {
        "registry_version": REGISTRY_VERSION,
        "categories": list_categories(),
        "regions": list_capabilities("regions", page_size=page_size),
        "skins": list_capabilities("skins", page_size=page_size),
        "pois": list_capabilities("pois", page_size=page_size),
        "actions": list_capabilities("actions", page_size=page_size),
    }


# --- Director Casting validation (Phase 2) ---------------------------------
#
# The Director may only anchor a story in regions/skins that actually exist in
# the registry (the "Absolute Grounding" rule). Casting selection is therefore
# validated programmatically here rather than trusting the LLM, so an invalid
# reference is rejected deterministically instead of contaminating project state.

MIN_CAST = 2
MAX_CAST = 4


def validate_casting(casting):
    """Validate a Director casting selection strictly against the capability registry.

    Expects a dict like::

        {"region_id": "archive_hall",
         "cast": [{"skin_id": "young_archivist", "character_name": "Mara", "role": "lead"}, ...]}

    Returns a normalized casting dict (with resolved region/skin names) on success.
    Raises ``ValueError`` with a descriptive message on any invalid reference so the
    caller can surface a structured error and retry/repair.
    """
    if not isinstance(casting, dict):
        raise ValueError("Casting must be an object with 'region_id' and 'cast'.")

    region = get_capability("regions", casting.get("region_id"))
    if not region:
        valid = ", ".join(str(item["id"]) for item in REGISTRY["regions"])
        raise ValueError(f"Unknown region_id '{casting.get('region_id')}'. Valid regions: {valid}.")

    cast = casting.get("cast")
    if not isinstance(cast, list) or not cast:
        raise ValueError("Casting must include a non-empty 'cast' list.")
    if not (MIN_CAST <= len(cast) <= MAX_CAST):
        raise ValueError(f"Casting must include between {MIN_CAST} and {MAX_CAST} cast members.")

    normalized_cast = []
    seen_skins = set()
    seen_names = set()
    for index, member in enumerate(cast):
        if not isinstance(member, dict):
            raise ValueError(f"Cast member #{index + 1} must be an object.")
        skin = get_capability("skins", member.get("skin_id"))
        if not skin:
            valid = ", ".join(str(item["id"]) for item in REGISTRY["skins"])
            raise ValueError(f"Unknown skin_id '{member.get('skin_id')}' in cast member #{index + 1}. Valid skins: {valid}.")
        if skin["id"] in seen_skins:
            raise ValueError(f"Skin '{skin['id']}' is cast more than once; each skin may anchor only one character.")
        seen_skins.add(skin["id"])

        character_name = str(member.get("character_name") or "").strip()
        if not character_name:
            raise ValueError(f"Cast member #{index + 1} is missing a character_name.")
        name_key = character_name.lower()
        if name_key in seen_names:
            raise ValueError(f"Character name '{character_name}' is used more than once.")
        seen_names.add(name_key)

        role = str(member.get("role") or "").strip() or (skin.get("roles") or ["cast"])[0]
        normalized_cast.append({
            "skin_id": skin["id"],
            "skin_name": skin["name"],
            "character_name": character_name,
            "role": role,
            "style_tags": skin.get("style_tags", []),
        })

    return {
        "registry_version": REGISTRY_VERSION,
        "region_id": region["id"],
        "region_name": region["name"],
        "region_description": region.get("description", ""),
        "region_mood_tags": region.get("mood_tags", []),
        "cast": normalized_cast,
    }


def default_casting(cast_size=2):
    """Deterministic, registry-valid casting used as a grounded fallback.

    Picks the first region and maps the first ``cast_size`` skins onto their primary
    role. Guaranteed to pass :func:`validate_casting` by construction.
    """
    cast_size = max(MIN_CAST, min(MAX_CAST, int(cast_size)))
    region = REGISTRY["regions"][0]
    cast = []
    for skin in REGISTRY["skins"][:cast_size]:
        cast.append({
            "skin_id": skin["id"],
            "character_name": skin["name"],
            "role": (skin.get("roles") or ["cast"])[0],
        })
    return validate_casting({"region_id": region["id"], "cast": cast})
