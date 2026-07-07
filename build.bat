@echo off
REM Build the Windows BetterFingers desktop app (Electron shell + PyInstaller
REM backend + NSIS installer). electron-builder produces the installer under
REM app\release\. Requires: Node.js, Python 3, and `pip install pyinstaller`.

setlocal

echo Cleaning previous Electron/backend build output...
rmdir /s /q app\out app\release app\resources\backend app\.electron-backend-build 2>nul

echo.
echo Installing Electron dependencies...
pushd app
call npm install
if %errorlevel% neq 0 (
    echo ERROR: npm install failed.
    popd & exit /b 1
)

echo.
echo Building app (renderer + main), backend (PyInstaller), and installer (NSIS)...
call npm run dist:win
set BUILD_RESULT=%errorlevel%
popd

if %BUILD_RESULT% neq 0 (
    echo ERROR: dist:win failed.
    exit /b %BUILD_RESULT%
)

echo.
echo Build complete. Installer is in app\release\.
endlocal
