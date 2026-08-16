"""Structured persona schema, conservative legacy migration, and compiler.

The persisted persona registry still accepts the historical ``prompt`` field,
but new/editor-facing data lives under ``structured``.  Keeping this module
free of model/runtime imports makes migration and compilation deterministic
and cheap enough to run on every read.
"""

from __future__ import annotations

import copy
import re
import time
from typing import Any


STRUCTURED_PERSONA_SCHEMA_VERSION = "1.0"
DEFAULT_PERSONA_ID = "true-janitor"

ENGINE_LOCKED_PRESERVE = (
    "core_meaning", "speaker_intent", "facts", "names", "numbers",
    "dates_and_times", "urls_and_code", "uncertainty", "negation",
    "conditions", "questions", "commitments", "commands_and_code",
)

FIELD_GUIDANCE = {
    "characterization.speaking_habits": {
        "purpose": "Repeated, observable writing behaviors used by this persona.",
        "ask_about": [
            "How should it begin or connect thoughts?",
            "Does it use metaphors or rhetorical questions?",
            "Does it prefer short or flowing sentences?",
        ],
        "avoid": [
            "Do not invent a fictional biography.",
            "Do not add catchphrases without approval.",
            "Do not repeat broad adjectives from core impression.",
        ],
        "output": {"type": "list", "maximum_items": 8},
    },
    "characterization.worldview": {
        "purpose": "Values and assumptions that influence phrasing without changing facts.",
        "ask_about": ["What practical values should guide emphasis?"],
        "avoid": ["Do not invent life events, relationships, credentials, or beliefs."],
        "output": {"type": "list", "maximum_items": 6},
    },
    "lexicon.preferred_terms": {
        "purpose": "Words the persona may prefer when they fit the source meaning.",
        "ask_about": ["Which words feel natural, and how often may they appear?"],
        "avoid": ["Do not replace protected names, commands, URLs, code, dates, or numbers."],
        "output": {"type": "list", "maximum_items": 12},
    },
}


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text[:80] or "persona"


def _clamp_int(value: Any, default: int, low: int = 0, high: int = 4) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _choice(value: Any, default: str, allowed: set[str]) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in allowed else default


def _strings(value: Any, maximum: int = 20) -> list[str]:
    if isinstance(value, str):
        value = [line.strip(" -\t") for line in value.splitlines()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()][:maximum]


