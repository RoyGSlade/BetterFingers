import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from utils import get_app_path, get_user_data_path


SCRIPT_FILE_NAME = "Tutorial_Script.txt"
GUIDED_TOUR_MARKER = ".guided_tour_complete"

TAB_KEY_TO_INDEX = {
    "general": 0,
    "input": 1,
    "output": 2,
    "ai": 3,
    "overlays": 4,
    "none": -1,
}


@dataclass
class TourStep:
    title: str
    narration: str
    tab_key: str
    target: str = ""
    action_hint: str = ""


_STRUCTURED_STEP_SPECS = [
    {
        "id": "welcome",
        "title": "Welcome to Better Fingers",
        "tab_key": "none",
        "target": "",
        "narration": (
            "This quick setup tour explains each major settings area, what it controls, "
            "and the few choices most users make first."
        ),
        "action_hint": "Click Start, then use Next and Back as you move through each section.",
    },
    {
        "id": "core_controls",
        "title": "Core Controls",
        "tab_key": "general",
        "target": "hotkey_row",
        "narration": (
            "Set your Master Hotkey, Emergency Stop key, and recording mode. "
            "These define how you start and stop dictation safely."
        ),
        "action_hint": "Set the two hotkeys first, then choose toggle or hold mode.",
    },
    {
        "id": "audio_processing",
        "title": "Audio Processing",
        "tab_key": "general",
        "target": "ducking_check",
        "narration": (
            "Smart Audio Ducking lowers desktop audio during dictation and restores it after. "
            "Tune ducking levels for clear microphone capture."
        ),
        "action_hint": "Enable ducking if games or music interfere with your mic input.",
    },
    {
        "id": "typing_behavior",
        "title": "Typing Behavior",
        "tab_key": "general",
        "target": "typing_behavior",
        "narration": (
            "Set typing speed for natural output, optionally enable Instant Typing, "
            "and add a custom sign-off for repeated messaging patterns."
        ),
        "action_hint": "Use a moderate speed first, then increase after a few test runs.",
    },
    {
        "id": "controller_input",
        "title": "Controller and Input",
        "tab_key": "input",
        "target": "controller_check",
        "narration": (
            "Controller users can enable gamepad input and define single, chord, "
            "or sequence bindings for dictation control."
        ),
        "action_hint": "Map your preferred button combo now if you play with a controller.",
    },
    {
        "id": "auxiliary_keys",
        "title": "Auxiliary Keys",
        "tab_key": "input",
        "target": "aux_keys",
        "narration": (
            "Set Chat Open Key and Voice Mute Key so Better Fingers can coordinate "
            "with in-game chat and push-to-talk behavior."
        ),
        "action_hint": "Match these keys to your game settings exactly.",
    },
    {
        "id": "delivery_pipeline",
        "title": "Delivery Pipeline and Primary Action",
        "tab_key": "output",
        "target": "send_mode_combo",
        "narration": (
            "Choose Review First for approval before send, or Auto Send for direct output. "
            "Primary Action is usually F9 and drives final send actions."
        ),
        "action_hint": "Start with Review First until your workflow is dialed in.",
    },
    {
        "id": "review_tts",
        "title": "Review TTS",
        "tab_key": "output",
        "target": "review_tts",
        "narration": (
            "Configure Review TTS voice and playback speed. You can read highlighted text with "
            "Ctrl + Shift + Space, and F9 also reads highlighted text when no draft is pending."
        ),
        "action_hint": "Test voice and speed once so review playback feels comfortable.",
    },
    {
        "id": "ai_engine",
        "title": "AI Engine",
        "tab_key": "ai",
        "target": "llm_check",
        "narration": (
            "Enable LLM post-processing, pick a persona, and decide whether you want "
            "style refinement on top of raw transcription."
        ),
        "action_hint": "Turn LLM on if you want automatic cleanup and formatting.",
    },
    {
        "id": "model_performance",
        "title": "Model Performance and Residency",
        "tab_key": "ai",
        "target": "model_size_combo",
        "narration": (
            "Choose Whisper model size, quantization, GPU usage, and model residency to balance "
            "speed, memory use, and accuracy."
        ),
        "action_hint": "If hardware is limited, use smaller models and disable keep-loaded options.",
    },
    {
        "id": "overlays",
        "title": "Overlays",
        "tab_key": "overlays",
        "target": "overlay_status",
        "narration": (
            "Set status dot, notification, and preview overlay positions so visual feedback "
            "stays visible without blocking gameplay."
        ),
        "action_hint": "Move overlays to corners that do not interfere with your HUD.",
    },
    {
        "id": "first_setup",
        "title": "First-Time Setup Checklist",
        "tab_key": "none",
        "target": "",
        "narration": (
            "Before daily use, confirm hotkeys, send mode, TTS voice/speed, and overlay positions. "
            "Run one short dictation to validate your full path."
        ),
        "action_hint": "Do one quick record-review-send test now, then save your profile.",
    },
    {
        "id": "closing",
        "title": "You Are Ready",
        "tab_key": "none",
        "target": "",
        "narration": (
            "Setup is complete. You can reopen this guided tour anytime from Settings "
            "to revisit controls or onboard new users."
        ),
        "action_hint": "Use Save after any configuration changes.",
    },
]

