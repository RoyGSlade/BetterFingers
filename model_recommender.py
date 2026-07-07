"""Hardware-aware model recommendations (U4).

Given the hardware tier (from hardware_report.classify_tier) and available RAM,
rank the LLM and Whisper catalogs and pick a sensible default per role with
plain-language tradeoff copy. Pure functions of (tier, ram, catalog) so they are
unit-testable without any specific hardware.
"""
import re

from model_manager import AVAILABLE_MODELS, DEFAULT_MODEL
from transcriber import SUPPORTED_MODEL_SIZES
from hardware_report import _estimate_runtime_mb

# The largest LLM (billions of params) worth *recommending* per tier. Bigger
# models may still run, but slowly, so they are offered with a caveat, not chosen.
TIER_LLM_CAP_PARAMS = {"cpu-only": 4, "igpu": 4, "dgpu-8g": 12, "dgpu-12g+": 31}

# Whisper default per tier (accuracy vs speed).
TIER_WHISPER = {
    "cpu-only": "base.en",
    "igpu": "base.en",
    "dgpu-8g": "small.en",
    "dgpu-12g+": "medium.en",
}

_WHISPER_BLURB = {
    "tiny.en": "Fastest, lowest accuracy.",
    "base.en": "Fast and accurate enough for most dictation.",
    "small.en": "Better accuracy, a bit slower.",
    "medium.en": "High accuracy, slow on CPU.",
    "large-v3": "Best accuracy, needs a GPU to be usable.",
    "distil-medium.en": "Medium accuracy, faster than medium.",
    "distil-large-v3": "Near-large accuracy, faster than large.",
}


def _params_b(model_id, meta):
    name = f"{meta.get('name', '')} {model_id}".lower()
    m = re.search(r"e(\d+)b", name)  # Gemma 4 E2B/E4B effective sizes
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)b", name)
    if m:
        return int(m.group(1))
    return 4


def _fit(need_mb, ram_mb):
    if not ram_mb:
        return "unknown"
    if need_mb <= ram_mb * 0.7:
        return "comfortable"
    if need_mb <= ram_mb * 0.95:
        return "tight"
    return "insufficient"


def _llm_note(item, cap, is_recommended):
    if is_recommended:
        return "Recommended for your hardware — good quality that fits comfortably."
    if item["fit"] == "insufficient":
        return "Too large for your available RAM."
    if item["params_b"] > cap:
        return "Runs, but will be slow without a bigger GPU."
    if item["fit"] == "tight":
        return "Fits, but tight — close other apps first."
    return "Fits comfortably; lighter and faster than the recommended pick."


def recommend_llm(tier, ram_mb):
    cap = TIER_LLM_CAP_PARAMS.get(tier, 4)
    items = []
    for mid, meta in AVAILABLE_MODELS.items():
        size_mb = int(meta.get("size_mb", 0) or 0)
        need = _estimate_runtime_mb(size_mb) if size_mb else 0
        items.append(
            {
                "id": mid,
                "name": meta.get("name", mid),
                "size_mb": size_mb,
                "need_mb": need,
                "params_b": _params_b(mid, meta),
                "fit": _fit(need, ram_mb),
            }
        )

    comfortable = [i for i in items if i["params_b"] <= cap and i["fit"] == "comfortable"]
    if comfortable:
        best_params = max(i["params_b"] for i in comfortable)
        tied = [i for i in comfortable if i["params_b"] == best_params]
        recommended_id = min(tied, key=lambda i: i["size_mb"])["id"]
    else:
        fitting = [i for i in items if i["fit"] in ("comfortable", "tight")]
        recommended_id = min(fitting, key=lambda i: i["size_mb"])["id"] if fitting else DEFAULT_MODEL

    for i in items:
        i["recommended"] = i["id"] == recommended_id
        i["note"] = _llm_note(i, cap, i["recommended"])

    fit_rank = {"comfortable": 0, "tight": 1, "unknown": 2, "insufficient": 3}
    items.sort(key=lambda i: (not i["recommended"], fit_rank.get(i["fit"], 4), -i["params_b"]))
    return {"recommended": recommended_id, "models": items}


def recommend_whisper(tier):
    recommended_id = TIER_WHISPER.get(tier, "base.en")
    models = []
    for size in SUPPORTED_MODEL_SIZES:
        models.append(
            {
                "id": size,
                "recommended": size == recommended_id,
                "note": _WHISPER_BLURB.get(size, ""),
            }
        )
    models.sort(key=lambda m: not m["recommended"])
    return {"recommended": recommended_id, "models": models}


def recommend(tier, ram_mb):
    return {
        "tier": tier,
        "ram_mb": int(ram_mb or 0) or None,
        "llm": recommend_llm(tier, ram_mb),
        "whisper": recommend_whisper(tier),
    }
