"""
Model-aware generation profiles + batched, schema-checked LLM helpers.

The Studio pipeline used to ask the local model for one large JSON blob per stage (all 12
panels at once, capped at 1500 tokens). On a small local model (≈4B, CPU-only) that
routinely fails JSON parsing and silently falls back to mock data — the root cause of the
incoherent output.

This module makes generation *batched and model-aware*: we pick a capability tier from the
selected model, and every stage asks for small, schema-shaped pieces that we stitch together
in code. Bigger models do fewer, richer calls; small models do more, smaller ones — but both
succeed instead of collapsing to the mock fallback.

Deterministic helpers here (batching, validation, stitching) are the "system pieces things
together" half of the design; the LLM is only used to interpret/expand each small piece.
"""

import re
import logging

logger = logging.getLogger("studio_generation")

# Capability tiers. Driven by model SIZE (param count), not just whether it fits RAM — a 4B
# model is "small" even on a 64 GB machine.
TIER_SMALL = "small"
TIER_MEDIUM = "medium"
TIER_LARGE = "large"

# Per-tier knobs. batch sizes = how many items we ask the model to produce per call;
# token budgets = max_output_tokens for that call shape. Small = ask for less, more often.
_PROFILES = {
    TIER_SMALL: {
        "tier": TIER_SMALL,
        "characters_per_call": 1,     # one character bible per call
        "beats_per_call": 1,          # deepen one beat at a time
        "shots_per_beat": 2,          # 2 shots per beat
        "panels_per_call": 2,         # dialogue/panels in pairs
        # `large` is the single-shot whole-story schema (genesis/loremaster/showrunner). It must be
        # big enough to emit a COMPLETE JSON object; too small truncates it mid-object and the parse
        # fails, dropping the keystone understanding to the procedural skeleton.
        "max_tokens": {"small": 500, "medium": 800, "large": 2600},
        "dialogue_passes": 1,         # single well-briefed pass
    },
    TIER_MEDIUM: {
        "tier": TIER_MEDIUM,
        "characters_per_call": 2,
        "beats_per_call": 2,
        "shots_per_beat": 3,
        "panels_per_call": 4,
        "max_tokens": {"small": 700, "medium": 1200, "large": 4096},
        "dialogue_passes": 2,         # write + voice/punch-up pass
    },
    TIER_LARGE: {
        "tier": TIER_LARGE,
        "characters_per_call": 4,
        "beats_per_call": 3,
        "shots_per_beat": 4,
        "panels_per_call": 6,
        "max_tokens": {"small": 900, "medium": 1500, "large": 6144},
        "dialogue_passes": 2,
    },
}


def tier_for_model(model_id):
    """Map a model id (e.g. 'gemma-4-e4b-q4', 'gemma-3-12b-q4', 'gemma-4-31b-q4') to a tier.

    We read the parameter scale out of the id: E2B/E4B/4B -> small, 12B -> medium,
    26B/31B (and bigger) -> large. Unknown ids default to small (the safe, reliable choice).
    """
    text = str(model_id or "").lower()
    # Find a billions-of-parameters number. Handles 'e2b', 'e4b', '4b', '12b', '26b', '31b'.
    match = re.search(r"(?:^|[^a-z0-9])e?(\d{1,3})b", text)
    if not match:
        return TIER_SMALL
    billions = int(match.group(1))
    if billions <= 9:
        return TIER_SMALL
    if billions <= 14:
        return TIER_MEDIUM
    return TIER_LARGE


def get_generation_profile(model_id=None):
    """Return the generation profile for the given model id (defaults to the small tier)."""
    tier = tier_for_model(model_id)
    profile = dict(_PROFILES.get(tier, _PROFILES[TIER_SMALL]))
    profile["model_id"] = model_id
    return profile


def max_tokens_for(profile, shape="medium"):
    """Token budget for a call of the given shape ('small' | 'medium' | 'large')."""
    budgets = (profile or {}).get("max_tokens") or _PROFILES[TIER_SMALL]["max_tokens"]
    return budgets.get(shape, budgets.get("medium", 800))


def chunk(items, size):
    """Split a list into batches of at most `size` (>=1). The batching primitive."""
    items = list(items or [])
    size = max(1, int(size or 1))
    return [items[i:i + size] for i in range(0, len(items), size)]


def run_batched(items, fn, batch_size):
    """Run `fn(batch)` over small chunks of `items` and stitch the results into one list.

    `fn` receives a list (the batch) and must return a list. Failures in one batch are
    logged and skipped so a single bad batch never sinks the whole stage.
    """
    results = []
    for batch in chunk(items, batch_size):
        try:
            produced = fn(batch)
            if isinstance(produced, list):
                results.extend(produced)
            elif produced is not None:
                results.append(produced)
        except Exception as exc:  # pragma: no cover - defensive; individual stages log detail
            logger.warning("Batched generation chunk failed: %s", exc)
    return results


def missing_keys(obj, required):
    """Return required keys absent or empty in obj. Empty list == valid."""
    if not isinstance(obj, dict):
        return list(required or [])
    out = []
    for key in (required or []):
        value = obj.get(key)
        if value is None or (isinstance(value, (str, list, dict)) and len(value) == 0):
            out.append(key)
    return out


def ensure_keys(obj, required):
    """True when obj is a dict containing every required key with a non-empty value."""
    return not missing_keys(obj, required)


def sentence_safe_trim(text, limit):
    """Trim text to <= limit chars on a word/sentence boundary — never mid-word.

    Fixes the old fallback that sliced visual descriptions at [:120] and produced
    fragments like '...counted the number of dri'.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    # Prefer ending at the last sentence terminator, else the last whole word.
    for terminator in (". ", "! ", "? "):
        idx = window.rfind(terminator)
        if idx >= limit * 0.5:
            return window[:idx + 1].strip()
    idx = window.rfind(" ")
    if idx > 0:
        return window[:idx].strip() + "…"
    return window.strip() + "…"
