# Wave 7 — documented integration diffs (Gate 7)

Wave 7 (application context and automatic profiles) ships six new files that are
complete and tested on their own. Six **integration-owned** files have to change
before the feature is reachable from the app. `sup-appcontext` did not edit any
of them; every required edit is written out below, exactly, with the reason it
is needed and what breaks without it.

Ordering matters for only one pair: the route module must be mounted (D-1)
before the proxy allowlist (D-2) does anything useful, and both must land before
any `signal-desk-prod` QA of the Wave 7 scenarios can pass.

| # | File | Status | Status without the diff |
|---|------|--------|------------------------|
| D-1 | `server.py` | **LANDED** (director, 2026-07-28) | `/app-context/*` returns 404 |
| D-2 | `app/src/main/backendProxy.js` | **LANDED** (director, 2026-07-28) | renderer cannot reach the routes at all; the Settings group renders its honest "not reachable" state |
| D-3 | `app/src/renderer/api/backend.js` | **LANDED** (director, 2026-07-28) | same as D-2 — the feature has no api methods to call |
| D-3b | `app/src/renderer/api/backend.js` | **OUTSTANDING — blocks QA** | the four helpers are defined but not exported, so `import * as api` sees them as `undefined` |
| D-4 | `data_categories.py` + `tests/test_data_categories.py` | outstanding | a persistent store exists that the privacy report does not declare |
| D-5 | `llm_engine.py` | outstanding | the gaming completion cap is declared but never applied |
| D-6 | `server.py` (second hunk) | outstanding | gaming delivery policy and the recording-state subscription are declared but never applied |

> **Naming note.** D-3 landed as `overrideAppProfile` / `pinAppProfile` rather
> than the `setAppContextOverride` / `pinAppContextProfile` names this document
> originally proposed. `app/src/renderer/api/backend.js` is integration-owned,
> so its names are authoritative:
> `app/src/renderer/features/applicationProfiles.js` and its unit tests were
> updated to call the landed names, and `REQUIRED_API_METHODS` now lists them.
> The D-3 diff below is kept as written for the record; the landed spelling is
> what is in the tree.

---

## D-1 — `server.py`: mount the route module

The other seven route modules are already registered this way; this is the same
one line in the same block at the end of the file.

```diff
--- a/server.py
+++ b/server.py
@@ (the app.include_router block at the end of the file, currently ending with routes_library)
 app.include_router(routes_contacts.router)
 app.include_router(routes_library.router)
+app.include_router(routes_app_context.router)
```

and, alongside the other route-module imports:

```diff
+from backend.api.routes import app_context as routes_app_context
```

Match whatever import spelling the neighbouring route modules already use in
this file; the module object is `backend.api.routes.app_context` and its router
attribute is `router`.

**Without it:** every `/app-context/*` request 404s.

---

## D-2 — `app/src/main/backendProxy.js`: four allowlist entries

`ROUTE_ALLOWLIST` is an exact `(method, route)` table, not a prefix match.
Nothing else in the file changes — no new method, no new param shape.

```diff
--- a/app/src/main/backendProxy.js
+++ b/app/src/main/backendProxy.js
@@ ROUTE_ALLOWLIST.GET
     // Wave 4 Library UI (contract §5): backend-driven search + read-only
     // reopen payload.
     '/library/search', '/library/drafts/:id/reopen',
+    // Wave 7 application context. Read-only: which application is focused and
+    // which profile that selects. Carries no recipient, contact or
+    // conversation data -- the snapshot vocabulary is closed and tested in
+    // backend/services/app_context.py.
+    '/app-context/status', '/app-context/profiles',
   ],
@@ ROUTE_ALLOWLIST.POST
     '/library/clear',
+    // Wave 7. Override is in-memory and temporary; pin is a durable
+    // "always use this profile for this application".
+    '/app-context/override', '/app-context/pin',
   ],
```

