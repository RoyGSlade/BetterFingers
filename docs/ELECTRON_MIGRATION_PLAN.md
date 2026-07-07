# Electron Migration — Remaining Work & UI/UX Plan

Status as of 2026-07-07, after removal of Studio Mode. Scope: Windows + Linux desktop
(macOS gaps noted but out of scope).

## Progress log (branch: electron-migration)

- **Studio Mode removed** — 38 files, ~14k lines.
- **Phase 1.3 sidecar hardening — DONE.** Unified `app/src/main/config.js`; fixed
  hotkeys.js hardcoded host/port; version handshake now gates on API `schema_version`;
  post-startup health monitor with bounded auto-restart + `crashed` state; logs
  retained across restarts; sidecar status pushed to renderer with a generalized banner.
- **Phase 1.1 Windows packaging — MOSTLY DONE (unverified build).** `build-backend.js`
  now resolves python3/python correctly and adds the `--collect-all`/`--hidden-import`
  flags the sidecar's deps need; `package.json` bundles `images/` too; `build.bat`
  rewritten to drive `npm run dist:win`; legacy `BetterFingers.spec` + standalone
  `installer/BetterFingers.nsi` + its test retired (electron-builder generates the NSIS
  installer). NOT YET VERIFIED end-to-end — needs a Windows box with PyInstaller.
  Model-prefetch moves to the first-run wizard (2.6).
- **Phase 1.2 Linux launch — DONE (dev launcher).** De-sudo'd
  `start-betterfingers-linux.sh` (backend runs as the user; fixes the root-owned-files
  gotcha); `BetterFingers.desktop` is now a template + `scripts/install-linux-shortcut.sh`
  fills in the real repo path. AppImage target already configured in package.json.
- **Phase 2.1 Push-to-talk / global hotkeys — DONE (Windows/X11; Wayland degrades).**
  Backend: added `/runtime/recording/start` + `/stop` (idempotent) and
  `HotkeyManager.request_start`; smoke-tested live. Electron: rewrote `hotkeys.js`
  around `uiohook-napi` (N-API, key-down + key-up) so PTT works — key-down starts,
  key-up stops, with auto-repeat suppression and modifier-order-proof release.
  Toggle mode debounced. Falls back to Electron `globalShortcut` (toggle-only) when
  uiohook can't load/start (Wayland, missing libXtst). Capability query exposed via
  `hotkeys:get-capabilities` for the UI. Also fixed a **latent bundler bug**: `config.js`
  wasn't a build input, so `require('./config')` resolved to nothing — would have broken
  even dev launch since Phase 1.3. Native module asarUnpack'd for packaging.
  Remaining UI touch: surface `pttSupported` in the recording-mode setting (Phase 3).

### Parallel tracks — outcome

The backend agent's worktree was accidentally branched from a stale base and it
died with its work uncommitted. All of its changes were salvaged and re-applied
onto the correct base (4 files applied clean; model_manager.py/requirements.txt/
server.py hand-ported), so nothing was lost.
- **Phase 2.2 injection matrix — DONE (salvaged).** injector.py runtime backend
  selection (pydirectinput → xdotool → wtype/ydotool → paste); platform_capabilities
  reports `injection_method`/`supports_typing` via /capabilities; best-effort Wayland
  clipboard.
- **Phase 2.5 backend gaps — DONE (salvaged).** Real `/models/unload` (frees memory +
  gc), `/project/export` → Downloads (XDG-aware), audio_ducker pactl Linux backend,
  requirements platform markers, standardized `sys.platform == 'win32'`. +15 new tests.
- Dead agent worktree left in place (harness-locked); harmless, on its own branch.
- **Frontend progress (solo loop):**
  - **2.1 UI — DONE:** PTT availability note; fixed the `ptt` vs `push_to_talk` value
    mismatch that would have silently disabled push-to-talk; injection method surfaced.
  - **2.3 — DONE:** review-overlay rewrite preset picker (Clearer/Shorter/Tone).
  - **2.4 — DONE:** state-driven tray icon + menu; in-app toast system (wired to
    sidecar crash/unhealthy pushes); status overlay was already draggable, now its
    position persists across launches (on-screen-validated).
  - **Phase 3 — partial:** removed 3 dead DOM refs. Theming was already fully wired
    (audit was wrong); high-contrast/accent/density all apply at startup.
  - **Remaining:** 2.6 (first-run policy/tour/model wizard, state stored client-side),
    Phase 3 (error/loading states on more paths, a11y: tab roles/focus trap).

