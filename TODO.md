# BetterFingers V3 Ship Checklist

## How to Use This List
- [ ] Work top to bottom by section.
- [ ] Check items only after code + tests + manual QA are complete.
- [ ] Keep "Post-V3" items out of release blockers.

## 1) Release Blockers (Must Be Done Before Ship)
- [x] End-to-end smoke test: record -> review -> accept -> manual send -> success notification.
- [x] End-to-end smoke test: record -> review -> decline -> no send performed.
- ** Get Rid of queue only mode only send mode and review mode ** [ ] End-to-end smoke test: queue-only mode behaves correctly (no unintended auto-send).
- [x] End-to-end smoke test: auto-send mode behaves correctly (no stuck review state).
- [ ] Regression test suite passes locally: `python -m unittest discover -s tests -v`.
- [x] Verify no crashes on startup/shutdown across 3 consecutive app restarts.
- [?] **one known issue it reverts to default profile on launch of app should be whatever you used last**  Verify first-run flow + settings persistence works across profile switches.

## 2) Input and Hotkey Behavior
- [x] Confirm recording hotkey behavior in both `toggle` and `ptt` modes.
- [?] **remove force-stopkey**Confirm force-stop key cleanly aborts recording, typing, and TTS playback.
- [x] Confirm `Primary Action Hotkey` (default `F9`) send-first behavior:
- [x] With accepted draft pending: sends draft only.
- [x] Without pending draft: attempts selection-capture TTS only.
- [x] Confirm `Review TTS Shortcut` still works independently.
- [x] Confirm hotkey dedupe when primary and review TTS hotkeys are identical.

## 3) TTS and Review UX
- [x] Review panel shows exactly 3 buttons: `Accept`, `Decline`, `Read Aloud`.
- [x] Review `Read Aloud` button reads selected text first, full text otherwise.
- [x] Settings Output tab voice selector works with runtime voice list.
- [x] Settings sample playback (`Play Sample` / `Stop`) works reliably.
- [x] Verify Kokoro primary path works when available.
- [x] Verify Windows SAPI fallback works when Kokoro unavailable.
- [x] Verify user sees clear fallback messaging when SAPI is used.

## 4) Clipboard-Safe TTS Capture
- [x] Confirm capture flow snapshots clipboard, sends `Ctrl+C`, and restores original clipboard.
- [x] Confirm unchanged clipboard with readable text uses guarded fallback.
- [x] Confirm URL-only clipboard text is rejected (not read aloud).
- [x] Confirm empty/unreadable clipboard shows non-error "no readable text" message.
- [x] Confirm clipboard restore still occurs when `Ctrl+C` capture fails.

## 5) Audio Ducking and Stability
- [x] Confirm ducking only unducks after a prior successful duck event.
- [x] Confirm disabling ducking does not trigger persistent interface reset.
- [x] Confirm fallback return volume is applied when volume read-back fails.
- [?] Run gameplay stability check (Rocket League scenario) for at least one full session.

## 6) Model Lifecycle and Resource Control
So the loaded models are not being produced accidentally. But when I unchecked the boxes to keep the model loaded on all three, they are still all loaded as far as I can tell. Perhaps not the TTS, but the LOM and speech to text are still loaded. Because we have five gigs of VRAM usage with no game running, just a couple of windows, and no video running, there are a couple of issues there.
- [Fail] Confirm `Keep LLM Loaded` toggle unload/reload behavior works.
- [Fail] Confirm `Keep STT Loaded` toggle unload/reload behavior works.
- [Fail] Confirm `Keep TTS Loaded` toggle unload/reload behavior works.
- [x] Confirm model unload actions do not break next-request auto-reload.
- [x] Confirm startup warm-load respects keep-loaded flags.

## 7) Settings, Profiles, and Migration
- [x] Confirm defaults for all new keys are present in profile load/save paths.
- [x] Confirm preview overlay enablement auto-defaults review TTS to enabled in UI.
- [x] Confirm profile migration works for older profile files without key errors.
- [x] Confirm all changed settings labels/tooltips are accurate and user-facing.

## 8) Packaging and Install Experience
- [ ] Validate clean install on a machine without dev dependencies.
- [ ] Validate update install over existing V2/V3 profile data.
- [ ] Confirm required runtime dependencies are documented (Kokoro optional/fallback path clear).
- [ ] Confirm installer and app icons/resources resolve correctly after packaging.

## 9) Documentation and Release Notes
- [ ] Write concise V3 release notes (major behavior changes + known limitations).
- [ ] Add "Hotkeys and behavior priority" section to user-facing docs.
- [ ] Add "TTS fallback and troubleshooting" section.
- [ ] Add "Clipboard capture behavior and privacy expectations" section.

## 10) Post-V3 (Not a Ship Blocker)
- [x] Integrate text formatter feature behind a settings toggle.
- [x] Define formatter scope (review-only, pre-send only, or global output path).
- [x] Add formatter presets/profile-level configuration.
- [x] Add formatter unit tests and manual QA scenarios.
- [x] Add formatter docs and migration defaults.

## Final Go/No-Go Gate
- [ ] All sections 1-9 complete.
- [ ] No P0/P1 bugs open.
- [ ] Ship build tagged and archived.