**Without it:** the renderer's request is refused in the main process. This also
blocks QA — `app/tests/qa/harness.mjs` runs a real HTTP stub that the app
reaches *through* this proxy, so the stub is behind the allowlist too. The
feature degrades honestly (one sentence saying it is not reachable) rather than
rendering an empty profile list, but nine of the ten `wave7-app-context`
scenarios cannot pass until this lands.

---

## D-3 — `app/src/renderer/api/backend.js`: four helpers

`app/src/renderer/features/applicationProfiles.js` calls exactly these four
names and checks for
them with `typeof === 'function'` before doing anything (`computeAvailability`).
Updates go by POST rather than PATCH for the same reason the contacts helpers do:
the proxy allowlist is keyed by method and carries only GET/POST/DELETE.

```diff
--- a/app/src/renderer/api/backend.js
+++ b/app/src/renderer/api/backend.js
@@ (with the other URL constants)
+const APP_CONTEXT_URL = `${BACKEND_ORIGIN}/app-context`;
@@ (with the other feature helper groups, e.g. after the Contacts block)
+// --- Application context (Wave 7) -------------------------------------------
+//
+// Which application is focused and which profile that selects. Nothing here
+// carries or returns a recipient, a contact or a conversation.
+
+async function fetchAppContextStatus(refresh = true, timeoutMs = 2500) {
+  return fetchJson(`${APP_CONTEXT_URL}/status?refresh=${refresh}`, timeoutMs);
+}
+
+async function fetchAppProfiles(timeoutMs = 2500) {
+  return fetchJson(`${APP_CONTEXT_URL}/profiles`, timeoutMs);
+}
+
+async function setAppContextOverride(profileId, timeoutMs = 2500) {
+  return postJson(`${APP_CONTEXT_URL}/override`, { profile_id: profileId || '' }, timeoutMs);
+}
+
+async function pinAppContextProfile(profileId, timeoutMs = 2500) {
+  return postJson(`${APP_CONTEXT_URL}/pin`, { profile_id: profileId || '' }, timeoutMs);
+}
@@ (the module's export list)
   fetchContacts,
+  fetchAppContextStatus,
+  fetchAppProfiles,
+  setAppContextOverride,
+  pinAppContextProfile,
```

> Note on `fetchAppContextStatus`: the feature calls it with no arguments, so
> the `refresh = true` default is what runs. `GET /app-context/status?refresh=…`
> is one allowlisted route — the proxy matches the path, not the query string.
> If that turns out not to hold in this proxy's matcher, drop the query string
> and let the route's own default (`refresh: bool = True`) apply; the feature
> behaves identically either way.

**Without it:** `computeAvailability` reports the feature unavailable and it
paints the "not reachable" sentence. That is the designed degraded state, not a
crash.

---

## D-3b — `app/src/renderer/api/backend.js`: export the four helpers

**This is the one piece still outstanding, and it blocks all ten
`wave7-app-context` QA scenarios.**

The four helpers landed as function declarations at ~line 527, but this module
exports through a single explicit `export { ... }` block (lines ~931–1091) and
they are not in it. `import * as api from '../api/backend.js'` therefore sees
`api.fetchAppContextStatus === undefined`, `computeAvailability` correctly
reports the feature unreachable, and the Settings group paints its "not
reachable" sentence — which is the designed degraded state doing its job, not a
bug in the feature.

```diff
--- a/app/src/renderer/api/backend.js
+++ b/app/src/renderer/api/backend.js
@@ (the export block, alongside the other feature helper groups)
   fetchActiveContact,
+  fetchAppContextStatus,
+  fetchAppProfiles,
+  overrideAppProfile,
+  pinAppProfile,
```

Verify with a one-liner before running QA — a defined-but-unexported helper is
invisible to every test that does not import the module namespace:

```
node -e "import('./app/src/renderer/api/backend.js').then(m => console.log(
  ['fetchAppContextStatus','fetchAppProfiles','overrideAppProfile','pinAppProfile']
    .map(n => n + ':' + typeof m[n]).join(' ')))"
```