---


## Where things stand

- **Backend (server.py)**: fully decoupled from the tkinter app — no imports of main.py or
  tkinter anywhere in the sidecar stack. ~56 endpoints covering health, warmup, recording,
  drafts (full CRUD + rewrite/TTS/send), profiles, LLM/Whisper/TTS models, personas,
  diagnostics/doctor, capabilities, and the voice-status WebSocket. Production-ready on
  Windows and Linux X11.
- **Electron app (app/)**: core plumbing works — sidecar spawn/health-poll/kill, single
  instance, tray, status + review overlay windows, 4-tab renderer (Dashboard / Settings /
  Models / Diagnostics), profile CRUD, model management, persona wizard.
- **Legacy tkinter app (main.py + overlays + Flet settings)**: still in-tree, still the only
  fully-working Windows experience. Keep until Phase 2 parity lands, then delete.

---

## Phase 1 — Ship it: packaging & launch (P0, blocks everything)

### 1.1 Windows build pipeline
- `build.bat`, `BetterFingers.spec`, and `installer/BetterFingers.nsi` all package the **old
  tkinter app**. The real pipeline is `app/scripts/build-backend.js` (PyInstaller of
  server.py → `app/resources/backend/`) + `npm run dist:win` (electron-builder NSIS).
- To do:
  - [ ] Verify `build-backend.js` produces a working `betterfingers-backend.exe` on Windows
        (it bundles config.yaml, context_rules.yaml, images, assets).
  - [ ] Either retire `installer/BetterFingers.nsi` in favor of electron-builder's NSIS
        config in `app/package.json`, or rewrite it for the Electron layout. The current
        one kills processes by old exe name, uses `_internal\images` icon paths, and calls
        `BetterFingers.exe --prefetch-mvp` — a CLI that the Electron exe doesn't have.
  - [ ] Model prefetch: move from installer sections to a **first-run download flow in the
        app** (see 3.1), or add `--prefetch-*` args to the backend binary and have the
        installer call that instead.
  - [ ] Retire `build.bat` + `BetterFingers.spec` once the above works (or repoint them).

### 1.2 Linux launch & packaging
- `BetterFingers.desktop` hardcodes `/home/donaven/Desktop/BetterFingers-1/...` — broken on
  every other machine. `scripts/start-betterfingers-linux.sh` requires **sudo** (runs the
  backend as root for keyboard hooks) and gnome-terminal.
- To do:
  - [ ] `npm run dist:linux` AppImage with bundled backend binary; make it the primary
        install path, replacing the shell-script launcher for end users.
  - [ ] Kill the sudo requirement: hotkeys already flow through Electron IPC (see 2.1), so
        the backend does not need root. Where evdev access is still wanted (X11 `keyboard`
        typing), document `usermod -aG input` + udev rule instead of sudo.
  - [ ] Regenerate `.desktop` file at install time with real paths (AppImage handles this
        via AppImageLauncher; otherwise template it).
  - [ ] Keep the dev scripts, but strip the sudo path and the hardcoded terminal.

### 1.3 Sidecar lifecycle hardening
- [ ] **Bug**: `app/src/main/hotkeys.js` hardcodes `127.0.0.1:8000` and doesn't receive the
      host/port env or the auth token path used elsewhere — unify config in one module.
- [ ] No health monitoring after startup: if the backend dies, the UI silently shows stale
      data. Add a periodic ping, an "engine offline — restart?" banner, and one automatic
      restart attempt.
- [ ] Persist sidecar logs across restarts (currently cleared on every start) — keep last N
      sessions in userData.
