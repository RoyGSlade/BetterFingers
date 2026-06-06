# Claude — Architecture & Strategy Agent Log

**Role**: Architecture, API boundaries, structural patterns, system design, dev tooling  
**Protocol ref**: [AGENTS_RULING.md](../AGENTS_RULING.md)

---

## Active Assignments

| ID | Task | Status | Branch | Notes |
| :- | :--- | :----- | :----- | :---- |
| C-001 | Dev desktop shortcut — Linux launcher | ✅ Complete | main | See Session Log below |
| C-002 | Architecture pass + Linux test stabilisation | ✅ Complete | main | See Session Log below |

---

## Session Log

---

### [C-001] Dev Desktop Shortcut
- **Date**: 2026-06-05 → 2026-06-06
- **Scope**: Create a one-click dev launcher on the Cinnamon desktop that always runs from latest source, cleans up all processes on close, and leaves no ghost processes in the background.

#### What was done
1. **Fixed `BetterFingers.desktop`** — paths were hardcoded to original developer's home (`/home/roygslade/Desktop/BetterFingers`). Updated `Exec=`, `Path=`, and `Icon=` to the correct `donaven/BetterFingers-1` paths.
2. **Added `HUP` to cleanup trap** in `scripts/start-betterfingers-linux.sh` — ensures cleanup fires when terminal window is closed (gnome-terminal sends SIGHUP on close, not just INT/TERM).
3. **Created `~/Desktop/BetterFingers-Dev.desktop`** — copy of the fixed file on the actual desktop, `chmod +x` and `gio set metadata::trusted true` so Cinnamon recognises it.
4. **Diagnosed and fixed gnome-terminal cgroup bug** — on kernel 6.17, `gnome-terminal` via `Terminal=true` silently fails with VTE scope creation error. Switched to `Terminal=false` with `Exec=systemd-run --scope --user -- gnome-terminal -- <script>`. The `systemd-run --scope` creates a valid user scope first, which VTE can then use as a parent cgroup.
5. **Confirmed `.venv` setup required** — venv was absent, user ran `pip install -r requirements.txt` to resolve.

#### Files changed
- `BetterFingers.desktop` (project root)
- `scripts/start-betterfingers-linux.sh` (line 176 — trap)
- `~/Desktop/BetterFingers-Dev.desktop` (new, on OS desktop)

#### Launch behavior after fix
- Click shortcut → systemd scope created → gnome-terminal window opens → sudo prompt → backend starts on :8000 → Electron hot-reload dev server starts
- Close app → Electron exits → `wait` returns → EXIT trap kills all process groups
- Close terminal window → SIGHUP → EXIT trap kills all process groups
- Click shortcut while running → `kill_previous_launch` kills old instance first → clean restart with latest code
- Frontend edits → electron-vite hot-reloads automatically
- Backend edits → click shortcut to restart with updated code

#### Blockers encountered
- gnome-terminal VTE cgroup failure on Linux kernel 6.17 (see above fix)
- No `.venv` present — user resolved manually

---

---

### [C-002] Architecture Pass + Linux Test Stabilisation
- **Date**: 2026-06-06
- **Scope**: Architecture/API boundary decision for platform-specific imports + fixing all remaining pytest failures. Picked up from GPT's P-002 handoff.

#### Decision: inline platform stub (no adapter module)
The scope of the platform problem was narrow: `pydirectinput` uses `ctypes.windll` at import time. All other methods (`keyboard`, `pyperclip`) are already cross-platform. A full platform adapter module would be over-engineering. Instead, a `sys.platform == "win32"` guard in `injector.py` stubs out `pydirectinput` on Linux with a `types.SimpleNamespace` no-op. This keeps the module's public API identical on both platforms, all existing mocks still work, and Windows production behavior is completely unchanged.

#### What was done
1. **`injector.py`** — wrapped `import pydirectinput` in `sys.platform == "win32"` guard; Linux gets a `SimpleNamespace` stub with `PAUSE`, `keyDown`, `keyUp`, `press` no-ops.
2. **`sudo apt-get install python3-tk`** — resolved 11 collection errors (all `main.py`/overlay tests import `tkinter`).
3. **`tests/test_hotkey_manager_tts.py`** — rewrote 3 tests that patched `hotkey_manager.keyboard.add_hotkey` / `remove_hotkey`. Those hooks no longer exist in the module (`start()` now says `# Native hooks removed` — hotkeys are handled by Electron IPC). Tests now assert actual current behavior: `_running` state, hotkey normalization via `_normalize_hotkey`, and `_review_tts_trigger()` callback dispatch.
4. **`tests/test_settings_external_url.py`** — added `create=True` to `@patch("settings.os.startfile", ...)` so the patch works on Linux where `os.startfile` doesn't exist.
5. **`tests/test_server_drafts.py`** `setUp`/`tearDown` — added `server.tts_engine` to the saved/restored global set. An earlier TTS test was leaving `tts_engine` populated; its `on_stop` callback then fired `draft_tts_stopped` into later tests' `broadcast_status_threadsafe` mocks, causing ordering-dependent failures.

#### Files changed
- `injector.py` (lines 6–17 — import block)
- `tests/test_hotkey_manager_tts.py` (3 test methods rewritten)
- `tests/test_settings_external_url.py` (1 patch decorator — `create=True`)
- `tests/test_server_drafts.py` (`setUp` line ~117, `tearDown` line ~129)

#### Result
**222 passed, 1 skipped, 0 failed** (full suite, `.venv/bin/python -m pytest`)

#### Blockers / Handoffs
- None. Baseline is clean. @GPT: can proceed with any new implementation tasks. @Gemini: no UX/audio impact from these changes.

---

## Reporting Checklist (before marking any task complete)
- [ ] Architectural side-effects on existing modules documented
- [ ] Files changed listed with line-level notes for anything non-obvious
- [ ] Blockers cleared or handed off to @Gemini / @GPT
- [ ] Entry added to [agent_blackboard.md](../agent_blackboard.md)
- [ ] Test impact noted in [agent_test_log.md](../agent_test_log.md) if code-touching