All four must print `:function`.

---

## D-4 — `data_categories.py`: declare the new store

A persistent store that the privacy report does not declare is a report that
lies by omission — the same rule the `contacts` entry was added under, in the
same change that created its store.

**Sensitivity is `personal`, not `configuration`, and that is deliberate.** The
profile bodies are settings, but the same file holds the `pinned` map, which
records *which applications this person runs*. That is a behavioural fingerprint,
and under-claiming it would defeat the privacy report. `may_contain_user_text`
is `False`: the fields are ids, process names and preset names, not prose
anybody wrote about a person.

Exact `_cat` line, to be inserted in the **Personal data** block (after the
`contacts` entry, before `wake_models`):

```python
    # Application profiles (Wave 7). The profile BODIES are settings, but the
    # same store holds the pinned map -- which applications this person runs --
    # so it is declared personal rather than configuration. Under-claiming that
    # would defeat the privacy report. No user prose: ids, process names and
    # preset names only.
    _cat("app_profiles", "Application profiles & pins", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         in_export=True, user_text=False),
```

And the matching addition to the hard-coded guard in
`tests/test_data_categories.py` (the set is deliberately not auto-derived):

```diff
--- a/tests/test_data_categories.py
+++ b/tests/test_data_categories.py
@@ EXPECTED_IDS
     "cloned_voices", "personas", "dictionary", "macros", "contacts", "wake_models",
+    "app_profiles",
     "mcp_config", "graph_data", "debug_log", "sidecar_raw_log", "support_report",
```

Wipe is already implemented: `AppProfileStore.clear_all()` resets both the
profile overlays and the pinned map, and returns the same
`{"ok": ...}` shape the other stores use. The file lives at
`<data root>/app_profiles.json` (`utils.get_user_data_path()`, so
`BETTERFINGERS_DATA_DIR` is honoured).

**Without it:** `tests/test_data_categories.py` still passes (the store simply
is not declared), which is exactly why this is a diff and not a silent omission
— the failure mode is a privacy report that does not mention a file on disk.

---

## D-5 — `llm_engine.py`: apply the gaming completion cap

`backend/domain/gaming_policy.clamp_completion_tokens` is a **ceiling, never a
floor**: a caller asking for fewer tokens gets what it asked for, and
`active=False` returns the request untouched, so the call site needs no `if`.

The single clamp already in `_call_api` is the right place — every generation
path funnels through it.

```diff
--- a/llm_engine.py
+++ b/llm_engine.py
@@ def _call_api(self, text, system_prompt, temperature=0.3, max_output_tokens=None, few_shot=None):
         try:
             safe_max_tokens = int(max_output_tokens if max_output_tokens is not None else DEFAULT_MAX_OUTPUT_TOKENS)
         except Exception:
             safe_max_tokens = DEFAULT_MAX_OUTPUT_TOKENS
         safe_max_tokens = max(64, min(4096, safe_max_tokens))
+
+        # Wave 7 gaming policy. While a game is focused a generation that spans
+        # a teamfight instead of finishing inside a lull is the defect, so the
+        # cap is hard. clamp_completion_tokens is a ceiling and is a no-op when
+        # the active profile is not a gaming one.
+        try:
+            from backend.domain.gaming_policy import clamp_completion_tokens
+            from backend.services.app_context import get_service
+
+            _ctx = get_service().current()
+            _gaming = bool((_ctx.get("gaming_policy") or {}).get("active"))
+            safe_max_tokens = clamp_completion_tokens(safe_max_tokens, active=_gaming)
+        except Exception:  # app context is best-effort; never fail a generation on it
+            pass
```

Note the floor interaction: the existing `max(64, ...)` runs **before** this, so
the clamp must land **after** it or the 50-token cap would be lifted back to 64.
As written above it is last and wins, which is the intent.

The snapshot already carries `gaming_policy.active`, so no profile dict and no
store lookup is needed here. A call site that does have a profile dict in hand
should use `gaming_policy.is_gaming_profile(profile)` instead.

