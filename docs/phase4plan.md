Phase 4A: Make settings navigable
Goal

Stop making the user scroll through a control landfill.

Build

Split Settings into sections:

General
Recording
Hotkeys
Review & Drafts
AI Cleanup
Send & Injection
Audio Devices
TTS / Read-Aloud
Models
Notifications & Status UI
Appearance
Accessibility
Advanced / Developer

This matches the repo’s own desired section breakdown.

Acceptance criteria
Left sidebar or sub-tabs exist.
Search/filter works.
No settings page requires reading a giant wall of controls.
Disabled/unsupported settings clearly explain why.
Phase 4B: Profile safety and lifecycle
Goal

Profiles should behave like real user data, not vibes in JSON form.

Build

Add:

profile rename
duplicate profile
import/export profile JSON
profile backup before migration
prevent deletion of active/default profile unless fallback is guaranteed
profile save validation before write
atomic save behavior: write temp, validate, replace

The current TODO already calls out import/export, duplicate handling, rename, backup, and safe delete as missing robustness items.

Acceptance criteria
User cannot accidentally delete the only usable profile.
Failed save does not corrupt profile.
Profile switching updates runtime without restart or clearly says what needs reload.
Import/export can move profiles between machines.
Phase 4C: Validation and conflict detection
Goal

Bad settings should be rejected before they cause runtime failures, because apparently computers need boundaries.

Build

Validate:

hotkey syntax
duplicate hotkeys
conflicting hotkeys
numeric ranges
token limits
chunk sizes
audio gate thresholds
TTS speed
send mode values
model keep-loaded flags

The TODO specifically calls out hotkey syntax validation, duplicate/conflicting hotkeys, numeric ranges, and safe profile failure handling.

Acceptance criteria
Invalid input shows inline error.
Save button is blocked until errors are fixed.
Backend also validates, not just frontend.
Tests cover bad values and migration/default fallback.
Phase 4D: Platform-aware warnings
Goal

Linux/Windows differences should be visible before the user thinks the app is broken.

Build warning badges like:
Setting	Warning
Audio ducking	Windows-only
Paste/type injection	May fail on Wayland
Clipboard rich restore	Windows-focused
Global hotkeys	Depends on Linux session/compositor
Llama server	Linux requires local llama-server path or env override

The parity map already states Wayland may block hotkeys/injection, rich clipboard restore is Windows-only, audio ducking is Windows-only, and Linux send should default to copy-only until injection is validated.

Acceptance criteria
Every platform-limited setting has a badge.
Unsupported settings are disabled or fallback-safe.
User sees the actual behavior, not a fake promise.
Phase 4E: Appearance and usability
Goal

Make BetterFingers feel like an app instead of a server admin panel that found eyeliner.

Build

Add:

dark/light/system theme
accent color
compact/comfortable density
font size scaling
high contrast mode
responsive layout for small laptops, large monitors, split screen
reusable UI components:
setting row
setting group
toggle
select
hotkey recorder
warning callout
status pill
capability badge

These are all already listed as needed under Phase 4 themes and appearance.

Acceptance criteria
Appearance settings persist.
Invalid theme values fall back safely.
Settings are usable on small laptop screens.
UI preferences are separated from functional behavior profiles unless you intentionally decide they are profile-specific.
Phase 4F: “Test this setting” buttons
Goal

Users should not have to guess whether a setting works.

Add test buttons for:
test microphone
test hotkey conflict
test TTS voice
test paste/copy behavior
test model load

Your TODO already lists these as useful per-setting tests.

Acceptance criteria
Test result shows success/failure and reason.
Failed test gives recovery steps.
Test actions never modify user text outside a controlled/copy-only path.
Phase 4G: QA and tests
Manual QA

Run this on both Linux and Windows:

profile switch
profile save
discard changes
create profile
delete profile
hotkey recording input
duplicate hotkey detection
invalid numeric values
platform warning visibility
theme persistence
responsive layout

The repo already has a manual Electron QA checklist, but it focuses more on runtime, backend, recording, packaging, and diagnostics. Phase 4 needs a dedicated settings QA section added.

Automated tests

Add tests for:

profile defaults
profile migration
invalid values rejected or corrected
appearance settings persist
invalid theme fallback
settings page renders
search/filter behavior
dirty-state behavior
save/discard behavior
Best next coding-agent prompt

Use this as the next prompt for Codex or whatever silicon intern you’re currently terrorizing:

You are working in the BetterFingers GitHub repo. Focus only on Phase 4: Settings, Profiles, and Configuration UX.

Read these files first:
- docs/ELECTRON_FULL_FUNCTIONALITY_TODO.md
- docs/ELECTRON_FEATURE_PARITY_MAP.md
- app/src/renderer/index.html
- app/src/renderer/main.js
- app/src/renderer/api/backend.js
- app/src/main/ipc.js
- app/src/preload/preload.js
- user_profile_manager.py
- settings.py
- server.py

Goal:
Refactor the current Electron settings experience from one long scroll into a cleaner categorized settings UX while preserving all existing functionality.

Do not begin planner, agent, notification, TTS, or model-management expansion. This task is settings/profile UX only.

Implement Phase 4A and Phase 4C first:
1. Add categorized Settings navigation:
   - General
   - Recording
   - Hotkeys
   - Review & Drafts
   - AI Cleanup
   - Send & Injection
   - Audio Devices
   - TTS / Read-Aloud
   - Notifications & Status UI
   - Appearance
   - Advanced / Developer

2. Add settings search/filter:
   - Search by label, description, and setting key.
   - Hide non-matching setting rows.
   - Show empty state when no results match.

3. Add reusable setting UI components/classes:
   - setting group
   - setting row
   - setting description
   - warning badge
   - inline validation message
   - sticky save/discard bar

4. Add frontend validation before save:
   - hotkey syntax
   - duplicate/conflicting hotkeys
   - numeric ranges for token limit, chunk sizes, TTS speed, and audio gate thresholds
   - valid enum values for record mode, send mode, cleanup preset, and booleans

5. Preserve existing backend API calls and existing setting keys.
Do not rename backend settings unless you also add migration compatibility.

6. Add platform warning badges for:
   - audio ducking Windows-only
   - paste/type injection Linux Wayland limitation
   - rich clipboard restore Windows-focused
   - global hotkey limitations on Linux/Wayland

7. Add tests where practical:
   - settings page renders
   - invalid numeric value blocks save
   - duplicate hotkey blocks save
   - search filters visible settings
   - dirty-state appears after changing a setting

8. Update docs/ELECTRON_FULL_FUNCTIONALITY_TODO.md:
   - Mark completed Phase 4 items accurately.
   - Do not mark QA complete unless actually tested.
   - Add a short Phase 4 QA checklist if missing.

Acceptance criteria:
- Existing Electron dashboard still loads.
- Existing profile load/save still works.
- Existing model, diagnostics, draft, and runtime controls are not broken.
- Settings are no longer presented as one giant undifferentiated scroll.
- Invalid settings cannot be saved silently.
- Platform-limited settings visibly explain their limits.