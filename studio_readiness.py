"""Studio first-run readiness audit.

This is intentionally lightweight: no model loads, no generation. It checks the local files,
tool environments, and ownership/readability conditions that determine whether the first
Studio run will use real departments or honest fallbacks.
"""

from __future__ import annotations

import os

import model_manager
import studio_ambience
import studio_image_backend
import studio_media_models
import studio_music


DEFAULT_REQUIRED_LLM = ("gemma-4-e4b-q4", "gemma-4-12b-q4")
DEFAULT_REQUIRED_MEDIA = ("chatterbox", "ace-step-1-5", "stable-audio-open-small")


def audit_studio_readiness():
    checks = []

    for model_id in DEFAULT_REQUIRED_LLM:
        info = model_manager.AVAILABLE_MODELS.get(model_id, {})
        file_status = model_manager.get_model_file_status(model_id)
        ok = bool(file_status.get("ok"))
        attention = list(file_status.get("attention") or [])
        # Writable is not required to load, but it matters for first-run repair and replacement.
        severity = "ok" if ok and not attention else ("warning" if ok else "error")
        checks.append({
            "id": f"llm:{model_id}",
            "kind": "llm",
            "name": info.get("name", model_id),
            "ok": ok,
            "severity": severity,
            "path": file_status.get("path"),
            "attention": attention,
            "details": file_status,
        })

    image_installed = studio_image_backend.image_model_installed()
    checks.append({
        "id": f"image:{studio_image_backend.DEFAULT_IMAGE_MODEL}",
        "kind": "image",
        "name": "Studio image model",
        "ok": bool(image_installed and studio_image_backend.diffusers_available()),
        "severity": "ok" if image_installed and studio_image_backend.diffusers_available() else "warning",
        "path": studio_image_backend.image_model_path(),
        "attention": _attention(
            (image_installed, "image_model_missing"),
            (studio_image_backend.diffusers_available(), "diffusers_or_cuda_unavailable"),
        ),
    })

    for model_key in DEFAULT_REQUIRED_MEDIA:
        entry = studio_media_models.MEDIA_MODELS.get(model_key, {})
        installed = studio_media_models.model_installed(model_key)
        checks.append({
            "id": f"media:{model_key}",
            "kind": entry.get("kind", "media"),
            "name": entry.get("name", model_key),
            "ok": bool(installed),
            "severity": "ok" if installed else "warning",
            "path": studio_media_models.model_path(model_key),
            "attention": [] if installed else ["media_model_missing"],
        })

    stable_tools = studio_ambience.stable_audio_tools_installed()
    stable_backend = studio_ambience.make_ambience_backend() is not None
    checks.append({
        "id": "tools:stable-audio",
        "kind": "tools",
        "name": "Stable Audio Tools",
        "ok": bool(stable_tools and stable_backend),
        "severity": "ok" if stable_tools and stable_backend else "warning",
        "path": str(studio_ambience.stable_audio_tool_root()),
        "attention": _attention(
            (stable_tools, "stable_audio_tools_missing"),
            (stable_backend, "stable_audio_backend_unavailable"),
        ),
    })

    ace_tools = studio_music.ace_tools_installed()
    ace_backend = studio_music.make_music_backend() is not None
    checks.append({
        "id": "tools:ace-step",
        "kind": "tools",
        "name": "ACE-Step composer",
        "ok": bool(ace_tools and ace_backend),
        "severity": "ok" if ace_tools and ace_backend else "warning",
        "path": str(studio_music.ace_tool_root()),
        "attention": _attention(
            (ace_tools, "ace_step_tools_missing"),
            (ace_backend, "ace_step_backend_unavailable"),
        ),
    })

    errors = sum(1 for check in checks if check["severity"] == "error")
    warnings = sum(1 for check in checks if check["severity"] == "warning")
    return {
        "ok": errors == 0,
        "ready_for_first_run": errors == 0,
        "warnings": warnings,
        "errors": errors,
        "checks": checks,
        "models_dir": model_manager.get_models_dir(),
        "cwd": os.getcwd(),
    }


def _attention(*pairs):
    return [name for ok, name in pairs if not ok]
