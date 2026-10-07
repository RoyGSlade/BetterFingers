# Developing BetterFingers

A map of the repository and the rules that keep it easy to work in. Product design lives in [DESIGN.md](../DESIGN.md); platform limits in [docs/release/SUPPORTED_PLATFORMS.md](release/SUPPORTED_PLATFORMS.md).

## Layout

| Path | What lives there |
|---|---|
| `server.py` | FastAPI app, auth middleware, process-wide runtime state and helpers, startup/shutdown, router registration. It serves no routes itself. Entry point for dev (`python server.py`) and for the PyInstaller backend bundle; when run as a script it registers itself as the `server` module so routers' lazy `import server` reach the live state. |
| `version.py` + `VERSION` | The single version source. |
| `config.yaml`, `context_rules.yaml`, `Tutorial_Script.txt` | Data files bundled into the backend from the repo root. |
| `backend/api/routes/` | All HTTP routes and the voice-status WebSocket handler, one router per domain. Handlers reach shared state through a lazy `import server as s` and `s.<name>`; anything that rebinds a server global stays in a `server.py` helper. `backend/api/security.py` holds sidecar auth. |
| `backend/audio/` | Microphone capture: input broker, recorder, device resolution, gating, ducking, status. |
| `backend/stt/` | Speech-to-text: `transcriber` (faster-whisper, CPU thread policy, CUDA probe), streaming, text formatting. |
| `backend/llm/` | Local LLM cleanup engine (llama-server) and persona traits. |
| `backend/tts/` | Text-to-speech (Kokoro), voice blend/modulation, optional voice cloning. |
| `backend/wake/` | Wake-word models, detection, training. |
| `backend/models/` | Model catalog/downloads (`model_manager`), hardware report, recommender. |
| `backend/output/` | Delivery: injector, clipboard capture/restore, injection pacing, send policy. |
| `backend/input/` | Hotkeys and input bindings. |
| `backend/commands/` | Voice/dictation/editing command parsing. |
| `backend/privacy/` | Data locations, registry, lifecycle/wipe, log redaction, upload safety. |
| `backend/config/` | Data-root resolution (`app_paths`, `platform_paths`), profile load/save (`utils`), store migration. |
| `backend/runtime/` | Coordinators: dictation single-flight, output lease, model residency/admission, jobs. |
| `backend/stores/` | Persistent stores: drafts, history DB, recordings, presets, dictionary, macros, app profiles. |
| `backend/services/` | Domain services: app context, library, personas, message rescue, workflows, support report. |
| `backend/domain/` | Pure domain rules with no heavy imports (contracts, gaming policy, actions, library). |
| `backend/platform/` | OS capability detection and audio-privacy adapters. |
| `backend/dev/` | Dev-only engines behind `BETTERFINGERS_DEV_ROUTES`. |
| `tools/` | Developer CLIs; `tools/lib/` holds their libraries (benchmarks, WER, injection matrix). Not bundled. |
| `app/` | Electron app: `src/main` (process, sidecar, hotkeys, updater), `src/preload`, `src/renderer` (Signal Desk UI), `tests/` (Node), `scripts/` (build). |
| `tests/` | Python tests, flat (`tests/test_*.py`). |

## Rules

1. **The repo root is closed.** New Python code goes under `backend/<domain>/`; `tests/test_repo_layout.py` fails on any new root module.
2. **Keep tests flat.** Windows CI enumerates `tests/test_*.py` non-recursively; a test in a subfolder silently stops running there.
3. **Import modules the way the codebase does:** `from backend.stt import transcriber`, `from backend.config.utils import load_profile`. Tests patch `server.<name>` and module objects, so keep local binding names stable when moving code.
4. **Never derive repo or data paths from `__file__`** in new code. Use `backend.config.app_paths` / `backend.privacy.data_paths`; they honour `BETTERFINGERS_DATA_DIR` and frozen builds.
5. **Routes keep their order.** `tests/test_route_table_snapshot.py` pins the route set and the winner of every overlapping path pair. Regenerate (`BF_UPDATE_ROUTE_SNAPSHOT=1`) only for a deliberate API change.
6. **No network before consent, no keystrokes into games.** Delivery decisions go through `backend.domain.gaming_policy` (allowlist) with the foreground app detected at send time.
7. **Every file the app writes under the data root is declared.** A new store, backup shape or download folder goes in `backend/privacy/data_paths.py` (the category in `data_categories.py` decides which wipe removes it) and, if it is a new top-level name, in the uninstaller's `BfSafeDeleteCanonical` list in `app/build/installer.nsh` under the matching checkbox. `tests/test_privacy_inventory_completeness.py` scans the sources for names joined onto the data root and fails on one no category claims; `tests/test_installer_cleanup_contract.py` fails when the inventory and the uninstaller list disagree. An undeclared file also makes a factory reset report failure.
8. **Electron's `userData` is not the data root.** On the packaged Windows app it is `%APPDATA%\betterfingers-electron` (electron-builder's `productName` never reaches `app.asar/package.json`, so Electron uses the package `name`; measured, not assumed), while the backend, `onboarding.json` and the inventory use `%APPDATA%\BetterFingers`. Chromium keeps the renderer's Local Storage (first-run flags, the legacy consent flag), Session Storage and caches there. The backend cannot delete or verify them (Chromium holds them open), so: the factory-reset IPC handler (`app/src/main/rendererState.js`) clears them through the session API, empties every open page's storage and reads it back, and leaves a marker so the next launch deletes the files before Chromium opens them; the names are declared as Chromium-owned in `data_paths.ELECTRON_RUNTIME_NAMES` (the residual sweep skips exactly those, and only if `userData` and the data root coincide, which is what adding a `productName` would do); the uninstaller removes them from both folders (`BfSafeDeleteElectron` is the canonical safe-delete program with one literal changed). Never edit the encoded safe-delete PowerShell by hand; re-derive the Electron one from it.

