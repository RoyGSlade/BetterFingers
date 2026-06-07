"""
Studio repair / rebuild support.

When a Director stage is *rejected* by the deterministic validators (scene physics,
casting grounding, JSON shape, or finalization timeline), the workflow used to either
silently swap in a mock fallback or dead-end with a bare error string. That is the
"got stuck on continuity and produced nothing" experience.

This module turns a rejection into a structured, grounded *repair report*: a plain
explanation of what is wrong/missing, the valid options pulled from the capability
registry, and a question to put to the user. The user's answer is then fed (with the
same grounding) to the LLM, which proposes concrete fixes the user can pick from or
edit. The goal is a human + AI loop, not a silent fallback.
"""

import re

import studio_capabilities as caps


# Map a raw validator error to a coarse repair category. The category drives which
# grounded options we surface and how we phrase the question to the user.
def classify_rejection(phase, error):
    text = str(error or "")
    low = text.lower()

    if phase == "finalization" or "cycle" in low or "timeline" in low:
        return "continuity"
    if "unknown region" in low or "not in region" in low:
        return "region"
    if "unknown poi" in low or "does not support action" in low or "capacity" in low:
        return "poi"
    if "unknown action" in low or "cannot follow" in low or "requires_posture" in low or "posture" in low:
        return "action"
    if "held" in low or "object" in low or "receiver" in low or "key" in low:
        return "object"
    if "unknown skin" in low or "actor" in low or "casting" in low:
        return "casting"
    if "json" in low or "parse" in low or "length" in low or "oversized" in low:
        return "format"
    return "generic"


def _quoted(text):
    """Pull the first 'quoted' token out of a validator message (e.g. the bad id)."""
    match = re.search(r"'([^']+)'", str(text or ""))
    return match.group(1) if match else None


def _allowed_from_error(text):
    """Some validators embed the allowed set as `Allowed: ['a', 'b']` — recover it."""
    match = re.search(r"[Aa]llowed:\s*\[([^\]]*)\]", str(text or ""))
    if not match:
        return []
    return [tok.strip().strip("'\"") for tok in match.group(1).split(",") if tok.strip()]


def _region_pois(region_id):
    region = caps.get_capability("regions", region_id) if region_id else None
    if region:
        return list(region.get("valid_pois", []))
    return [item["id"] for item in caps.list_capabilities("pois").get("items", [])]


def grounded_options(category, error, context):
    """Return registry-valid options relevant to the rejection, as {id, name} dicts."""
    context = context or {}
    region_id = context.get("region_id")

    def pack(cat, ids=None):
        items = caps.list_capabilities(cat).get("items", [])
        if ids is not None:
            allow = set(ids)
            items = [it for it in items if it["id"] in allow]
        return [{"id": it["id"], "name": it.get("name", it["id"]), "description": it.get("description", "")} for it in items]

    if category == "region":
        return {"label": "Valid regions", "options": pack("regions")}
    if category == "poi":
        return {"label": "Valid points of interest", "options": pack("pois", _region_pois(region_id))}
    if category == "action":
        allowed = _allowed_from_error(error)
        return {"label": "Valid next actions", "options": pack("actions", allowed or None)}
    if category == "casting":
        return {"label": "Valid character skins", "options": pack("skins")}
    if category == "object":
        # Objects live on POIs in the registry; surface POIs so the user can pick a
        # place that actually holds the object the action needs.
        return {"label": "Points of interest (where objects live)", "options": pack("pois", _region_pois(region_id))}
    return {"label": "", "options": []}


_QUESTIONS = {
    "continuity": "These scenes can't be ordered into one timeline (they loop back on each other). Which scene should come first, or which connection is wrong?",
    "region": "The chosen location isn't a real region. Where should this scene take place?",
    "poi": "That spot doesn't exist or can't host this action here. Where in the scene should it happen?",
    "action": "That action can't follow the previous one. What did you want the character to do at this beat?",
    "object": "This action needs an object (held item or receiver) that isn't present. What item or who should be involved?",
    "casting": "The casting pick isn't valid for this world. Who should be in this scene, and how should they look?",
    "format": "The model's output couldn't be read as a clean plan. Describe in your own words what this beat should contain.",
    "generic": "Something in this step was rejected. Tell us what you were going for and we'll rebuild it.",
}


def build_repair_report(phase, error, context=None):
    """Turn a single rejection into a structured, grounded repair report for the UI."""
    category = classify_rejection(phase, error)
    bad_token = _quoted(error)
    grounding = grounded_options(category, error, context)

    return {
        "phase": phase,
        "category": category,
        "error": str(error or ""),
        "problem": _QUESTIONS.get(category, _QUESTIONS["generic"]),
        "offending_value": bad_token,
        "valid_options": grounding.get("options", []),
        "valid_options_label": grounding.get("label", ""),
        "question": _QUESTIONS.get(category, _QUESTIONS["generic"]),
        "context": context or {},
        "allow_freeform": True,
    }


def deterministic_proposals(report):
    """
    Grounded fallback proposals used when the LLM is unavailable. Each proposal is a
    selectable fix: a short label/description plus a machine-applicable `resolution`.
    """
    category = report.get("category")
    options = report.get("valid_options", [])[:4]
    proposals = []

    if category in ("region", "poi", "action", "casting", "object") and options:
        for opt in options:
            proposals.append({
                "label": opt.get("name", opt.get("id")),
                "description": opt.get("description") or f"Use '{opt.get('id')}' here.",
                "resolution": {"type": "set", "field": category, "value": opt.get("id")},
            })
    elif category == "continuity":
        proposals.append({
            "label": "Drop the conflicting link",
            "description": "Remove the cross-scene connection that creates the loop and re-link in creation order.",
            "resolution": {"type": "relink", "strategy": "creation_order"},
        })

    proposals.append({
        "label": "Describe the fix myself",
        "description": "Write what this beat should be; the AI will rebuild it from your description.",
        "resolution": {"type": "freeform"},
    })
    return proposals


def build_proposal_prompt(report, user_note):
    """Build the LLM prompt that reads the user's explanation and proposes fixes."""
    option_lines = "\n".join(
        f"- {opt.get('id')}: {opt.get('name')} — {opt.get('description', '')}".rstrip(" —")
        for opt in report.get("valid_options", [])
    ) or "(no preset options; use the user's description)"

    system_prompt = (
        "You are the Studio Repair Director. A production step was rejected by the validator. "
        "Read the validator error AND the user's explanation of what they intended, identify the "
        "single core problem, and propose 2-4 concrete fixes. Each fix MUST be achievable with the "
        "valid options listed (or a clear freeform rewrite). Be specific and grounded — never invent "
        "ids that are not in the valid options. "
        'Respond with ONLY JSON: {"diagnosis": "<one sentence>", "proposals": '
        '[{"label": "<short>", "description": "<what it does>", "resolution": '
        '{"type": "set", "field": "<category>", "value": "<valid id>"}}]}. '
        'For a freeform rewrite use {"type": "freeform"}.'
    )

    user_prompt = (
        f"REJECTED STAGE: {report.get('phase')} (category: {report.get('category')})\n"
        f"VALIDATOR ERROR: {report.get('error')}\n"
        f"OFFENDING VALUE: {report.get('offending_value')}\n"
        f"VALID OPTIONS ({report.get('valid_options_label')}):\n{option_lines}\n\n"
        f"USER EXPLANATION: {user_note or '(none provided)'}\n\n"
        "Propose grounded fixes now."
    )
    return user_prompt, system_prompt
