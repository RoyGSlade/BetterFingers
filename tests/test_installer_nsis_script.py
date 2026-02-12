from pathlib import Path


def _load_script() -> str:
    script_path = Path(__file__).resolve().parents[1] / "installer" / "BetterFingers.nsi"
    return script_path.read_text(encoding="utf-8")


def test_nsis_script_exists():
    script_path = Path(__file__).resolve().parents[1] / "installer" / "BetterFingers.nsi"
    assert script_path.exists(), "NSIS installer script is missing."


def test_nsis_installs_per_user_appdata():
    script = _load_script()
    assert 'InstallDir "$LOCALAPPDATA\\Programs\\BetterFingers"' in script
    assert "RequestExecutionLevel user" in script


def test_nsis_has_force_close_and_upgrade_uninstall_flow():
    script = _load_script()
    assert "taskkill.exe" in script
    assert "/IM BetterFingers.exe /F" in script
    assert "/IM llama-server.exe /F" in script
    assert "UninstallPreviousVersion" in script
    assert "BetterFingers_is1" in script


def test_nsis_uninstall_preserves_data_by_default_with_optional_wipe():
    script = _load_script()
    assert 'Section "Uninstall" SEC_UNINSTALL' in script
    assert 'Section /o "Remove user data (%APPDATA%\\\\BetterFingers)" SEC_UNINSTALL_USERDATA' in script
    assert "/WIPEUSERDATA=" in script


def test_nsis_offers_optional_first_time_model_prefetch():
    script = _load_script()
    assert 'SectionGroup /e "First-time model prefetch (optional)" SEC_MODEL_PREFETCH' in script
    assert "--prefetch-mvp" in script
    assert "--prefetch-llm-model gemma-3-4b-q4" in script
    assert "--prefetch-whisper-model base.en" in script
    assert "--prefetch-tts-assets" in script
