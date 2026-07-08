# Bugfix plan — post-merge gap review

Source: multi-surface review (setup/deps/docs, backend runtime, renderer UI/UX,
Electron main process) of the merged `master-plan` → `main` tree. Every finding
below was verified against the actual code; two review claims were checked and
**rejected** (the persona v2 cache check *is* inside its lock; Pillow *is* used
by server.py:2932 — both stay as-is).

Baseline: **276 tests** (one is environment-dependent — fixed in Phase 0 so the
suite is trustworthy for the rest of the work). Rules for every phase: full
`python3 -m pytest` stays green, `node --check` any touched JS, one commit per
phase, update this file's checkboxes as work lands.

---

## Phase 0 — make the suite trustworthy (do first)

### 0.1 Fix env-dependent test `test_gemma4_updates_old_managed_runtime`  [LOW → but blocks verification]
- **Problem:** `tests/test_model_manager_status.py:218` doesn't stub
  `get_server_path`/`get_repo_root`, so on any machine with a real
  `.betterfingers/llama-server` binary the test validates the wrong file and
  fails. (Its sibling `test_linux_uses_llama_server_without_exe...` already
  patches `get_repo_root`.)
- **Fix:** in the test's `with patch(...)` block add
  `patch("model_manager.get_server_path", return_value=server_path)` (or patch
  `get_repo_root` to `tmp` like the sibling test does).
- **Verify:** test passes **with** the local `.betterfingers` binary present.

---

## Phase 1 — HIGH: privacy wipe actually wipes (backend)

### 1.1 `/privacy/wipe` misses the history DB and on-disk audio  [HIGH]
- **Problem:** `server.py` `privacy_wipe()` (~line 2166) clears the in-memory
  draft queue + `draft_history.json` (+voices on request), but leaves:
  - the SQLite FTS archive — `history_store.clear()` (history_store.py:200,
    returns bool) is never called;
  - the persisted WAV recordings — `recordings.clear_recordings()`
    (recordings.py:115, returns count) is only wired to `DELETE /recordings`.
  A "wipe my data" leaves every transcript searchable and every raw recording
  on disk.
- **Fix:** in `privacy_wipe()`:
  ```python
  cleared["history_db_cleared"] = history_store.clear()
  cleared["recordings_files_removed"] = recordings.clear_recordings()
  ```
  Update the endpoint docstring; confirm `GET /privacy` (get_privacy_report)
  lists the history DB and recordings dir as data locations — add if missing.
- **Tests (new `tests/test_privacy_wipe.py` or extend existing):**
  - seed history_store + a recording in a tmp APPDATA, POST `/privacy/wipe`,
    assert history search returns nothing and `recordings.list_recordings()`
    is empty; assert `cleared` keys present.
  - wipe with nothing to clear still returns ok.

---

## Phase 2 — HIGH: persona editing must not destroy prompts (renderer)

### 2.1 Wizard silently regenerates an existing persona's prompt  [HIGH]
- **Problem:** `app/src/renderer/main.js` — `showStep(4)` always calls
  `generatePromptPreview()` (line ~1523), and `loadExistingPersonaAdvanced()`
  loads only the Advanced fields, not the prompt. Editing an existing persona
  (typing its name) then saving overwrites its hand-tuned prompt with generic
  wizard output.
- **Fix (design):**
  1. Track `let editingExistingPersona = false;` in the wizard scope.
  2. In `loadExistingPersonaAdvanced()`: when GET `/personas/{name}` succeeds,
     also set `wizardPromptPreview.value = persona.prompt`, set
     `editingExistingPersona = true`, and show a hint via
     `setMessage(wizardMessage, "Loaded existing persona — its prompt is shown below.", "info")`.
  3. In `showStep(4)`: only call `generatePromptPreview()` when
     `!editingExistingPersona`.
  4. Remove `readonly` from `#wizardPromptPreview` (index.html ~line 573) so
     the loaded prompt is hand-editable, and add a small
     "Regenerate from wizard" button next to it that calls
     `generatePromptPreview()` and clears the flag.
  5. Reset the flag in the post-save reset and the delete handler.
