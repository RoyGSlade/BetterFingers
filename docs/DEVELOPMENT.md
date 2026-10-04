# Developing BetterFingers

A map of the repository and the rules that keep it easy to work in. Product design lives in [DESIGN.md](../DESIGN.md); platform limits in [docs/release/SUPPORTED_PLATFORMS.md](release/SUPPORTED_PLATFORMS.md).

## Layout

| Path | What lives there |
|---|---|
| `server.py` | FastAPI app, process-wide runtime state, startup/shutdown, and routes not yet extracted. Entry point for dev (`python server.py`) and for the PyInstaller backend bundle. |
| `version.py` + `VERSION` | The single version source. |
| `config.yaml`, `context_rules.yaml`, `Tutorial_Script.txt` | Data files bundled into the backend from the repo root. |
| `backend/api/routes/` | FastAPI routers, one per domain. `security.py` holds sidecar auth. |
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

## Building

`npm run dist:win` builds the renderer, freezes the backend with PyInstaller (`app/scripts/build-backend.js`) and packages the installer. Note that `build-backend.js` empties `app/resources/backend` first. To check what the backend bundle contains without touching that folder, run PyInstaller with the same arguments and `--distpath/--workpath/--specpath` pointed at a temp directory. Signing is documented in [docs/release/WINDOWS_SIGNING.md](release/WINDOWS_SIGNING.md).