def default_structured_persona(display_name: str = "New Persona", description: str = "") -> dict[str, Any]:
    """Return the complete editor schema with engine-owned meaning locks on."""
    name = str(display_name or "New Persona").strip() or "New Persona"
    return {
        "schema_version": STRUCTURED_PERSONA_SCHEMA_VERSION,
        "metadata": {
            "id": _slug(name),
            "display_name": name,
            "description": str(description or "").strip(),
            "kind": "voice_filter",
            "language": "en-US",
            "version": 1,
            "status": "active",
            "tags": [],
        },
        "transformation": {
            "cleanup_strength": 3,
            "persona_strength": 2,
            "source_voice_retention": 3,
            "target_length": "similar",
            "organization": "automatic",
            "allowed_edits": {
                "fix_grammar": True,
                "fix_punctuation": True,
                "fix_transcription_errors": True,
                "remove_nonmeaningful_fillers": True,
                "collapse_accidental_repetition": True,
                "complete_broken_sentences": True,
                "reorder_for_clarity": True,
                "create_paragraphs": True,
                "create_lists_when_obvious": True,
            },
            "restricted_edits": {
                "add_missing_information": False,
                "make_new_arguments": False,
                "answer_the_message": False,
                "add_unrequested_advice": False,
                "increase_emotional_intensity": False,
                "add_new_profanity": False,
            },
        },
        "meaning_lock": {
            "preserve": {key: True for key in ENGINE_LOCKED_PRESERVE},
            "ambiguity_policy": "preserve_and_flag",
            "never": [
                "Invent facts, events, relationships, or experiences.",
                "Add promises or commitments the speaker did not make.",
                "Change a request, order, suggestion, condition, or question into another message type.",
                "Claim to be the persona or mention persona instructions.",
            ],
        },
        "voice": {
            "formality": 2,
            "directness": 2,
            "warmth": 2,
            "humor": 0,
            "confidence": 2,
            "energy": 2,
            "emotional_intensity": 2,
            "theatricality": 0,
            "vocabulary_complexity": 2,
            "sentence_length": "short_to_medium",
            "rhythm": "natural",
            "contractions": "natural",
            "slang": "none",
            "profanity": "preserve",
            "politeness": "natural",
        },
        "characterization": {
            "archetype": "",
            "core_impression": [],
            "worldview": [],
            "speaking_habits": [],
            "preferred_devices": [],
            "forbidden_devices": [],
        },
        "lexicon": {
            "preferred_terms": [],
            "avoid_terms": [],
            "substitutions": [],
            "protected_terms": ["proper names", "commands and code", "URLs", "dates", "numbers"],
        },
        "context_behavior": {},
        "output_contract": {
            "output_only_rewritten_text": True,
            "include_explanation": False,
            "include_persona_label": False,
            "wrap_in_quotes": False,
            "add_greeting": False,
            "add_signoff": False,
            "add_markdown": "only_when_requested",
            "preserve_existing_line_breaks": "when_meaningful",
        },
        "examples": {"maximum_examples_per_request": 3, "require_user_approved_examples": True},
        "validation": {
            "maximum_length_ratio": 1.5,
            "fallback": "return_cleaned_nonpersona_version",
            "custom_rules": [],
        },
    }