## Tests

Fast local loop (about 40 s; skips model-loading suites and tests marked `slow`):

```bash
.venv/Scripts/python.exe -m pytest -q -n 8 --dist loadfile -m "not slow" -k "not transcriber and not tts_engine"
```

When you touch speech-to-text or TTS, also run their suites (they use fakes, no real models):

```bash
.venv/Scripts/python.exe -m pytest -q -n 4 tests/test_stt_load_policy.py tests/test_transcriber_confidence.py tests/test_transcriber_device_status.py tests/test_transcriber_hallucination.py tests/test_transcriber_lifecycle.py tests/test_transcriber_structured.py tests/test_streaming_transcriber.py tests/test_tts_engine.py tests/test_tts_engine_blend.py
```

Release smoke gate (also run by the installer workflow): `pytest -q -m smoke`. Slow tests (parity ledger regeneration): `pytest -q -m slow`.

Renderer and Electron tests run from `app/`:

```bash
npm run test:unit
```

The conftest refuses any test that would resolve a data root outside a temp directory, and stops server tests from preloading real models. Keep both guards intact.

## GPU speech-to-text (optional, NVIDIA)

faster-whisper needs NVIDIA's cuBLAS and cuDNN for CUDA. They are not in the lock files (about 1.26 GB); install them into the dev venv when you want GPU dictation:

```bash
.venv/Scripts/python.exe -m pip install --no-deps --require-hashes -r gpu-requirements.txt
```

with `gpu-requirements.txt` containing:

```text
nvidia-cublas-cu12==12.8.4.1 --hash=sha256:47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af
nvidia-cudnn-cu12==9.10.2.21 --hash=sha256:c6288de7d63e6cf62988f0923f96dc339cea362decb1bf5b3141883392a7d65e
```

`backend/stt/cuda_runtime.py` finds them (or a folder named by `BETTERFINGERS_CUDA_RUNTIME_DIR`) and puts them on the process PATH before the first CUDA load; without them the load-time probe falls back to CPU. The first CUDA use on a machine compiles kernels once (about 20 s on an RTX 5070, cached afterwards). The packaged app does not ship this runtime yet.

## Building

`npm run dist:win` builds the renderer, freezes the backend with PyInstaller (`app/scripts/build-backend.js`) and packages the installer. Note that `build-backend.js` empties `app/resources/backend` first.

The installer ships the pinned Systran `base.en` speech model (`backend/stt/bundled_manifest.json`) so first dictation needs no download. `build-backend.js` stages and hash-verifies it before PyInstaller, adds it at `_internal/bundled_models/base.en/`, and re-verifies the frozen copy afterwards, so every backend build must say where the model comes from. Set one of these (first match wins; only the exact value `1` enables a switch):

| Variable | Effect |
|---|---|
| `BETTERFINGERS_BUNDLED_MODEL_SOURCE=<dir>` | Stage from a local snapshot folder (e.g. the Hugging Face cache `snapshots/<revision>` directory). Wins over the other two; a source that fails verification fails the build with no network fallback. |
| `BETTERFINGERS_ALLOW_MODEL_DOWNLOAD=1` | Fetch the pinned revision from Hugging Face (about 148 MB), hash-verified. This is what the release workflow uses. Downloads into a short temp directory (the build also redirects `HF_HOME`/`HF_XET_CACHE` there for every step, so it never writes into your `~/.cache/huggingface`). |
| `BETTERFINGERS_SKIP_MODEL_BUNDLE=1` | Dev only: build without the model, with a loud warning. The result is not release-ready. |

With none of them set the build fails before touching `app/resources/backend`. The signed local build (`npm run dist:win:signed`) inherits the same variables. To check what the backend bundle contains without touching that folder, run PyInstaller with the same arguments and `--distpath/--workpath/--specpath` pointed at a temp directory. Signing is documented in [docs/release/WINDOWS_SIGNING.md](release/WINDOWS_SIGNING.md).

At runtime, `Transcriber._resolve_model_source()` (one function, used by every load path) prefers a verified bundled `base.en`: it hands faster-whisper the bundle directory with `local_files_only=True`, even when a download is allowed, so `base.en` never touches the network. A bundle that fails verification reports `verification_failed` and is never repaired from the network. Other model sizes, and development runs without a bundle, keep the local-only Hub-cache behaviour (only the explicit Download route may fetch). To exercise the bundled path from source, point `BETTERFINGERS_BUNDLED_MODELS_DIR` at a folder that contains `base.en/` (the four verified files); the Whisper model list (`GET /models/whisper`) then reports `base.en` as installed.
