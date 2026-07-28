# Wave 9 — documented integration diffs (Gate 9)

Wave 9 (the restricted action engine, binding ruling **D-0011**) ships ten new
files that are complete and tested on their own. Six **integration-owned** files
have to change before the feature is reachable from the app. `sup-actions` did
not edit any of them; every required edit is written out below, exactly, with
the reason it is needed and what breaks without it.

Ordering matters for one chain: the route module must be mounted (D-1) before
the proxy allowlist (D-2) does anything useful, and both must land before the
api helpers (D-3) can succeed — and all three before any `signal-desk-prod` QA
of the `wave9-actions` scenarios can pass.

| # | File | Status | Status without the diff |
|---|------|--------|------------------------|
| D-1 | `server.py` | outstanding | `/workflows/*` returns 404 |
| D-2 | `app/src/main/backendProxy.js` | outstanding | renderer cannot reach the routes; the builder renders its honest "not reachable" state |
| D-3 | `app/src/renderer/api/backend.js` | outstanding | same as D-2 — the feature has no api methods to call |
| D-4 | `app/src/main/ipc.js` + `app/src/preload/preload.js` | outstanding | the confirmed application registry never reaches the renderer, so every `launch_app` step is refused as an unknown application |
| D-5 | `data_categories.py` + `tests/test_data_categories.py` | outstanding | two persistent stores exist that the privacy report does not declare |
| D-6 | `app/src/renderer/features/utilitiesWorkspace.js` | **optional** | the builder lives inside Utilities › Advanced instead of getting its own sub-section |

## Files Wave 9 added (not integration-owned; already in the tree)

| File | What it is |
|---|---|
| `backend/domain/actions.py` | restricted action schema v1: the closed vocabulary, the prohibited list with refusal reasons, URI/path normalisation and bounds |
| `backend/services/action_validator.py` | target validation against the confirmed registry, exact preview generation, partial-failure reporting |
| `backend/services/workflow_store.py` | unified-root persistent store; saved disabled-or-enabled and always unapproved; code-only run history |
| `backend/api/routes/actions.py` | the `/workflows/*` adapters (needs D-1 to be mounted) |
| `voice_commands.py` (extended) | the five-way classification layer on top of the existing conservative parser |
| `app/src/main/applicationRegistry.js` | discovery + user-confirmed application registry (main process) |
| `app/src/main/applicationLauncher.js` | Linux launch adapters (argv arrays) + the honestly-unqualified Windows adapter |
| `app/src/renderer/features/workflowBuilder.js` | the describe → compile → preview → approve → save → run flow |
| `app/electron.vite.config.js` | the two new main inputs (the Wave 1 lesson — see the note at the end) |
| `app/tests/qa/scenarios/wave9-actions.mjs` | eleven `signal-desk-prod` scenarios |

---

## D-1 — `server.py`: mount the route module

The other route modules are already registered this way; this is the same one
line in the same block at the end of the file.

```diff
--- a/server.py
+++ b/server.py
@@ (the app.include_router block at the end of the file)
 app.include_router(routes_library.router)
 app.include_router(routes_app_context.router)
+app.include_router(routes_actions.router)
```

and, alongside the other route-module imports:

```diff
+from backend.api.routes import actions as routes_actions
```

Match whatever import spelling the neighbouring route modules already use; the
module object is `backend.api.routes.actions` and its router attribute is
`router`.

**Without it:** every `/workflows/*` request 404s. Note that
`tests/test_action_routes.py` mounts the router onto a bare FastAPI app of its
own, so the routes are fully tested either way — this diff is about
reachability, not correctness.

---

## D-2 — `app/src/main/backendProxy.js`: nine allowlist entries

`ROUTE_ALLOWLIST` is an exact `(method, route)` table, not a prefix match.
Nothing else in the file changes — no new method, no new param shape.

```diff
--- a/app/src/main/backendProxy.js
+++ b/app/src/main/backendProxy.js
@@ ROUTE_ALLOWLIST.GET
     // Wave 7 application context: read-only status + profile list.
     '/app-context/status', '/app-context/profiles',
+    // Wave 9 restricted actions. Read-only: the closed action vocabulary, the
+    // saved workflows, and the code-only run history. Nothing here launches
+    // anything -- execution is the main process's job, not a route's.
+    '/workflows', '/workflows/vocabulary', '/workflows/history',
   ],
@@ ROUTE_ALLOWLIST.POST
     '/library/clear',
+    // Wave 9. compile writes nothing; save always stores unapproved; approve
+    // records the exact preview lines the user read; run is the gate, and
+    // run/record files the per-step status codes.
+    '/workflows/compile', '/workflows/save', '/workflows/approve',
+    '/workflows/enable', '/workflows/delete',
+    '/workflows/run', '/workflows/run/record',
   ],
```