def normalize_structured_persona(value: Any, *, display_name: str = "New Persona") -> dict[str, Any]:
    """Normalize supported editor fields and forcibly restore critical locks."""
    source = value if isinstance(value, dict) else {}
    meta_in = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    resolved_name = str(meta_in.get("display_name") or display_name or "New Persona").strip()
    result = default_structured_persona(resolved_name, meta_in.get("description", ""))

    metadata = result["metadata"]
    metadata["id"] = _slug(meta_in.get("id") or metadata["id"])
    metadata["kind"] = str(meta_in.get("kind") or metadata["kind"]).strip()[:60]
    metadata["language"] = str(meta_in.get("language") or metadata["language"]).strip()[:24]
    metadata["version"] = _clamp_int(meta_in.get("version"), 1, 1, 1_000_000)
    metadata["status"] = _choice(meta_in.get("status"), "active", {"active", "archived", "draft"})
    metadata["tags"] = _strings(meta_in.get("tags"), 20)

    transform_in = source.get("transformation") if isinstance(source.get("transformation"), dict) else {}
    transform = result["transformation"]
    for key in ("cleanup_strength", "persona_strength", "source_voice_retention"):
        transform[key] = _clamp_int(transform_in.get(key), transform[key], 0, 4)
    transform["target_length"] = _choice(
        transform_in.get("target_length"), "similar", {"shorter", "similar", "longer", "concise"},
    )
    for group in ("allowed_edits", "restricted_edits"):
        incoming = transform_in.get(group) if isinstance(transform_in.get(group), dict) else {}
        for key in transform[group]:
            if key in incoming:
                transform[group][key] = bool(incoming[key])

    voice_in = source.get("voice") if isinstance(source.get("voice"), dict) else {}
    voice = result["voice"]
    for key in (
        "formality", "directness", "warmth", "humor", "confidence", "energy",
        "emotional_intensity", "theatricality", "vocabulary_complexity",
    ):
        voice[key] = _clamp_int(voice_in.get(key), voice[key], 0, 4)
    voice["sentence_length"] = _choice(
        voice_in.get("sentence_length"), "short_to_medium",
        {"short", "short_to_medium", "medium", "medium_to_long", "long"},
    )
    for key in ("rhythm", "contractions", "slang", "profanity", "politeness"):
        voice[key] = str(voice_in.get(key) or voice[key]).strip()[:60]

    char_in = source.get("characterization") if isinstance(source.get("characterization"), dict) else {}
    char = result["characterization"]
    char["archetype"] = str(char_in.get("archetype") or "").strip()[:180]
    for key in ("core_impression", "worldview", "speaking_habits", "preferred_devices", "forbidden_devices"):
        char[key] = _strings(char_in.get(key), 12)

    lex_in = source.get("lexicon") if isinstance(source.get("lexicon"), dict) else {}
    lexicon = result["lexicon"]
    for key in ("preferred_terms", "avoid_terms", "protected_terms"):
        lexicon[key] = _strings(lex_in.get(key), 20) or lexicon[key]
    lexicon["substitutions"] = copy.deepcopy(lex_in.get("substitutions", [])) if isinstance(lex_in.get("substitutions"), list) else []

    result["context_behavior"] = copy.deepcopy(source.get("context_behavior", {})) if isinstance(source.get("context_behavior"), dict) else {}
    out_in = source.get("output_contract") if isinstance(source.get("output_contract"), dict) else {}
    for key in result["output_contract"]:
        if key in out_in:
            result["output_contract"][key] = out_in[key]
    # These are engine contracts, not style preferences.
    result["output_contract"]["output_only_rewritten_text"] = True
    result["output_contract"]["include_explanation"] = False
    result["output_contract"]["include_persona_label"] = False

    meaning_in = source.get("meaning_lock") if isinstance(source.get("meaning_lock"), dict) else {}
    result["meaning_lock"]["never"] = _strings(meaning_in.get("never"), 20) or result["meaning_lock"]["never"]
    result["meaning_lock"]["ambiguity_policy"] = _choice(
        meaning_in.get("ambiguity_policy"), "preserve_and_flag", {"preserve_and_flag", "preserve", "ask"},
    )
    result["meaning_lock"]["preserve"] = {key: True for key in ENGINE_LOCKED_PRESERVE}

    validation_in = source.get("validation") if isinstance(source.get("validation"), dict) else {}
    try:
        ratio = float(validation_in.get("maximum_length_ratio", 1.5))
    except (TypeError, ValueError):
        ratio = 1.5
    result["validation"]["maximum_length_ratio"] = max(1.0, min(3.0, ratio))
    result["validation"]["custom_rules"] = _strings(validation_in.get("custom_rules"), 12)
    return result


