# Electron Feature Parity Map

## Purpose

This map tracks how original BetterFingers desktop functionality moves into the Electron shell while the Python FastAPI backend remains the behavior source of truth.

## Status Labels

- `electron-ready`: Already available in Electron.
- `backend-ready`: Backend behavior exists, Electron UI still needed.
- `portable`: Should work across Windows/Linux/macOS with normal abstraction.
- `linux-limited`: Works partially on Linux or needs explicit fallback.
- `windows-only`: Original behavior depends on Windows APIs.
- `defer`: Keep out of parity milestone unless product direction changes.

## Feature Inventory

| Original Feature | Current Source | Electron Destination | Status | Notes |
| --- | --- | --- | --- | --- |
| Backend process lifecycle | `server.py`, Electron sidecar | Electron main process + diagnostics panel | electron-ready | Electron starts/stops backend and reports sidecar state. |
| Health/runtime dashboard | `server.py` | Dashboard top cards and runtime panel | electron-ready | `/health`, `/runtime/status`, `/capabilities`. |
| Runtime warmup | `server.py` | Dashboard warmup buttons | electron-ready | STT, LLM, hotkeys return structured results. |
| Runtime diagnostics | `utils.py`, `model_manager.py`, `server.py` | Dashboard diagnostics panel | electron-ready | Log tail, runtime errors, model paths, sidecar status. |
| Recording hotkeys | `hotkey_manager.py`, `recorder.py` | Backend runtime + Electron controls | backend-ready | Start hotkeys exists; deeper hotkey settings pending. |
| Recording to draft | `main.py`, `transcriber.py`, `llm_engine.py` | Latest Draft panel | electron-ready | First slice complete; no-audio gate and retry pending. |
| No-audio gate | `audio_gate.py`, `main.py` | Backend draft pipeline | portable | Needs parity in `process_recording_result`. |
| LLM cleanup presets | `llm_engine.py`, profile config | Review/settings UI | backend-ready | Basic True Janitor path exists; preset UI pending. |
| Draft accept/decline | `preview_overlay.py`, `main.py` | Latest Draft panel | electron-ready | Status update only; send path pending. |
| Draft send/type/paste | `injector.py`, `main.py` | Send endpoint + Electron actions | linux-limited | Linux fallback should default to copy-only unless injection is supported. |
| Clipboard copy | Electron IPC | Latest Draft panel | electron-ready | Secure preload bridge. |
| Clipboard snapshot/restore | `clipboard_capture.py` | Backend selected-text/read-aloud flow | windows-only | Rich restore currently Windows-focused. |
| Primary action hotkey | `main.py`, `hotkey_manager.py` | Backend hotkey behavior + settings UI | linux-limited | Needs accepted-draft send and selected-text TTS parity. |
| Emergency stop | `main.py`, `injector.py`, `tts_engine.py` | Backend endpoint + UI/hotkey | portable | Needs endpoint and state cleanup. |
| Settings window | `settings.py`, mixins | Electron settings page | portable | Needs profile endpoints and UI. |
| Profiles | `utils.py`, `user_profile_manager.py` | Settings/profile UI | backend-ready | Basic `/profile` exists; list/switch/create/delete pending. |
| Model selection/downloads | `model_manager.py`, `transcriber.py` | Model management page | linux-limited | Windows downloads preserved; Linux llama-server is manual/repo-local. |
| Linux llama-server | `model_manager.py`, setup script | Diagnostics/model management UI | backend-ready | Repo-local and env override supported. |
| Whisper model management | `transcriber.py`, `settings.py` | Model management page | portable | Endpoints/UI pending. |
| Model keep-loaded flags | `main.py`, profile config | Runtime/model settings | portable | Needs endpoint parity and unload actions. |
| Review overlay | `preview_overlay.py` | Electron Review panel or mini window | portable | Latest Draft is first slice; edit/rewrite/TTS pending. |
| Rewrite actions | `preview_overlay.py`, `main.py` | Review panel | portable | Needs endpoints and UI. |
| Review TTS/read aloud | `tts_engine.py`, `main.py` | Review panel + settings | linux-limited | Backend currently mock in `server.py`; real playback pending. |
| Voice clone/list voices | `server.py`, `tts_engine.py` | TTS settings | backend-ready | `/tts/voices` works cross-platform; full TTS pending. |
| Notification overlay | `notification_overlay.py` | Electron toast/mini window | linux-limited | Decide native notification vs Electron always-on-top. |
| Status overlay | `overlay.py` | Dashboard/mini status window | linux-limited | Windows overlay behavior may not translate directly to Wayland. |
| Splash screen | `splash.py` | Optional Electron loading screen | defer | Only needed if startup becomes slow. |
| Guided tour | `guided_tour.py`, settings tour mixin | Electron onboarding | portable | Pending. |
| Audio ducking | `audio_ducker.py` | Settings/capability UI | windows-only | Linux should show unsupported unless new backend is added. |
| Audio input device selection | `recorder.py`, profile config | Settings/audio page | portable | Endpoint/UI pending. |
| Live audio meter | `recorder.py` chunk callbacks | Dashboard/review status | portable | Pending. |
| Project/graph tools | `project_generator.py`, graph endpoints | Advanced Electron page | defer | Existing endpoints need product decision. |
| Intent state | `intent_engine.py`, endpoints | Advanced Electron page | defer | Existing endpoints need product decision. |
| Packaging | PyInstaller/Electron Builder | Electron dist path | backend-ready | Electron package path exists; full Linux/Windows smoke pending. |

## Old Overlay Migration Decision

| Old Component | Electron Direction |
| --- | --- |
| `overlay.py` | Replace with dashboard state first; consider Electron mini status window later. |
| `notification_overlay.py` | Replace with Electron toast/native notification system. |
| `preview_overlay.py` | Replace with Review panel first; optional always-on-top review window later. |
| `splash.py` | Defer unless startup UX needs it. |
| `settings.py` | Replace with Electron Settings page. |

## Linux Limitation Notes

- Wayland may block global hotkeys and input injection depending on compositor permissions.
- Rich clipboard snapshot/restore is Windows-only today.
- Audio ducking is Windows-only today.
- Linux LLM runtime requires a local `llama-server` binary via `.betterfingers/llama-server/bin/llama-server` or `BETTERFINGERS_LLAMA_SERVER`.
- Linux send behavior should default to safe copy-only until input injection is validated.