_SCRIPT_SECTION_HINTS: Dict[str, Tuple[str, ...]] = {
    "welcome": ("introduction", "welcome"),
    "core_controls": ("master hotkey", "emergency stop", "recording mode", "core controls"),
    "audio_processing": ("audio ducking", "ducking level", "audio processing"),
    "typing_behavior": ("typing speed", "instant typing", "custom sign-off", "typing behavior"),
    "controller_input": ("controller support", "controller binding mode", "controller"),
    "auxiliary_keys": ("chat open key", "voice mute key"),
    "delivery_pipeline": ("send mode", "primary action hotkey", "primary action", "delivery pipeline"),
    "review_tts": ("review tts voice", "review tts speed", "review tts"),
    "ai_engine": ("llm post-processing", "persona selection", "ai engine"),
    "model_performance": ("whisper model size", "quantization level", "gpu acceleration", "model memory residency"),
    "overlays": ("status indicator position", "notification overlay position", "preview overlay position", "overlays"),
    "first_setup": ("closing",),
}


def _default_script_path():
    return os.path.join(get_app_path(), SCRIPT_FILE_NAME)


def _normalize_script_heading(text):
    value = str(text or "").strip().lower()
    return " ".join(value.split())


def _parse_tutorial_script(script_path):
    path = str(script_path or "").strip()
    if not path or not os.path.exists(path):
        return {}

    sections = {}
    current_heading = ""
    current_lines = []

    def flush_section():
        heading = _normalize_script_heading(current_heading)
        if not heading:
            return
        body = " ".join(piece.strip().strip('"').strip("'") for piece in current_lines if piece and piece.strip())
        body = " ".join(body.split()).strip()
        if body:
            sections[heading] = body

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = str(raw_line or "").strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                if not line.startswith('"') and not line.startswith("'"):
                    flush_section()
                    current_heading = line
                    current_lines = []
                    continue
                current_lines.append(line)
            flush_section()
    except Exception as exc:
        logging.warning("Failed parsing tutorial script '%s': %s", path, exc)
        return {}

    return sections


def _resolve_script_override(step_id, script_sections):
    if not script_sections:
        return ""
    for hint in _SCRIPT_SECTION_HINTS.get(step_id, ()):
        normalized_hint = _normalize_script_heading(hint)
        if normalized_hint in script_sections:
            return script_sections.get(normalized_hint, "")
    return ""


def _marker_path() -> str:
    return os.path.join(get_user_data_path(), GUIDED_TOUR_MARKER)


def has_completed_guided_tour() -> bool:
    return os.path.exists(_marker_path())


def mark_guided_tour_complete() -> None:
    path = _marker_path()
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("guided_tour_complete=true\n")
    except Exception as exc:
        logging.error("Failed to persist guided tour marker: %s", exc)


def reset_guided_tour_marker() -> None:
    path = _marker_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as exc:
        logging.error("Failed to clear guided tour marker: %s", exc)


def load_guided_tour_steps(script_path: str = "") -> List[TourStep]:
    """Returns tour steps with optional script-based narration overrides."""
    source_path = str(script_path or "").strip() or _default_script_path()
    script_sections = _parse_tutorial_script(source_path)
    steps = []
    for spec in _STRUCTURED_STEP_SPECS:
        override = _resolve_script_override(spec.get("id", ""), script_sections)
        if override:
            narration = f"{override} {spec['narration']}".strip()
        else:
            narration = spec["narration"]
        steps.append(
            TourStep(
                title=spec["title"],
                narration=narration,
                tab_key=spec["tab_key"],
                target=spec["target"],
                action_hint=spec.get("action_hint", ""),
            )
        )
    return steps


def build_legacy_tutorial_script() -> List[dict]:
    # This might be used by the frontend (main.py) to run the tour
    script: List[dict] = []
    for step in load_guided_tour_steps():
        message = step.narration
        if step.action_hint:
            message = f"{message} Try this: {step.action_hint}"
        # Estimate wait time based on word count
        words = len(message.split())
        wait_seconds = max(3.0, min(18.0, float(words) / 2.5))
        
        script.append(
            {
                "msg": message,
                "tab": TAB_KEY_TO_INDEX.get(step.tab_key, -1),
                "target": step.target,
                "wait": wait_seconds,
            }
        )
    return script
