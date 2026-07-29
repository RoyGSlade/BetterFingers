# Wave 11 integration-owned diffs

Wave 11 touched four integration-owned files. Per the wave constraints the
lane did **not** edit them; the exact intended change is written out here for
the release director to apply at integration, the same discipline Waves 5, 7,
9 and 10 used.

Each diff has a test that is **failing right now** and turns green the moment
the diff lands. That is deliberate: the failing test *is* the integration
checklist, so an unapplied diff cannot be forgotten silently.

| # | File | Change | Test that gates it |
|---|---|---|---|
| 1 | `app/package.json` | `version` → `0.2.0-alpha.1` | `tests/test_version_source.py::test_electron_package_version_matches`, `app/tests/versionSource.test.mjs` |
| 2 | `server.py` | `/runtime/version` reads `version.py` | `tests/test_version_source.py::test_runtime_version_endpoint_reports_the_single_source` |
| 3 | `server.py` | support-report version block reads `version.py` | `tests/test_version_source.py::test_support_report_version_block_reports_the_single_source` |
| 4 | `app/src/main/windows.js` | the default flip | `tests/test_rollback_store_parity.py::test_the_flip_is_reversible_by_environment_alone` |

Current status: **5 tests failing, all five of them these diffs** (diff 1 trips
two version assertions). Nothing else in the Wave 11 workset is red — backend
`3011 passed / 5 failed / 3 skipped`, renderer `1299/1300`, and every one of
those 6 failures is on this list.

Nit for the integrator: `tests/test_parity_evidence_report.py` started as a
scratch report and ended up as the evidence-collector regression guard. Its
contents are correct; the filename is a leftover. Rename to
`tests/test_parity_evidence.py` if you are touching it anyway — this lane
could not delete files.

---

## 1 — `app/package.json`: the release version

`app/package.json` is the one place npm requires a literal, so it is a *copy*
of `VERSION` rather than a second source. `tests/test_version_source.py` and
`app/tests/versionSource.test.mjs` both assert the two are equal, which is
what keeps the copy non-authoritative.

```diff
 {
   "name": "betterfingers",
-  "version": "0.1.0",
+  "version": "0.2.0-alpha.1",
```

This field is also what electron-builder turns into release artifact
filenames, so it is the manifest-naming half of D-0008 as well as the
renderer-display half (`app.getVersion()` → `config.js` `APP_VERSION` →
`app:get-version` IPC → `.sd-nav__version-num`).

## 2 — `server.py`: `/runtime/version`

Add the import alongside the other first-party imports (after `from
store_migration import get_degraded_events`, order is not load-bearing):

```diff
+import version
```

Then at the handler (currently `server.py:2474`):

```diff
 @app.get("/runtime/version")
 async def runtime_version():
     return {
-        "backend_version": "0.1.0",
-        "expected_electron_api_version": "0.1.0",
+        "backend_version": version.BACKEND_VERSION,
+        "expected_electron_api_version": version.APP_VERSION,
         "schema_version": 1,
         "config_version": 1,
     }
```

`schema_version` and `config_version` deliberately stay literals. They are the
compatibility contract `app/src/main/config.js` checks and they have their own
cadence — a marketing version bump must not silently claim an API change.

## 3 — `server.py`: the support-report version block

At `server.py:4318`:

```diff
     # --- version (source of truth: /runtime/version) ---
-    version = {"backend_version": "0.1.0", "profile_schema_version": 1, "config_version": 1}
+    version_block = {
+        "backend_version": version.BACKEND_VERSION,
+        "profile_schema_version": 1,
+        "config_version": 1,
+    }
```

Note the **rename**: the local was called `version`, which would now shadow the
imported `version` module inside that function. Every later use of the local in
that function body must be renamed to `version_block` in the same edit —
`support_report._render_version()` reads `data["version"]`, so the *key* stays
`"version"` and the report's output is unchanged.

## 4 — `app/src/main/windows.js`: the default flip

At `windows.js:210-222`:

