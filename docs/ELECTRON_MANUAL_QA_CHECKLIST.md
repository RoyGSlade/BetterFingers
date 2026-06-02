# Electron Manual QA Checklist

## Linux Development QA

- [ ] Start from repo root with `.venv` active.
- [ ] Run `cd app`.
- [ ] Run `BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev`.
- [ ] Confirm Electron window opens.
- [ ] Confirm backend card becomes `active`.
- [ ] Confirm sidecar diagnostics show `ready` or clearly explain external backend/port conflict.
- [ ] Confirm runtime status loads.
- [ ] Click `Warm Up STT` and confirm either success or clear subsystem-specific error.
- [ ] Click `Warm Up LLM` and confirm Linux llama-server guidance appears if no runtime is configured.
- [ ] Click `Start Hotkeys` and confirm either started or clear capability/error message.
- [ ] Confirm `/capabilities` shows Linux session data.
- [ ] Confirm diagnostics paths include model path, llama-server path, and debug log path.
- [ ] Confirm debug log tail renders or clearly says no log exists.
- [ ] Confirm runtime error history updates after an intentional warmup failure.
- [ ] Install repo-local llama-server with `python tools/setup_linux_llama_server.py --from /path/to/llama-server`.
- [ ] Restart Electron and confirm diagnostics show `llama_server_exists: yes`.
- [ ] Record audio through hotkey flow.
- [ ] Confirm latest draft appears.
- [ ] Copy cleaned output and paste it into a text editor.
- [ ] Accept draft and confirm status changes to `accepted`.
- [ ] Decline draft and confirm status changes to `declined`.
- [ ] Quit Electron and confirm the backend process exits if Electron owned it.
- [ ] Verify port `8000` and renderer port are not left occupied by BetterFingers ghosts.

## Linux Port Conflict QA

- [ ] Start a dummy process on port `8000`.
- [ ] Start Electron.
- [ ] Confirm diagnostics explain that port `8000` is occupied by a non-BetterFingers process.
- [ ] Stop dummy process.
- [ ] Restart Electron and confirm backend starts normally.

## Windows QA

- [ ] Run `npm run dev` from `app/`.
- [ ] Confirm dev Python resolves to `python` unless `BETTERFINGERS_PYTHON` is set.
- [ ] Confirm dashboard opens and backend starts.
- [ ] Confirm Windows model manager still uses `llama-server.exe`.
- [ ] Confirm existing Windows LLM download flow is still available.
- [ ] Confirm tray icon resolves.
- [ ] Confirm global hotkeys can start recording.
- [ ] Confirm clipboard copy bridge works.
- [ ] Confirm legacy PyInstaller build still works unchanged.

## Packaging QA

- [ ] Run `npm run build`.
- [ ] Run `npm run build:backend`.
- [ ] Run `npm run dist:linux` on Linux.
- [ ] Run `npm run dist:win` on Windows.
- [ ] Confirm packaged app starts the backend from Electron resources.
- [ ] Confirm packaged app passes host and port args to backend.
- [ ] Confirm packaged shutdown kills the backend process.
- [ ] Confirm legacy Python/PyInstaller package remains available until cutover.