**Without it:** the renderer's request is refused in the main process. This also
blocks QA — `app/tests/qa/harness.mjs` runs a real HTTP stub that the app
reaches *through* this proxy, so the stub is behind the allowlist too. The
feature degrades honestly (one sentence saying it is not reachable) rather than
rendering an empty workflow list, but ten of the eleven `wave9-actions`
scenarios cannot pass until this lands. (The first one —
`the-builder-states-what-a-workflow-can-never-do` — asserts the static
boundary text and the dead Run button, and passes in the degraded state.)

> **Note on `/workflows` vs `/workflows/vocabulary`.** The table matches exact
> paths, so both are listed; `/workflows` alone does not cover its children.

---

## D-3 — `app/src/renderer/api/backend.js`: six helpers, defined **and exported**

`app/src/renderer/features/workflowBuilder.js` calls exactly these names and
checks for them with `typeof === 'function'` before doing anything
(`computeAvailability`). Updates go by POST rather than PATCH for the same
reason the contacts helpers do: the proxy allowlist is keyed by method and
carries only GET/POST/DELETE.

**Export them in the same change.** Wave 7's D-3b was a whole extra
round-trip caused by exactly this: the four helpers landed as function
declarations but were not added to the module's single explicit `export { … }`
block, so `import * as api` saw them as `undefined`, the feature correctly
reported itself unreachable, and every scenario stayed blocked. This module has
one export block; a helper that is not in it does not exist.

```diff
--- a/app/src/renderer/api/backend.js
+++ b/app/src/renderer/api/backend.js
@@ (with the other URL constants)
+const WORKFLOWS_URL = `${BACKEND_ORIGIN}/workflows`;
@@ (with the other feature helper groups, e.g. after the application-context block)
+// --- Restricted workflows (Wave 9) ------------------------------------------
+//
+// compile writes nothing; save always stores the workflow UNAPPROVED; approve
+// carries the exact preview lines the user read; run is a gate that returns a
+// verdict, never a side effect.
+
+async function fetchWorkflows(timeoutMs = 2500) {
+  return fetchJson(WORKFLOWS_URL, timeoutMs);
+}
+
+async function fetchWorkflowHistory(workflowId = '', limit = 20, timeoutMs = 2500) {
+  const query = `?workflow_id=${encodeURIComponent(workflowId)}&limit=${limit}`;
+  return fetchJson(`${WORKFLOWS_URL}/history${query}`, timeoutMs);
+}
+
+async function compileWorkflow(workflow, context, timeoutMs = 4000) {
+  return postJson(`${WORKFLOWS_URL}/compile`, { workflow, context }, timeoutMs);
+}
+
+async function saveWorkflow(workflow, enabled = false, timeoutMs = 2500) {
+  return postJson(`${WORKFLOWS_URL}/save`, { workflow, enabled }, timeoutMs);
+}
+
+async function approveWorkflow(workflowId, preview, timeoutMs = 2500) {
+  return postJson(`${WORKFLOWS_URL}/approve`, { workflow_id: workflowId, preview }, timeoutMs);
+}
+
+async function runWorkflow(workflowId, context, timeoutMs = 4000) {
+  return postJson(`${WORKFLOWS_URL}/run`, { workflow_id: workflowId, context }, timeoutMs);
+}
@@ (the export block, alongside the other feature helper groups)
   fetchAppProfiles,
+  fetchWorkflows,
+  fetchWorkflowHistory,
+  compileWorkflow,
+  saveWorkflow,
+  approveWorkflow,
+  runWorkflow,
```

Verify with a one-liner before running QA — a defined-but-unexported helper is
invisible to every test that does not import the module namespace:

```
node -e "import('./app/src/renderer/api/backend.js').then(m => console.log(
  ['fetchWorkflows','fetchWorkflowHistory','compileWorkflow','saveWorkflow','approveWorkflow','runWorkflow']
    .map(n => n + ':' + typeof m[n]).join(' ')))"
```