- **Verify:** `node --check main.js`; manual QA step added to
  MANUAL_QA_CHECKLIST ("edit existing persona → prompt preserved; Regenerate
  button replaces it").

### 2.2 Wizard delete leaves stale prompt preview  [LOW — same file, do together]
- **Fix:** in the delete success handler add
  `if (wizardPromptPreview) wizardPromptPreview.value = '';` and reset the
  Advanced fields + `editingExistingPersona`.

---

## Phase 3 — HIGH: closing the dashboard must not strand the app (Electron main)

### 3.1 Stale window reference makes the dashboard unrecoverable  [HIGH]
- **Problem:** `app/src/main/main.js:84` captures `mainWindow` once. The hidden
  overlay window keeps Electron alive after the dashboard is closed
  (`window-all-closed` never fires), `windows.js:78` nulls its own reference,
  but main.js's stale destroyed reference means tray → "Open Dashboard" /
  tray-click silently no-op. Only escape is Quit.
- **Fix:**
  1. `windows.js`: export `getMainWindow()` returning the module-level
     `mainWindow`.
  2. `main.js`: replace the captured reference everywhere with a helper:
     ```js
     function ensureMainWindow() {
       let win = getMainWindow();
       if (!win || win.isDestroyed()) { win = createMainWindow(); }
       return win;
     }
     ```
     Tray `onShow` → `focusMainWindow(ensureMainWindow())`;
     `registerIpc.getMainWindow` → `getMainWindow()`;
     `notifyRendererSidecarStatus` → use `getMainWindow()`.
  3. Keep `window-all-closed → requestQuit` as-is (still correct if overlay is
     ever gone too).
- **Verify:** `node --check` on main.js/windows.js; manual QA step: close
  dashboard → tray → Open Dashboard reopens it; sidecar status resumes
  rendering in the reopened window.

---

## Phase 4 — MEDIUM backend

### 4.1 History DB retention  [MED]
- **Problem:** `history_store.py` grows unbounded (recordings has
  MAX_RECORDINGS=50; history has nothing).
- **Fix:** add `MAX_HISTORY_RECORDS = 5000` and
  `prune(max_records=MAX_HISTORY_RECORDS)` deleting oldest rows
  (`DELETE FROM drafts WHERE id NOT IN (SELECT id FROM drafts ORDER BY id DESC LIMIT ?)`),
  called from `init()`/server startup and after every ~100th `add()` (cheap
  counter). Keep FTS in sync (external-content or contentless table — check the
  existing schema and use the matching delete pattern).
- **Tests:** insert limit+N rows in tmp DB → prune → count == limit, newest
  kept, search still works.

### 4.2 Double profile read per utterance  [MED]
- **Problem:** `server.py:301-316` — `voice_commands_enabled()` and
  `macros_enabled()` each call `load_profile()` (disk I/O) and both run per
  dictation in `process_recording_result`.
- **Fix:** add `get_pipeline_flags()` returning
  `{"voice_commands": bool, "macros": bool}` from ONE `load_profile()` call;
  use it in `process_recording_result`. Keep the two existing helpers
  delegating to it (API/tests compat).
- **Tests:** existing suites cover behavior; add one asserting a single
  `load_profile` call via mock during `get_pipeline_flags()`.

### 4.3 Persona copy hardening  [MED — narrowed]
- **Problem (verified subset):** `get_persona()` returns `dict(entry)` — nested
  `voice`/`format`/`few_shot` still reference `_personas_v2_cache`, so a caller
  mutation corrupts the cache. `load_personas()`/`load_personas_v2()` also
  return the live cache objects. (The reported lock-check race was FALSE —
  check already runs under `_personas_lock`.)
- **Fix:** `import copy`; `get_persona` → `copy.deepcopy(entry)` inside the
  lock. Leave `load_personas*` returning the cache (hot path,
  `process_fast_lane` only reads) but add a docstring warning "treat as
  read-only".
- **Tests:** get_persona → mutate nested dict → reload → cache unchanged.

### 4.4 Dead dependencies  [MED]
- **Fix:** remove `flet==0.80.5` and `pystray` from requirements.txt (zero
  imports repo-wide; UI is Electron now). **Keep Pillow** (server.py:2932) and
  `keyboard`/`pygame` (hotkey_manager.py still imported by server.py).
- **Verify:** `grep -rn "import flet\|import pystray"` empty; full pytest.

---

## Phase 5 — MEDIUM/LOW renderer polish (one commit)

### 5.1 Async race guards  [MED]
- `loadExistingPersonaAdvanced()`: capture the name at request time; on
  response, bail if `wizardPersonaName.value.trim()` no longer matches.
- `populateOnboardingRecommendation()`: after `await`, bail if the target
  `#onboardingRecommendation` is no longer in the DOM (`!box.isConnected`).

### 5.2 Escape dynamic strings in innerHTML  [LOW]
- Wrap with existing `escapeHtml()`:
  - `main.js:1273` history search error, `:2170` macros error, `:2207`
    dictionary error (or switch to `.textContent`);
  - `renderModelRecommendation()` + `populateOnboardingRecommendation()`:
    escape `tier_label`, `tier_guidance`, `llm.name`, `llm.note`, `whisper`.

### 5.3 Builtin-persona list drift  [LOW]
- Server: extend `GET /personas/{name}` response is unchanged; add tiny
  `GET /personas-builtins` (list of `_DEFAULT_PERSONAS` keys, avoids colliding
  with the `/personas/{name}` route). Renderer: on personas refresh, populate
  `BUILTIN_PERSONAS` from it, keeping the current hardcoded set as fallback.
- Test: route returns the 5 names.

### 5.4 Health poll pauses when hidden  [LOW]
- `visibilitychange`: skip the poll body (or stop/restart the interval) while
  `document.hidden`.

### 5.5 `[hidden]` consistency  [LOW]
- Add `[hidden] { display: none !important; }` to base.css; leave existing
  `.hidden` class usage alone.

Verify all of Phase 5 with `node --check` + pytest (5.3 adds a route test).

---

## Phase 6 — LOW backend/infra hygiene (one commit)

### 6.1 Pipeline stage timing  [LOW]
- In `process_recording_result`, time dictionary/commands/macros as one
  `post_ms` (perf_counter around the three calls) and include it in the
  metrics/HUD payload next to `stt_ms`/`llm_ms`. Renderer HUD: display if
  present.

### 6.2 Corrupted store visibility  [LOW]
- `dictionary.py` / `macros.py` read paths: on JSON parse failure,
  `logging.warning(...)` and rename the bad file to `*.corrupt` (one-time,
  preserves user data for recovery) before returning defaults.
- Tests: corrupted file → warning logged, `.corrupt` created, empty list
  returned, subsequent add works.

### 6.3 `.gitignore` stale rule  [LOW]
- Remove `!.env.example` (file no longer exists).

### 6.4 Unused import  [LOW]
- `server.py:17`: drop `Field` from the pydantic import (0 usages).

### 6.5 `required_llama_server_build` future-proofing note  [LOW]
- Add a comment: "new model families with runtime minimums must be added
  here" (behavioral change not needed today).

---

## Explicitly OUT of scope (features, not bugs)
- UI for persona `voice` / `few_shot` / `dictionary_scope` (U7 deferred polish).
- The 7 blocked MASTER_PLAN items (see REMAINING_WORK.md).

## Execution order & verification matrix

| Phase | Area | Est. size | Gate |
|---|---|---|---|
| 0 | test fix | ~5 lines | full pytest green **with** local llama-server present |
| 1 | privacy wipe | ~15 lines + tests | new wipe tests green |
| 2 | persona edit UX | ~40 lines JS/HTML | node --check + manual QA note |
| 3 | window lifecycle | ~25 lines JS | node --check + manual QA note |
| 4 | backend mediums | ~80 lines + tests | pytest green, +~6 tests |
| 5 | renderer polish | ~60 lines + 1 route/test | node --check + pytest |
| 6 | hygiene | ~40 lines + tests | pytest green |

Every phase: commit separately (`Co-Authored-By: Claude`), keep tree clean,
tick the boxes here. Expected end state: ~285+ tests, all HIGH/MED findings
closed, LOWs closed except the explicit out-of-scope features.

## Progress
- [x] Phase 0 — env-dependent test (af15b2c)
- [x] Phase 1 — privacy wipe completeness (28154a9; also fixed a latent
      history_store.init() path-keying bug found while testing)
- [x] Phase 2 — persona edit prompt preservation (+ preview reset on delete)
- [x] Phase 3 — dashboard reopen from tray
- [ ] Phase 4 — history retention, single profile read, persona deepcopy, dead deps
- [ ] Phase 5 — race guards, escaping, builtins endpoint, hidden-poll, [hidden] CSS
- [ ] Phase 6 — stage timing, corrupt-store visibility, gitignore, unused import, doc note
