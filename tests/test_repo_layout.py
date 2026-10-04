"""Repository layout guardrails for the backend reorganization.

Python modules are moving out of the repository root into the `backend/`
package (one batch per commit). Two layout rules must hold throughout:

1. The root may only shrink. A new root-level `.py` file fails this test; new
   code belongs under `backend/`. When a batch moves a module, its old root file
   becomes a compatibility alias (see tests/test_module_aliases.py) and stays on
   this list until the alias is deleted -- then remove it here too.
2. Tests stay flat. Windows CI enumerates `tests/test_*.py` non-recursively
   (`.github/workflows/ci.yml`), so a test file moved into a subfolder would
   silently stop running there.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ROOT_MODULES = frozenset({
    "app_paths.py",
    "audio_device_resolver.py",
    "audio_ducker.py",
    "audio_gate.py",
    "audio_input_broker.py",
    "audio_schema.py",
    "audio_status.py",
    "clipboard_capture.py",
    "data_categories.py",
    "data_lifecycle.py",
    "data_paths.py",
    "data_registry.py",
    "dictation_coordinator.py",
    "hardware_report.py",
    "history_store.py",
    "hotkey_manager.py",
    "injection_pacing.py",
    "injector.py",
    "input_binding.py",
    "job_manager.py",
    "llm_engine.py",
    "log_redaction.py",
    "model_manager.py",
    "model_recommender.py",
    "model_runtime_coordinator.py",
    "output_coordinator.py",
    "persona_traits.py",
    "platform_capabilities.py",
    "platform_paths.py",
    "recorder.py",
    "recordings.py",
    "routes_foundry.py",
    "routes_models_resources.py",
    "routes_user_config.py",
    "routes_wake.py",
    "send_policy.py",
    "server.py",
    "server_security.py",
    "store_migration.py",
    "streaming_transcriber.py",
    "support_report.py",
    "text_formatter.py",
    "transcriber.py",
    "tts_engine.py",
    "tts_text.py",
    "upload_safety.py",
    "user_profile_manager.py",
    "utils.py",
    "utterance_history.py",
    "version.py",
    "voice_blend.py",
    "voice_clone_engine.py",
    "voice_clone_qa.py",
    "voice_modulation.py",
    "voice_presets.py",
    "wake_models.py",
    "wake_phrase_fitness.py",
    "wake_pretrigger.py",
    "wake_qwen_capability.py",
    "wake_setup_registry.py",
    "wake_trainer.py",
    "wake_training_data.py",
    "wake_training_service.py",
    "wake_word.py",
})


def test_no_new_root_level_python_modules():
    present = {path.name for path in REPO_ROOT.glob("*.py")}
    unexpected = sorted(present - ROOT_MODULES)
    assert not unexpected, (
        f"New root-level Python modules: {unexpected}. Put new code under backend/ "
        "(see docs/arc/REPO_MAP.md section 6b), not in the repository root."
    )


def test_tests_stay_flat():
    nested = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "tests").rglob("test_*.py")
        if path.parent != REPO_ROOT / "tests"
    )
    assert not nested, (
        f"Test files in subfolders: {nested}. Windows CI only runs tests/test_*.py "
        "at the top level, so these would silently stop running there."
    )