All six must print `:function`. Note the argument shapes: `compileWorkflow` and
`runWorkflow` take `(payload, context)` and `saveWorkflow` takes
`(payload, enabled)` — `workflowBuilder.js` calls them that way, and
`app/tests/workflowBuilder.test.mjs` pins those signatures against a fake api.

**Without it:** `computeAvailability` reports the feature unavailable and it
paints the "not reachable" sentence. That is the designed degraded state, not a
crash.

---

## D-4 — `app/src/main/ipc.js` + `app/src/preload/preload.js`: the registry bridge

The confirmed application registry is owned by the **main process**, which is
the side that can see the desktop — the architecture boundary in the release
plan puts OS-facing discovery there and keeps Python out of it. The renderer
needs two things from it: the list of confirmed applications (to send as the
validation context) and the discover/confirm pair (to add one).

Three handlers in `ipc.js`, alongside the existing `onboarding:*` group:

```js
// Wave 9 restricted actions. The registry is the ONLY thing a workflow may
// name, so these channels are the boundary: discovery returns unconfirmed
// candidates, and only applications:confirm writes an entry.
const { createApplicationRegistry } = require('./applicationRegistry');
const { execFile } = require('node:child_process');

let _applicationRegistry = null;
function applicationRegistry() {
  if (!_applicationRegistry) {
    _applicationRegistry = createApplicationRegistry({ execFile });
  }
  return _applicationRegistry;
}

ipcMain.handle('applications:list', () => ({ ok: true, entries: applicationRegistry().list() }));
ipcMain.handle('applications:discover', async () => ({
  ok: true, candidates: await applicationRegistry().discover(),
}));
ipcMain.handle('applications:confirm', (_event, payload) => applicationRegistry().confirm(payload));
ipcMain.handle('applications:remove', (_event, { id } = {}) => applicationRegistry().remove(id));
```

and the matching bridge in `preload.js`, inside the existing `api` object:

```diff
--- a/app/src/preload/preload.js
+++ b/app/src/preload/preload.js
@@ (with the other typed operation groups, e.g. after `onboarding`)
+  // Wave 9. Discovery returns UNCONFIRMED candidates; confirm is the only
+  // writer. Nothing here launches anything.
+  applications: {
+    list: () => ipcRenderer.invoke('applications:list'),
+    discover: () => ipcRenderer.invoke('applications:discover'),
+    confirm: (entry) => ipcRenderer.invoke('applications:confirm', entry),
+    remove: (id) => ipcRenderer.invoke('applications:remove', { id }),
+  },
```

`app/src/renderer/bootstrap/signalDeskApp.js` already reads
`window.betterFingers.applications.list()` and caches `payload.entries`; it
degrades to an empty registry when the bridge is absent.

**A LAUNCH CHANNEL IS DELIBERATELY NOT IN THIS DIFF.** `applicationLauncher.js`
is written and tested but is not wired to an IPC channel, because the run path
needs the gate in front of it: the main process must call `POST /workflows/run`,
receive `ok: true` plus the preview, execute the steps, and post the per-step
status codes back to `/workflows/run/record`. Exposing a bare
`applications:launch` channel first would create a way to start an application
that never passes the approval gate — the single thing Wave 9 exists to prevent.
That wiring is a deliberate follow-up, listed as **BLOCKED** in the Gate 9 table
below rather than half-shipped here.

**Without it:** the renderer sends an empty registry, so every `launch_app`,
`focus_app` and `wait_for_process` step is refused as an unknown application.
That is the fail-closed state working as designed, and it is honest on screen —
but it means no launch workflow can be approved end to end.

---

## D-5 — `data_categories.py`: declare the two new stores

A persistent store the privacy report does not declare is a report that lies by
omission — the same rule the `contacts` and `app_profiles` entries were added
under, in the same change that created their stores.

**Both are `personal`, not `configuration`, and that is deliberate.** The
workflow bodies are settings-shaped, but a workflow names the applications this
person runs and the folders they keep work in, and the run history records when
they ran them. The application registry is the same fingerprint in a more direct
form. Under-claiming either would defeat the privacy report.
`may_contain_user_text` is `True` for `launcher_workflows`: a workflow carries
trigger phrases and notification/confirmation messages the user wrote. It is
`False` for `application_registry`: ids, display names, app ids and paths only.

Exact `_cat` lines, to be inserted in the **Personal data** block (after the
`app_profiles` entry):

