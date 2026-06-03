# Suggested Build Order From Here

## Immediate priority

1. Clean up docs so the TODO, parity map, and QA checklist agree.
2. Run Linux dev QA on current Electron shell.
3. Fix Settings dirty-state and basic profile UX issues.
4. Split Settings into organized sections instead of one long scroll.
5. Add theme foundation:
   - CSS variables
   - dark/light/system
   - accent color
6. Finish real TTS.
7. Add mic/device selection and recording test.
8. Add notification/status strategy.
9. Package Linux AppImage.
10. Package Windows NSIS.
11. Add automated backend tests for drafts, profiles, models, runtime.
12. Only then begin planner foundation.

## Do not prioritize yet

- Mobile tunnel.
- Full local agent.
- Planner automation.
- Graph editor unless it is still core product direction.
- Advanced intent systems.
- Extra personality/preset complexity beyond what supports the review workflow.

These are good future features, but not before the foundation is stable.

---

# Immediate Next Tasks For A Coding Agent

Use these as near-term coding prompts.

## Prompt 1: Fix docs and checklist status

Update `docs/ELECTRON_FEATURE_PARITY_MAP.md`, `docs/ELECTRON_MANUAL_QA_CHECKLIST.md`, and this TODO so they agree with the current code. Separate "implemented" from "manual QA passed" and remove stale immediate tasks that are already implemented.

## Prompt 2: Fix settings dirty-state

Audit `app/src/renderer/main.js` and ensure settings dirty-state listeners are registered during bootstrap or module initialization, not accidentally inside unrelated runtime/warmup logic. Add a small renderer test or manual test notes proving dirty-state, save, and discard work.

## Prompt 3: Redesign settings into sections

Refactor the Electron settings UI from one long scroll into organized sections: General, Recording, Hotkeys, Review, Send, Audio, TTS, Models, Notifications, Appearance, Advanced. Add section navigation, descriptions, validation hints, and platform limitation callouts.

## Prompt 4: Add theme foundation

Add CSS variables and theme settings for system/dark/light, accent color, density, and font scale. Persist appearance settings and apply them on startup.

## Prompt 5: Add backend doctor endpoint

Create `/runtime/doctor` that summarizes backend health, runtime readiness, platform capabilities, model paths, llama-server status, audio/TTS readiness, hotkey status, recent runtime errors, and user-facing recovery hints.

## Prompt 6: Implement real TTS backend

Replace mock `/tts/speak` and `/drafts/{id}/tts` behavior with real TTS synthesis/playback or generated audio response. Add runtime status, warmup, stop endpoint, voice list parity, sample playback, and clear missing-dependency errors.

## Prompt 7: Add audio device settings

Add microphone listing, selected input device setting, recording test endpoint, live level meter, and audio gate diagnostics. Show platform-specific Linux/Windows capability messaging.

## Prompt 8: Add manual QA runner script

Create a repeatable dev smoke script that starts the backend/Electron stack where practical, checks `/health`, checks runtime endpoints, creates a test draft, accepts/copies/sends it, and verifies clean shutdown.

## Prompt 9: Add backend tests

Add tests for runtime status, drafts, no-audio gate, profile endpoints, model endpoints with mocks, platform capabilities, and error response structure.

## Prompt 10: Package and smoke test

Run Linux and Windows packaging flows. Document exact failures and update packaging scripts until packaged builds can start the backend, find assets, load config/model paths, and shut down cleanly.

---

# Release Gate Summary

Electron BetterFingers cannot be considered release-ready until these are true:

- [ ] Record -> transcribe -> cleanup -> review -> copy/send works on Linux.
- [ ] Record -> transcribe -> cleanup -> review -> copy/send works on Windows.
- [ ] Settings are organized, validated, and not a giant scroll trap.
- [ ] Profiles save, switch, migrate, and recover safely.
- [ ] TTS is real, stoppable, and diagnosable.
- [ ] Microphone selection and testing exist.
- [ ] Missing model/runtime dependencies are understandable.
- [ ] Packaging works on Linux and Windows.
- [ ] Electron shutdown does not leave backend ghosts.
- [ ] Logs and diagnostics are useful but do not leak sensitive text by default.
- [ ] Automated tests cover core backend state transitions.
- [ ] Manual QA checklist has real pass/fail notes.
- [ ] Legacy Python app remains available until explicit cutover approval.