**Without it:** `MAX_COMPLETION_TOKENS = 50` is declared and tested but never
reaches a generation.

---

## D-6 — `server.py`: gaming delivery policy + the recording subscription

Two independent hunks.

### D-6a — delivery never synthesises keystrokes into a game

`perform_output_action` already normalises the requested action.
`gaming_policy.resolve_send_action` maps every input-synthesising action to
`copy_only` — the clipboard fallback the policy guarantees — and is a no-op when
inactive.

```diff
--- a/server.py
+++ b/server.py
@@ def perform_output_action(text, action="copy_only", open_chat=False):
     requested_action = str(action or "copy_only").strip().lower()
     if requested_action not in {"copy_only", "paste", "type", "open_chat_then_send"}:
         requested_action = "copy_only"
+
+    # Wave 7 gaming policy: never type into a game. Synthetic keystrokes reach
+    # whatever has focus, and in a game that is the movement keys.
+    try:
+        from backend.domain.gaming_policy import resolve_send_action
+        from backend.services.app_context import get_service
+
+        _ctx = get_service().current()
+        requested_action = resolve_send_action(
+            requested_action, active=bool((_ctx.get("gaming_policy") or {}).get("active")),
+        )
+    except Exception:  # best-effort; a context failure must not block delivery
+        pass
```

`resolve_send_action` leaves `open_chat_then_send` alone — that one opens a chat
window rather than synthesising input into the game, so it is not the hazard the
policy targets. If the release wants it blocked too, add it to that helper's
mapped set in `backend/domain/gaming_policy.py` rather than special-casing here.

### D-6b — push the recording state into the service

The service is **told** the recording state; it never polls or reaches into the
recorder (`tests/test_app_context.py` asserts it imports no recorder module).
The one place `server.py` already reads `hotkey_manager.is_recording` is the
runtime-status builder, which the renderer polls, so it is a natural push point
and costs nothing extra.

```diff
--- a/server.py
+++ b/server.py
@@ (the runtime status dict builder, ~line 650)
-        "recording_active": bool(getattr(hotkey_manager, "is_recording", False)) if hotkey_manager else False,
+        "recording_active": _publish_recording_state(
+            bool(getattr(hotkey_manager, "is_recording", False)) if hotkey_manager else False
+        ),
```

with the helper near it:

```python
def _publish_recording_state(active: bool) -> bool:
    """Tell the application-context service whether a recording is running.

    A profile that changed the injection policy underneath an in-flight
    dictation would change where that dictation lands, so the service holds
    profile changes while this is True and applies them when it clears.
    Returns the value unchanged so the caller reads as it did before.
    """
    try:
        from backend.services.app_context import get_service

        get_service().set_recording_active(active)
    except Exception:  # best-effort; never fail /runtime/status on it
        pass
    return active
```