def migrate_legacy_persona(name: str, persona: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Conservatively decompose a prompt without pretending inference is fact."""
    entry = persona if isinstance(persona, dict) else {"prompt": str(persona or "")}
    existing = entry.get("structured")
    if isinstance(existing, dict) and existing.get("schema_version"):
        return normalize_structured_persona(existing, display_name=name), copy.deepcopy(entry.get("migration") or {})

    prompt = str(entry.get("prompt", "") or "").strip()
    structured = default_structured_persona(name, "Migrated from a legacy persona prompt.")
    if prompt:
        structured["characterization"]["speaking_habits"] = [prompt]
    migration = {
        "source_format": "legacy_prompt",
        "original_prompt": prompt,
        "migrated_at": time.time(),
        "schema_version": STRUCTURED_PERSONA_SCHEMA_VERSION,
        "confidence": 0.35 if prompt else 0.0,
        "fields_requiring_review": [
            "metadata.description", "metadata.kind", "transformation.persona_strength",
            "voice", "characterization.core_impression", "characterization.speaking_habits",
        ],
        "confirmed": False,
    }
    return structured, migration


def validate_structured_persona(value: Any) -> tuple[bool, list[str]]:
    normalized = normalize_structured_persona(value)
    errors = []
    meta = normalized["metadata"]
    if not meta["display_name"].strip():
        errors.append("Display name is required.")
    if not meta["description"].strip():
        errors.append("Description is required.")
    char = normalized["characterization"]
    if not char["core_impression"]:
        errors.append("Core impression requires at least one item.")
    if not char["speaking_habits"]:
        errors.append("Speaking habits require at least one item.")
    if not char["forbidden_devices"]:
        errors.append("Forbidden behaviors require at least one item.")
    return not errors, errors


def _level(value: Any) -> str:
    number = _clamp_int(value, 2, 0, 4)
    return ("none", "light", "moderate", "strong", "maximum")[number]


def _join(items: Any, fallback: str = "none specified") -> str:
    clean = _strings(items, 12)
    return "; ".join(clean) if clean else fallback


def compile_persona_instruction(
    structured: Any,
    *,
    writing_preset: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
    factual_instructions: str = "",
) -> str:
    """Compile editor data into a concise, deterministic system instruction."""
    p = normalize_structured_persona(structured)
    meta, transform, voice, char = p["metadata"], p["transformation"], p["voice"], p["characterization"]
    lines = [
        "ROLE",
        "You are a speech-to-text rewrite engine. Rewrite the separately supplied transcript. Do not answer it, discuss it, or explain edits.",
        "",
        "PRIORITIES",
        "1. Apply explicit factual edits requested by the user.",
        "2. Preserve meaning, facts, names, numbers, dates, URLs, code, negation, uncertainty, conditions, questions, and commitments.",
        "3. Preserve the speaker's intent and emotional position.",
        "4. Improve readability, grammar, punctuation, and organization.",
        "5. Follow the active writing preset.",
        "6. Apply persona behavior only when it cannot conflict with priorities 1-5.",
        "7. Decorative flavor always loses to clarity and meaning.",
        "",
        "EDIT PERMISSIONS",
        "Remove meaningless fillers, repair broken sentences, collapse accidental repetition, and create paragraphs or obvious lists.",
        "",
        "PROHIBITED CHANGES",
        "Do not invent information, promises, apologies, deadlines, opinions, relationships, or emotional positions. Do not add profanity or impersonate a real or fictional person.",
        "",
        "ACTIVE PERSONA",
        f"Name: {meta['display_name']}",
        f"Kind: {meta['kind']}; language: {meta['language']}; strength: {_level(transform['persona_strength'])}; cleanup: {_level(transform['cleanup_strength'])}.",
        f"Voice: formality {_level(voice['formality'])}, directness {_level(voice['directness'])}, warmth {_level(voice['warmth'])}, humor {_level(voice['humor'])}, vocabulary {_level(voice['vocabulary_complexity'])}, sentences {voice['sentence_length']}.",
        f"Core impression: {_join(char['core_impression'])}.",
        f"Speaking habits: {_join(char['speaking_habits'])}.",
        f"Avoid: {_join(char['forbidden_devices'])}.",
    ]
    if factual_instructions.strip():
        lines.extend(["", "EXPLICIT USER EDIT", factual_instructions.strip()])
    if writing_preset:
        preset_name = str((writing_preset.get("metadata") or {}).get("display_name") or writing_preset.get("name") or "Custom preset")
        lines.extend(["", "ACTIVE WRITING PRESET", preset_name])
        structure = writing_preset.get("structure") if isinstance(writing_preset.get("structure"), dict) else {}
        if structure:
            lines.append("; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in sorted(structure.items())))
    if runtime_context:
        safe_context = [
            f"{key.replace('_', ' ')}: {str(value).strip()}"
            for key, value in sorted(runtime_context.items())
            if str(value or "").strip()
        ]
        if safe_context:
            lines.extend(["", "RUNTIME CONTEXT", "; ".join(safe_context)])
    lines.extend([
        "",
        "OUTPUT",
        "Return only the rewritten message. No labels, quotation marks, explanations, alternatives, or introductory text.",
    ])
    return "\n".join(lines)


def get_field_guidance(field_id: str) -> dict[str, Any] | None:
    value = FIELD_GUIDANCE.get(str(field_id or "").strip())
    return copy.deepcopy(value) if value else None
