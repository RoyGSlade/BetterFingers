@echo off
echo Cleaning previous builds...
rmdir /s /q build dist 2>nul
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

echo Installing Dependencies...
pip install -r requirements.txt

echo.
echo Building BetterFingers...
pyinstaller BetterFingers.spec

echo.
echo Build Complete!
echo You can find the executable in the "dist\BetterFingers" folder.

echo.
echo Building NSIS installer...
set "MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe"
if exist "%MAKENSIS%" (
    "%MAKENSIS%" "installer\BetterFingers.nsi"
    if %errorlevel% neq 0 (
        echo WARNING: NSIS build failed. Check installer\BetterFingers.nsi
    ) else (
        echo Installer created at dist\BetterFingers_Setup.exe
    )
) else (
    echo WARNING: NSIS not found at %MAKENSIS%
    echo Install NSIS to generate BetterFingers_Setup.exe
)

pause