A tighter integration would call `set_recording_active` from the recording
start/stop routes (`/runtime/recording/start`, `/runtime/recording/stop`)
directly, which removes the dependency on the status poll's cadence. That is the
better long-term shape; the diff above is the minimal one and does not touch
`recorder.py` (sup-audio's territory this wave).

**Without it:** a profile switch can land during a recording. In practice the
window is small and the service still debounces, but "never interrupts an active
recording" is a Gate 7 criterion and this is the line that makes it true.

---

## Gate 7 checklist — evidence, or an honest block

The plan's Gate 7 criteria (§ wave table, row 7) are: *unknown is safe, Wayland
is honest, no recipient inference, profile changes do not interrupt work.*

| Criterion | Status | Evidence |
|---|---|---|
| Unknown is safe | **EVIDENCED** | `ResolutionTests.test_unknown_resolves_to_default_and_says_so`, `…_an_unrecognised_application_resolves_to_default_not_a_guess`. Default's match rules are empty (`test_default_and_generic_game_match_nothing`), so it is a fallback, never a guess. |
| Wayland is honest | **EVIDENCED** | `test_wayland_empty_detection_stays_default_and_unknown` — empty detection reports `source="unknown"`, `detected=False`. UI: `describeDetected` renders "Not identified on this desktop session", asserted in `applicationProfiles.test.mjs` and QA `unknown-application-shows-no-status-cell`. |
| No recipient inference | **EVIDENCED** | `NoInferenceTests` walks every snapshot the service can produce against `FORBIDDEN_OUTPUT_TERMS`; `SanitizeTests` proves the schema drops and *reports* recipient/contact/conversation/intent keys; renderer test "nothing rendered names a recipient…"; detection is class-only and `test_a_window_title_is_never_used_as_a_match_input` proves a title like "Priya - Discord" does not match. |
| Profile changes do not interrupt work | **EVIDENCED (unit) / PARTIAL (wired)** | `RecordingTests` proves a switch during recording is held and applied only when recording ends, and that subscribers see it only then. `test_applying_a_profile_touches_no_model_lifecycle` proves no model module is imported. **Blocked half:** the recording state is only actually pushed once D-6b lands. |
| Debounce | **EVIDENCED** | `DebounceTests` — transient focus, settled focus, and flapping. |
| Schema v1 exactly as specified | **EVIDENCED** | `SchemaTests.test_every_builtin_is_a_complete_v1_document` pins the field set to `PROFILE_FIELDS`. |
| Required built-in profiles | **EVIDENCED** | `test_builtin_ids_are_the_required_set` (all seven). Match-rule honesty: `test_match_rules_are_lowercase_class_level_names`; uncertain matchers are named and *excluded* with a comment in `BUILTIN_PROFILES`. |
| Atomic, migration-safe store under the unified data root | **EVIDENCED** | `test_writes_are_atomic_and_leave_no_temp_files`, `test_corrupt_file_degrades_to_the_builtins`, `test_hand_edited_record_degrades_field_by_field`, `test_missing_schema_version_still_reads`. Root is `utils.get_user_data_path()` → `app_paths.resolve_base()`, which honours `BETTERFINGERS_DATA_DIR`. |
| Gaming policy constants | **EVIDENCED (declared) / BLOCKED (consumed)** | `tests/test_gaming_policy.py` pins every value and helper. **Blocked:** consumption needs D-5 and D-6a. |
| Status cell absent when unknown/Default | **EVIDENCED** | `statusBar.test.mjs` — Default and unknown both yield `null`, not an em dash. |
| Settings section with override controls | **EVIDENCED (unit) / BLOCKED (prod QA)** | `applicationProfiles.test.mjs` covers availability, list, override, pin-the-selected-profile, and the no-recipient rule. **Blocked on D-3b only:** D-1/D-2/D-3 have landed, but the four api helpers are not exported, so the feature is correctly unreachable and the ten `wave7-app-context` scenarios cannot pass yet. |
| Privacy declaration | **BLOCKED** | Needs D-4; the store is written and its `clear_all()` is tested, but the category is not declared until that diff lands. |

## What is NOT in this list

* `utils.py`, `injector.py`, `injection_pacing.py` — **unchanged and untouched.**
  Wave 7 builds on the existing detection rather than replacing it:
  `app_context.normalize()` delegates to `injection_pacing.normalize_app`, so an
  app key means the same thing in both features, and the pacing consumers keep
  calling `detect_active_app_key` exactly as before.
* `recorder.py`, `audio_ducker.py` — sup-audio's territory this wave; the
  recording state arrives as a push (D-6b), never a read.
* `app/src/renderer/features/settingsWorkspace.js` — the Application Profiles UI
  is a **group inside the existing AI Cleanup section**, not an eighth Settings
  section, because `SETTINGS_SECTIONS` and its nav/section element maps are owned
  by that module: a nav button with an id it does not know would never be hidden
  when another section is active and would render on top of every other section.
  Promoting this to its own section is a `settingsWorkspace.js` change and a
  deliberate follow-up, not a markup one.
