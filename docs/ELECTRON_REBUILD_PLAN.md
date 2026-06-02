# Electron Rebuild Plan

## What Changed

BetterFingers now has a second desktop shell in `app/`:

- The Electron UI lives in `app/src/renderer/`.
- The Electron main process lives in `app/src/main/`.
- The Python FastAPI backend is still the same `server.py` entrypoint.
- The legacy PyInstaller desktop build at the repo root stays untouched.

## How to Rebuild The Electron Shell

From `app/`:

```bash
npm run dev
npm run build
npm run build:backend
npm run dist
npm run dist:win
npm run dist:linux
```

### Dev Flow

`npm run dev` starts Electron and launches the backend with:

```bash
python server.py --host 127.0.0.1 --port 8000
```

The dashboard waits for `GET http://127.0.0.1:8000/health` before marking the backend ready.

### Packaged Flow

`npm run dist*` does two separate builds:

1. `electron-vite build` compiles the Electron app into `app/out/`.
2. `npm run build:backend` packages `server.py` into `app/resources/backend/` with PyInstaller.
3. `electron-builder` packages the Electron shell and copies `resources/backend/` into the app bundle as `resources/backend/`.

In packaged mode, the Electron shell starts the backend executable from `process.resourcesPath/backend/`.

## Backend Binary Layout

The packaged backend is expected to be named:

- `betterfingers-backend.exe` on Windows
- `betterfingers-backend` on Linux

The startup code also accepts fallback names so packaging can evolve without breaking launch behavior.

## What Stays The Same

- `BetterFingers.spec` stays as the current Python desktop build.
- `build.bat` stays as the existing PyInstaller entrypoint.
- The Electron shell is additive and should not be used as a replacement for the current Python build until that migration is explicitly planned.

## Operational Notes

- The Electron app expects port `8000` to be free so it can own the backend process.
- Closing the Electron app quits the backend process too.
- The tray icon is present for quick access to the dashboard and the quit action, but it does not keep the backend alive after app exit.
- Linux setup commands depend on your current directory:
  - From the repo root, use `requirements.txt`.
  - From `app/`, use `../requirements.txt`.
