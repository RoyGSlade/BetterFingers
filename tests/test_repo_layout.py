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
    "clipboard_capture.py",
    "hardware_report.py",
    "hotkey_manager.py",
    "injection_pacing.py",
    "injector.py",
    "input_binding.py",
    "llm_engine.py",
    "model_manager.py",
    "model_recommender.py",
    "persona_traits.py",
    "platform_capabilities.py",
    "platform_paths.py",
    "routes_foundry.py",
    "routes_models_resources.py",
    "routes_user_config.py",
    "routes_wake.py",
    "server.py",
    "store_migration.py",
    "streaming_transcriber.py",
    "text_formatter.py",
    "transcriber.py",
    "utils.py",
    "version.py",
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