```python
    # Launcher workflows (Wave 9). Personal rather than configuration: a
    # workflow names the applications this person runs and the folders they
    # keep work in, and the same file holds the run history. user_text because
    # trigger phrases and notification/confirmation messages are prose the user
    # wrote. Run history itself holds status CODES only -- never speech.
    _cat("launcher_workflows", "Launch workflows & run history", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         in_export=True, user_text=True),
    # Confirmed application registry (Wave 9). Electron-owned: the main process
    # is the side that can see the desktop. A behavioural fingerprint -- which
    # applications this person has installed and confirmed -- with no prose.
    _cat("application_registry", "Confirmed applications", "electron", "personal",
         "Kept until personal data is cleared (Electron-owned).", _PERSONAL,
         in_export=True, user_text=False),
```

And the matching addition to the hard-coded guard in
`tests/test_data_categories.py` (the set is deliberately not auto-derived):

```diff
--- a/tests/test_data_categories.py
+++ b/tests/test_data_categories.py
@@ EXPECTED_IDS
     "cloned_voices", "personas", "dictionary", "macros", "contacts", "wake_models",
     "app_profiles",
+    "launcher_workflows", "application_registry",
     "mcp_config", "graph_data", "debug_log", "sidecar_raw_log", "support_report",
```

Wipe is already implemented on both sides:
`WorkflowStore.clear_all()` resets the workflows and the history together and
returns the same `{"ok": …}` shape the other stores use, and
`createApplicationRegistry().clearAll()` does the same for the registry.

* `<data root>/launcher_workflows.json` — `utils.get_user_data_path()`, so
  `BETTERFINGERS_DATA_DIR` is honoured.
* `<data root>/application_registry.json` — `main/userDataRoot.js`, the Node
  mirror of the same resolution.

**Without it:** `tests/test_data_categories.py` still passes (the stores simply
are not declared), which is exactly why this is a diff and not a silent omission
— the failure mode is a privacy report that does not mention two files on disk.

---

## D-6 — `utilitiesWorkspace.js`: promote the builder to its own sub-section (optional)

The Launch Workflows UI is a **group inside the existing Utilities › Advanced
section**, not a sixth Utilities sub-section, because `UTILITIES_SECTIONS` and
its nav/section element maps are owned by
`app/src/renderer/features/utilitiesWorkspace.js`: a nav button with an id it
does not know would never be hidden when another section is active and would
render on top of every other section. This is the same resolution Wave 7
documented for the Settings nav, and for the same reason.

If the release wants it promoted, it is three coordinated edits in that one
file plus two in the markup:

```diff
--- a/app/src/renderer/features/utilitiesWorkspace.js
+++ b/app/src/renderer/features/utilitiesWorkspace.js
@@ UTILITIES_SECTIONS
-export const UTILITIES_SECTIONS = ['models', 'speech', 'text', 'diagnostics', 'advanced'];
+export const UTILITIES_SECTIONS = ['models', 'speech', 'text', 'diagnostics', 'workflows', 'advanced'];
@@ UTILITIES_ELEMENT_IDS
+  navWorkflows: 'sdUtilNavWorkflows',
+  sectionWorkflows: 'sdUtilSectionWorkflows',
@@ renderSectionNav() and bindSectionNav() -- BOTH maps, they are separate literals
-    const navEls = { models: …, speech: …, text: …, diagnostics: …, advanced: els.navAdvanced };
+    const navEls = { models: …, speech: …, text: …, diagnostics: …, workflows: els.navWorkflows, advanced: els.navAdvanced };
```

and in `signal-desk.html`, a `<button id="sdUtilNavWorkflows" data-util-nav="workflows">`
plus wrapping the existing `#sdUtilWorkflowGroup` in
`<section class="sd-util-section" id="sdUtilSectionWorkflows" hidden>`.

The `wave9-actions` QA scenarios navigate via `#sdUtilNavAdvanced`; promoting
the section means changing that one line in `openWorkflows()`.

**Without it:** nothing breaks. The builder is reachable at Utilities ›
Advanced › Launch Workflows, which is where the QA scenarios expect it.

---

## Gate 9 checklist — evidence, or an honest block

The plan's Gate 9 criteria (§7 wave table, row 9) are: *unsupported actions and
unknown commands cannot execute; partial failure is visible.*

