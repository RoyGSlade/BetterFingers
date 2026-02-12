# BetterFingers Ready For Launch

Last updated: 2026-02-11

## Current Sitrep

### Green right now

- Tests: `159 passed` via:
  - `python -m pytest -q tests`
- Smoke suite: `14 passed` via:
  - `python -m pytest -q tests -m smoke`
- PyInstaller build succeeds.
- Current packaged payload: `~1469.16 MB`.
- Size budget in CI is `2500 MB` (`.github/workflows/build-installer.yml`, size gate step).
- CI release flow now gates on:
  - full tests
  - smoke suite
  - deprecation check
  - payload size budget
  - NSIS build
  - installer smoke install/uninstall

### Not blocking but important context

- Package is still large mainly due bundled `torch` and `onnxruntime`.
- Remaining warning in tests is external (`pygame/pkg_resources`), not project-owned.
- Runtime bundling should stay as-is for launch stability (avoid user-side wheel/bootstrap failures).

## What Is Left Before Ship

1. Run real installer validation on a clean Windows machine:
   - Fresh install.
   - Upgrade over previous install.
   - Uninstall with default preserve-data behavior.
   - Uninstall with data wipe option: `Uninstall.exe /S /WIPEUSERDATA=1`.
2. Set installer version metadata for release:
   - Update `!define APP_VERSION "1.0"` in `installer/BetterFingers.nsi`.
3. Decide and apply signing path for trust reputation:
   - OV cert, EV cert, or Microsoft Trusted Signing.

## One-Shot Pre-Release Checklist (When You Return)

1. Update release version metadata.
   - Edit: `installer/BetterFingers.nsi`
   - Set: `!define APP_VERSION "<new-version>"`

2. Run validation locally.

```powershell
python -m pytest -q tests
python -m pytest -q tests -m smoke
python -m pytest -q tests -W default 2>&1 | Tee-Object -FilePath build\pytest.log
python tools\check_project_deprecations.py build\pytest.log
pyinstaller BetterFingers.spec -y
```

3. Verify payload size (must be <= 2500 MB).

```powershell
$payloadDir = "dist\BetterFingers"
$sizeBytes = (Get-ChildItem $payloadDir -Recurse -File | Measure-Object Length -Sum).Sum
$sizeMb = [math]::Round($sizeBytes / 1MB, 2)
Write-Host "Payload size: $sizeMb MB"
```

4. Build installer with NSIS.

```powershell
$makensis = "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
& $makensis "installer\BetterFingers.nsi"
```

5. Run installer smoke check.

```powershell
powershell -ExecutionPolicy Bypass -File tools\smoke_installer.ps1 -InstallerPath "dist\BetterFingers_Setup.exe"
```

6. Manual clean-machine validation (required before public release).
   - Install on clean profile/VM.
   - Upgrade install test from prior version.
   - Uninstall default preserve-data test.
   - Uninstall wipe-data test (`/WIPEUSERDATA=1`).
   - Confirm app launch and tray/settings behavior post-install.

7. Release via tag push (CI will enforce gates).

```powershell
git tag vX.Y.Z
git push origin vX.Y.Z
```

## Fast Risk Notes

- If installer passes but Windows trust warnings are high, signing is your highest-impact improvement.
- Do not move `torch`/`onnxruntime` to user-side dynamic download before launch unless you accept higher install/runtime support risk.

## Launch Decision Rule

Ready to launch when all are true:

- CI pipeline passes on tagged build.
- Installer smoke step passes.
- Manual clean-machine installer matrix passes.
- Version metadata is correct.
- Signing decision is made (or consciously deferred with accepted trust warning risk).