- [ ] Version handshake is a hardcoded `0.1.0` string in sidecar.js; read from package.json
      / a shared version file, and make mismatch state block the UI with a clear message
      instead of limping along.

---

## Phase 2 — Feature parity with the legacy app (P1)

### 2.1 Push-to-talk & global hotkeys (biggest functional gap)
- Electron `globalShortcut` fires on key-down only — **push-to-talk cannot work** (no
  release event). The legacy app's PTT mode is a headline feature.
- The backend's `hotkey_manager` has native keyboard hooks disabled ("running via Electron
  IPC"), so hotkeys don't work at all if the window is closed to tray on Wayland.
- Plan:
  - [ ] Windows + Linux X11: add `uiohook-napi` (or similar) in the Electron main process
        for key-down/key-up pairs → PTT via `/runtime/recording/toggle` start/stop.
  - [ ] Wayland: no global key hooks exist by design. Ship honest fallbacks — tray-click
        toggle, in-app button, and optionally the XDG GlobalShortcuts portal where
        supported. Keep the existing Wayland warning in settings, but make it state-driven
        from `/capabilities` instead of hardcoded HTML.
  - [ ] Controller/gamepad path (backend pygame thread) still works headless — expose a
        **Controller section in Settings** (enable, binding style single/chord/sequence,
        live mapping capture, axis threshold, sequence window). The backend already
        supports it; the Electron UI has nothing.

### 2.2 Text injection on Linux
- `injector.py` stubs pydirectinput off-Windows; "type" mode on X11 needs evdev perms;
  Wayland is a no-op. Paste mode works everywhere.
- [ ] Add an injection backend matrix: Windows=pydirectinput → X11=xdotool or evdev →
      Wayland=`wtype`/`ydotool` if present → clipboard-paste fallback.
- [ ] Surface the *actual* available method in Settings → Send & Injection (from
      `/capabilities`) instead of letting "type" silently fall back.

### 2.3 Review/draft flow parity
- [ ] Review overlay "Change" button hardcodes the `clearer` rewrite — add the preset picker
      (shorten / expand / rephrase / format / custom) that the dashboard already has.
- [ ] Long-input splitting (multi-part drafts with part_index/part_total) existed in legacy;
      verify the sidecar splits at the token limit, and give the review overlay next/prev
      queue navigation for multi-draft sessions.
- [ ] Draft metadata (duration, token counts) is rendered but never populated — wire it from
      the backend payload or remove the placeholders.
- [ ] Review TTS: show play/stopped state properly; "Read" currently flips to "Stop" with no
      done signal.

### 2.4 Overlays & tray
- [ ] Status overlay: fixed at bottom-right, not draggable, not configurable. Legacy had 9
      positions + custom, colors, flash toggle. Minimum: position presets + remember a
      dragged position; honor the existing settings toggles.
- [ ] Notification overlay parity: transient success/warn/error toasts (legacy
      notification_overlay). Today only the status pill exists; errors go to console.
- [ ] Tray: swap icon by state (idle/recording/processing — assets already exist in
      images/), add menu items: Toggle Recording, Open Settings, Quit.

### 2.5 Backend gaps
- [ ] `/models/unload/{component}` returns success but frees nothing — implement real
      unload + gc (matters a lot on low-RAM/no-GPU machines).
- [ ] `/project/export` hardcodes `~/Desktop` (server.py:2429 area) — use Downloads with
      fallback.
- [ ] Audio ducking is Windows-only (pycaw). Either add a PulseAudio/PipeWire
      implementation (`pactl set-sink-volume`) or hide/disable the toggle on Linux with a
      capability note — currently the toggle lies.
- [ ] requirements.txt: add platform markers (`pydirectinput; sys_platform == 'win32'`,
      pycaw/comtypes likewise) so Linux installs stop pulling/failing Windows deps.
- [ ] Standardize platform detection (`sys.platform.startswith("win")` vs `== "win32"`).

### 2.6 First-run experience (legacy had this, Electron has nothing)
- [ ] Policy acceptance screen (legacy splash.py) — required before first use.
- [ ] Guided tour port (legacy guided_tour.py, 10 steps) — even a trimmed 4–5 step version:
      hotkeys → record → review → send.