| Criterion | Status | Evidence |
|---|---|---|
| Unsupported actions cannot execute — schema half | **EVIDENCED** | `tests/test_actions_schema.py::RefusalTests` — every one of the fifteen prohibited verbs is refused *with its reason* and never survives into the compiled steps (`test_every_prohibited_verb_is_refused_when_it_appears_as_a_step`, `test_a_prohibited_step_never_survives_into_the_compiled_steps`); spelling variants and aliases are canonicalised first (`ClassifyTests`); `ok` is False for the whole workflow, so nothing partial can be saved. |
| Unsupported actions cannot execute — store half | **EVIDENCED** | `tests/test_workflow_store.py::SaveTests::test_a_workflow_containing_a_prohibited_step_is_refused_with_its_reasons` (nothing is even written to disk) and `DurabilityTests::test_a_hand_edited_file_that_adds_a_shell_step_loses_the_whole_record` — a file edited by hand does not become a runnable workflow. |
| Unsupported actions cannot execute — UI half | **EVIDENCED (unit) / BLOCKED (prod QA)** | `app/tests/workflowBuilder.test.mjs` — a refusal blocks Save and Run and is rendered as the backend's own sentence. **Blocked on D-2/D-3:** QA `a-prohibited-step-is-refused-with-a-reason-and-nothing-saves` cannot run until the routes are reachable. |
| Workflows cannot escape the application registry | **EVIDENCED** | `tests/test_action_validator.py::RegistryEscapeTests` — unconfirmed and unknown applications are refused for `launch_app`, `focus_app` and `wait_for_process` alike; `index_registry` keeps only `confirmed` entries; an unregistered URI scheme is refused (`UriSchemeTests`); folders are bounded with a separator guard (`test_a_sibling_directory_with_a_shared_prefix_is_not_inside_the_root`). |
| Unknown commands cannot execute | **EVIDENCED** | `tests/test_voice_commands.py::UnknownCommandTests::test_an_unknown_command_can_never_execute` — every unknown phrase, in every clear command context, yields `executable=False`, no workflow id and no intent. Near-miss trigger phrases are unknown, not fuzzy launches (`LauncherWorkflowTests`). |
| Unknown commands explain themselves and offer the builder | **EVIDENCED** | `test_an_unknown_command_explains_itself_and_offers_the_builder`, `test_the_launch_shaped_explanation_still_refuses`. |
| No generated shell command is ever shown as a solution | **EVIDENCED** | `test_no_explanation_ever_hands_the_user_a_command_line` (backend), `no rendered refusal or hint ever contains a command line` (renderer), `test_every_prohibition_carries_a_reason_a_person_can_read` (the refusal text itself). QA `no-refusal-ever-offers-a-command-line-as-a-workaround` asserts it against the whole rendered group. |
| Partial failure is visible | **EVIDENCED** | `tests/test_action_validator.py::PartialFailureTests` — two of three is `partial` and `ok` is False; steps that never ran are reported as `skipped` rather than omitted; an unrecognised status code reads as `failed`, never as success. `describeRunSummary` never says "finished" for a partial run. |
| Exact preview | **EVIDENCED** | `PreviewTests::test_the_preview_is_ordered_and_names_the_resolved_launch_target` pins the exact strings (`1. Launch Obsidian (flatpak run md.obsidian.Obsidian)`); no preview at all is produced when anything was refused. |
| Approval precedes running | **EVIDENCED** | `tests/test_workflow_store.py::RunGateTests` (all five branches) and `tests/test_action_routes.py::SaveApproveRunTests` — including `test_a_registry_change_after_approval_blocks_the_run`, where nobody edited the workflow and the approval no longer describes what would happen. |
| Saved disabled or enabled, always unapproved | **EVIDENCED** | `SaveTests::test_a_saved_workflow_is_never_approved_and_defaults_to_disabled`, `test_a_workflow_can_be_saved_enabled_and_still_is_not_approved`, `ApprovalTests::test_editing_the_steps_revokes_the_approval`. |
| Run history stores status codes, never user speech | **EVIDENCED** | `HistoryTests::test_history_stores_status_codes_and_no_user_speech` and `test_a_summary_carrying_prose_fields_has_them_dropped` — a summary carrying a transcript and a folder path has both dropped by the sanitiser, not by caller discipline. |
| Argument arrays, never a shell string | **EVIDENCED** | `app/tests/applicationLauncher.test.mjs` — `every launch method spawns with shell:false and an args array`, `shell metacharacters in confirmed fields stay inside a single argument`, `the launcher never spawns a shell binary itself`. Flatpak *discovery* uses an argv array too. |
| Linux launch priority | **EVIDENCED** | `the Linux priority order is desktop, flatpak, uri, executable, steam`, plus `an explicitly chosen method wins over the priority order`. |
| Discovery shows without trusting | **EVIDENCED** | `app/tests/applicationRegistry.test.mjs` — `every discovered candidate is unconfirmed`, `confirm is the only writer: discovery never persists anything`; an Exec line with shell syntax yields a path, never a command. |
| Windows adapter | **DESIGNED, HONESTLY UNQUALIFIED** | `resolveWindowsLaunchPlan` is real and mockable and every branch carries `qualified: false` plus a reason (`the Windows plan carries qualified:false and a reason, for every branch`). **No Windows host exists on this project; nobody has watched it launch anything.** |
| Atomic, migration-safe store under the unified data root | **EVIDENCED** | `DurabilityTests` — atomic writes leave no temp file, a corrupt file degrades to empty, a missing `schema_version` still reads, a hand-edited approval with no recorded preview is not an approval. Registry side: `a corrupt registry file degrades to empty instead of throwing`, `confirm writes … through a temp file and a rename`. |
| Voice routing extends the existing parser | **EVIDENCED** | `ParserIsPreservedTests` — same input, same answer, whether asked through `parse_command` or through the classifier. Every pre-existing `parse_command` test still passes unchanged, and `tests/test_server_voice_commands_execute.py` (its production consumer) is green. |
| Privacy declaration | **BLOCKED** | Needs D-5. Both stores are written and both `clear_all`/`clearAll` are tested, but the categories are not declared until that diff lands. |
| Reachable from the app | **BLOCKED** | Needs D-1, D-2, D-3. The feature degrades honestly to "not reachable" until then. |
| A launch actually happens end to end | **BLOCKED** | Needs D-4 *plus* the gated run channel described in D-4's closing note. `applicationLauncher.js` is complete and unit-tested; it is deliberately not exposed on an IPC channel that could bypass the approval gate. |
| Production QA on `signal-desk-prod` | **BLOCKED (10 of 11 scenarios)** | `app/tests/qa/scenarios/wave9-actions.mjs` is registered and well-formed (`app/tests/workflowBuilder.test.mjs` asserts registration, uniqueness, the `signal-desk-prod` target, and the no-`:has-text` rule). Running them needs D-2/D-3. |