```diff
-// Opt-in only, and deliberately not a persisted setting: the Signal Desk
-// workspace UI (DESIGN.md §11) is landing incrementally and is not at feature
-// parity with index.html yet, so it must not be reachable by accident. The
-// default is unchanged for every shipping user.
-const SIGNAL_DESK_PAGE = 'signal-desk-preview.html';
-// The production composition root (D-0007). Also opt-in until the Wave 11
-// default flip; BF_UI=signal-desk keeps routing to the QA preview above.
-const SIGNAL_DESK_PROD_PAGE = 'signal-desk.html';
-
-function dashboardPage() {
-  if (process.env.BF_UI === 'signal-desk-prod') return SIGNAL_DESK_PROD_PAGE;
-  return process.env.BF_UI === 'signal-desk' ? SIGNAL_DESK_PAGE : 'index.html';
-}
+// The DESIGN/mockup preview page (D-0007). QA target only — never a
+// production route, and deliberately still behind BF_UI=signal-desk so the
+// preview QA scenarios keep a page to run against.
+const SIGNAL_DESK_PREVIEW_PAGE = 'signal-desk-preview.html';
+// The production composition root, and since Wave 11 the DEFAULT: this is
+// what a user with no BF_UI set gets.
+const SIGNAL_DESK_PROD_PAGE = 'signal-desk.html';
+// The pre-Signal-Desk dashboard. Kept reachable, but only on request: it is
+// the rollback path if the flip has to be backed out in the field, not a
+// second product. Both pages read the same backend stores, so flipping
+// forward and rolling back lose nothing — see
+// tests/test_rollback_store_parity.py.
+const LEGACY_PAGE = 'index.html';
+
+function dashboardPage() {
+  if (process.env.BF_UI === 'legacy') return LEGACY_PAGE;
+  if (process.env.BF_UI === 'signal-desk') return SIGNAL_DESK_PREVIEW_PAGE;
+  // `signal-desk-prod` still resolves, so every Wave 1-10 command line and
+  // committed QA invocation keeps working; it is now a synonym for the
+  // default rather than the only way in.
+  return SIGNAL_DESK_PROD_PAGE;
+}
```

Behaviour table after the diff:

| `BF_UI` | Page |
|---|---|
| *(unset)* | `signal-desk.html` ← **the flip** |
| `signal-desk-prod` | `signal-desk.html` (compatibility synonym) |
| `legacy` | `index.html` (rollback path) |
| `signal-desk` | `signal-desk-preview.html` (QA only) |
| anything else | `signal-desk.html` |

The last row is a judgement call worth stating: an unrecognised `BF_UI` falls
through to the production page rather than erroring. A typo'd env var should
give a user the shipping product, not a dead app — and the old code had the
same shape (anything unrecognised fell through to `index.html`).

## Not required, but recommended in the same commit

`app/src/main/senderValidation.js:16-24` — comment-only. Both pages are already
in `RENDERER_PAGES` and the flip needs no functional change there, but the
comments still describe `signal-desk.html` as reachable "until the Wave 11
default flip", which will read as stale:

```diff
-  // Signal Desk (DESIGN.md §11), reachable via BF_UI=signal-desk. This entry
+  // The Signal Desk QA preview (DESIGN.md §11, D-0007), reachable via
+  // BF_UI=signal-desk. This entry
   // is load-bearing, not bookkeeping: a page missing from this set still
   // loads, but every IPC call from it is rejected, so `window.betterFingers`
   // is absent. The renderer is pervasively optional-chained, so that surfaces
   // as a silently dead UI rather than an error.
   'signal-desk-preview.html',
-  // Production Signal Desk composition root, reachable via
-  // BF_UI=signal-desk-prod until the Wave 11 default flip.
+  // The production Signal Desk composition root, and since Wave 11 the
+  // DEFAULT page. `index.html` above stays listed because BF_UI=legacy must
+  // keep a working IPC bridge — a rollback to a page whose every IPC call is
+  // rejected would look like a working app that silently does nothing.
   'signal-desk.html',
```

`tests/test_rollback_store_parity.py::test_the_flip_is_reversible_by_environment_alone`
already asserts both pages stay in that set, so the functional guarantee is
covered whether or not the comment is updated.

## Files this wave DID edit

For completeness, so the review boundary is unambiguous — none of these are
integration-owned:

- new: `VERSION`, `version.py`, `tools/parity_validator.py`,
  `tools/parity_evidence.py`, `tools/parity_ledger_build.py`,
  `tests/test_version_source.py`, `tests/test_rollback_store_parity.py`,
  `tests/test_parity_inventory.py`, `tests/test_parity_regen.py`,
  `tests/test_parity_evidence_report.py`, `app/tests/versionSource.test.mjs`,
  `app/tests/qaTargets.test.mjs`, `app/tests/qa/scenarios/default-flip.mjs`,
  `docs/release/WAVE11_BLOCKERS.md`, this file
- edited: `app/scripts/build-backend.js` (bundle `VERSION` into the sidecar),
  `app/tests/qa/harness.mjs` (targets), `app/tests/qa/run.mjs` (scenario
  filter), `app/tests/qa/scenarios/index.mjs` (registry),
  `app/tests/qa/scenarios/signal-desk-prod-sweep.mjs` (Utilities sub-sections
  + late-wave surfaces), `app/src/renderer/signal-desk-preview.html` (dead
  hardcoded version removed), `docs/release/PARITY_INVENTORY.md`,
  `docs/release/RELEASE_BOARD.md`, `docs/release/KNOWN_LIMITATIONS.md`