- [ ] First-run model download wizard: detect nothing installed → offer MVP pack
      (gemma-4b-q4 + base.en + TTS) with progress. Replaces the NSIS prefetch sections.
      Use `/doctor` model-fit assessment to recommend sizes for the machine.

---

## Phase 3 — UI/UX improvements (P2)

### Fix what's broken/dead
- [ ] Dead DOM refs in renderer main.js: `refreshRuntimeButton`, `refreshProfilesButton`,
      `capabilitiesSummaryEl` — add the elements or delete the code.
- [ ] Theme settings are decorative: theme mode (system/dark/light), accent palettes,
      density, font size, high contrast are saved but never applied. Wire them to CSS
      custom properties on `<html>` or remove them until real.
- [ ] Hotkey capture inputs give no feedback while recording — add an "listening…" state
      and Escape-to-cancel.
- [ ] Profile names accept blank strings; persona wizard accepts empty name/prompt — add
      validation.

### Error/loading states
- [ ] Every fetch failure currently lands in console.error. Route through one toast/banner
      helper (pairs with 2.4 notification overlay).
- [ ] WebSocket: visible connection state + exponential backoff (currently silent 3s loop).
- [ ] Distinguish Loading / Empty / Error in status cards and lists (they all read alike).
- [ ] Model downloads: support cancel; make the progress UI handle LLM + Whisper downloads
      concurrently (currently assumes one).
- [ ] Add retry buttons where a refresh is the fix (doctor panel, diagnostics).

### Accessibility & polish
- [ ] Tabs: `role="tab"`, `aria-selected`, `aria-controls`; arrow-key navigation.
- [ ] Focus trap + Escape-to-close in the review overlay.
- [ ] Move the 18+ inline `style=` attributes in index.html into base.css classes.
- [ ] Settings search: debounce, show category of each hit, aria-live result count.
- [ ] Keyboard shortcuts inside the app (e.g. Ctrl+R toggle recording when focused).

### Performance/hygiene
- [ ] Clear the 2s health-refresh interval when window hidden; resume on focus.
- [ ] Event delegation for tab buttons; reuse DOM nodes in draft history render.
- [ ] Centralize magic numbers (poll intervals, overlay timeouts) in one config object.

---

## Phase 4 — Legacy retirement & tests (after parity)

- [ ] Delete the tkinter/Flet stack: main.py, overlay.py, preview_overlay.py,
      notification_overlay.py, splash.py, guided_tour.py, settings*.py mixins,
      settings_modal_manager.py — **only after** 2.1–2.6 land.
- [ ] The 11 test modules that `from main import App` currently error on machines without
      tkinter — mark with `pytest.importorskip("tkinter")` now; rewrite against the sidecar
      API when main.py is deleted.
- [ ] Pre-existing failures to fix independently: `tests/test_server_lazy_startup.py` (4)
      and `tests/test_model_manager_status.py` (1) — they fail on unmodified HEAD too.
- [ ] Add smoke tests for the Electron path: sidecar spawn/health, hotkey → toggle
      endpoint, draft roundtrip, packaged-binary boot on both OSes.

---

## Suggested order of attack

| # | Work | Why first |
|---|------|-----------|
| 1 | 1.3 sidecar config bug + health monitor | Small, everything depends on a reliable sidecar |
| 2 | 1.1 Windows dist pipeline end-to-end | Proves the packaged product exists |
| 3 | 1.2 Linux AppImage + de-sudo | Your daily driver; unblocks real dogfooding |
| 4 | 2.1 PTT/global hotkeys (uiohook) | Headline feature, currently impossible |
| 5 | 2.2 Linux injection matrix | Core dictation output on Linux |
| 6 | 2.6 first-run wizard + policy | Required for anyone else to install it |
| 7 | 2.3–2.5 parity items | Feature completeness |
| 8 | Phase 3 UI/UX passes | Polish once flows are real |
| 9 | Phase 4 legacy deletion + tests | Lock it in |