## What is NOT in this list

* `app/src/main/main.js`, `windows.js` — **unchanged and untouched.** Wave 9 adds
  two new main-process modules and lists them as vite inputs; nothing in the
  window or startup path changes.
* `injector.py`, `injection_pacing.py`, `recorder.py` — untouched. A workflow
  never types, and never records.
* `parse_command`'s own behaviour — **deliberately unchanged.** See the finding
  below.

## Findings for the director

1. **Pre-existing over-trigger in `parse_command` (not introduced by Wave 9).**
   `_SWITCH_PERSONA_RE` is a `search`, not an anchored match, so inside a clear
   command context *any* sentence containing "use …" resolves to
   `switch_persona` with whatever followed — "launch the thing I use for taxes"
   becomes `switch_persona("for taxes")`. Wave 9 deliberately did not change it:
   the classifier's contract is that it *calls* the conservative parser rather
   than second-guessing it, and diverging would mean two different answers to
   "is this a command" depending on the entry point. It is pinned as a
   documented regression test
   (`test_the_classifier_inherits_parse_commands_switch_persona_over_trigger`)
   and it cannot reach a launcher workflow, which is the Wave 9 boundary. The
   fix — anchor the pattern, or require the target to name a known persona —
   changes behaviour every existing caller sees, so it belongs to whoever owns
   `parse_command`.

2. **The vite-input rule had no test until now.** The Wave 1 defect (a
   main-process module missing from `electron.vite.config.js` fails at *runtime*
   as a silent no-window startup, not at build time) was fixed but never
   guarded. `app/tests/viteMainInputs.test.mjs` now walks the require closure of
   `src/main/main.js` and asserts every module in it is a declared input, and
   that every declared input exists. It passes on the current tree —
   `src/main/redact.js` is *not* flagged, because no main-process module
   requires it (it is exercised only by tests and QA scenarios), which is worth
   knowing on its own.

3. **The Electron build was not run by `sup-actions`.** `electron-vite build`
   was outside the permitted command set for this session. The two new inputs
   are asserted to exist and to be declared by the test above, and the full
   renderer unit suite (1208 tests) passes, but a real `npm run build` is a
   director-side verification.
