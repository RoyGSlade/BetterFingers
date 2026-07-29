# True BetterFingers Known Limitations

- **Release candidate:** `v0.2.0-alpha.1`
- **Baseline:** `feat/signal-desk-ui` at `093eaf2a…`
- **Last updated:** 2026-07-28

This is an honest record of the current unreleased baseline. Items here are not
automatically accepted public-release limitations. A blocker must be fixed,
cut, or explicitly accepted by the release director before Source Arcanum
publication.

## Release-control limitations

- **Gate 0 is accepted; later gates are not.** Product measurement evidence
  for tests, QA, preservation, strict parity, dependencies, sizes, and
  artifacts is complete. Repairs A–C are integrated on the pushed
  `release/true-betterfingers` branch, and the authenticated cross-client
  hierarchy smoke passed on the restarted repaired configuration on
  2026-07-28 (D-0017). Gates 1–12 remain open work: the strict parity ledger
  still records 434 `blocked` items and no distributable package exists.
- **The integrated Gate 0 workset was broader than infrastructure.** The
  [exact workset](TRUE_BETTERFINGERS_RELEASE_PLAN.md#21-integrated-wave-0-workset)
  includes `AGENTS.md`; `.claude`/`.codex` infrastructure and skills;
  `ACCOMPLISH.md` repair C; UI/release/persona docs; the regenerated Signal
  Desk QA report; and 23 regenerated PNGs that are pixel-identical but
  byte-reencoded. The coordinator reviewed and integrated that full set in
  `abafdf6`, `d320904`, and `cfe6136`.
- **Literal system Python is not a project environment.** It exits 2 with 72
  dependency-related collection errors because packages including `fastapi`,
  `numpy`, `keyboard`, and `pyperclip` are absent. The qualified `.venv` is
  green at `2,085 passed / 3 skipped`; renderer unit tests are `775/775`, the
  production build passes, and Playwright has three model-dependent skips
  beside 18 passes. Release and contributor instructions must name the
  qualified environment so the system-Python failure is not mistaken for a
  regression.
- **QA uses a deterministic stub backend.** The Wave 0 run regenerated legacy
  QA at `37/37` and Signal Desk QA at `28/28`, but those green scenario counts
  do not prove that the preview is a real production composition root or that
  its fixture-seeded workspaces use live user data.
- **Traits remain preservation-blocked.** The retained
  [baseline](PRESERVATION_BASELINE.md) and
  [JSON](PRESERVATION_BASELINE.json) record delivery `PASS 3/3` and audience
  `PASS 3/3`, both qualified-but-disabled. The corrected production True
  Janitor traits protocol ran exactly three consecutive suites and each passed
  3/3, but traits remain `unavailable_methodology_unreconciled`: valid
  historical evidence is `FAIL_TRAITS 0/3`, and the invalid earlier Wave 0
  adapter leaves qualification methodology unresolved. Under the current gate,
  the valid historical failure blocks qualification. Its `2/3`, `3/3`, and
  `3/3` observations are non-qualifying, not current evidence. W0-P1 evidence
  collection is done, but traits qualification is not a pass.
- **The strict 438-item baseline has zero production-qualified wired rows.**
  The completed [release ledger](PARITY_INVENTORY.md) records 0 `wired`,
  4 `intentional_cut`, and 434 `blocked`. Zero wired is the honest result of
  the strict production data/action/failure/accessibility/QA/privacy evidence
  rule, not a product failure count to hide. The five preview placement maps
  are a separate subset and report `159/183` placed/wired in those maps with
  `24` unwired; they do not replace the strict ledger.
- **No distributable package exists in this checkout.** The completed
  [package baseline](PACKAGE_BASELINE.md) records a
  `2026-07-28T08:11:19Z` snapshot: tracked checkout
  `525 files / 35,761,072 bytes`, `app/out`
  `30 files / 1,288,162 bytes`, and `assets` + `images`
  `14 files / 15,941,784 bytes`. The checkout count is not a live
  authoritative byte count. The Python sidecar was unbuilt, and both Windows
  and Linux had `0 artifacts / 0 bytes`; no later package build is recorded,
  so the artifact conclusion remains `ABSENT/UNBUILT`. W0-D1 is complete, but
  none of this qualifies Wave 12.

## Application and UI limitations

> **Wave 11 update (2026-07-28).** The first three bullets below are the Gate 0
> record and are now superseded: Waves 1-10 built the production composition
> root and Wave 11 flipped the default. `BF_UI` unset now opens
> `signal-desk.html`; `index.html` is the rollback path behind `BF_UI=legacy`;
> `signal-desk-preview.html` is a QA target only. Current limitations are the
> two Wave 11 bullets at the end of this section.

### Wave 12 additions (2026-07-29)

- **BetterFingers ships a dark theme only.** `#sdSetTheme` offered "System
  Preference" and "Light Theme", and `settingsWorkspace.js`'s
  `computeAppearanceClasses()` duly put a `theme-light` class on `<body>` for
  either — but no stylesheet in the renderer defines a single `theme-light`
  rule, and `color-scheme: dark` is hard-pinned on `:root`. Selecting either
  option therefore did nothing at all, which a user reasonably reads as their
  click not registering. **Both options are now disabled and labelled "not
  built yet", with a note stating that accent, density, font size and high
  contrast do all work.** They are disabled rather than removed because the
  preference is real and persisted (`pref_theme`) — hiding it would
  misrepresent an unbuilt setting as one that was never offered. Pinned by
  `app/tests/uiControlContract.test.mjs`, which asserts no `theme-light` rule
  exists; building the light theme will fail that test and tell whoever does it
  to re-enable the options. Residual: `normalizeAppearancePrefs()` still
  defaults to `system`, so a profile carrying that preference shows the
  disabled option as selected. That is honest (it says the saved preference
  needs a theme that is not built) and changing the default would alter a
  contract shared with the legacy rollback page, so it is left as follow-up.

- **Roughly 40 muted-text surfaces are below WCAG AA.** `--sd-text-muted`
  (`#5B6B7C`) measures **3.20–3.54:1** against every surface token in the
  palette, short of the 4.5:1 body-text bar, and is used as real text colour in
  descriptions, hints, empty states, meta lines and timestamps. Wave 12 fixed
  the highest-leverage consumers — the `--sd-label-color` token itself (the
  section/field label colour, `.sd-field__label` alone appears 39 times), 14
  uppercase-label selectors that hardcoded the muted token, two search
  placeholders, and `.sd-badge--error` (4.07:1 → 5.53:1 via a new
  `--sd-red-bright`) — all now 5.53–7.53:1 and asserted by computed-contrast
  tests. The remaining consumers were deliberately NOT bulk-changed: the blast
  radius is large and the change wants visual sign-off, not a blind sweep. The
  clean fix is either a scoped follow-up or re-tuning the token itself.

- **The primary workspace nav is an incomplete ARIA tablist.**
  `.sd-nav__primary` carries `role="tablist"` but its buttons use
  `aria-current="page"` (a navigation-landmark idiom) rather than
  `aria-selected`, have no `role="tab"`, and there is no arrow-key handling.
  Every item is a real `<button>` and fully reachable and operable by
  Tab/Enter, so this is an ARIA-correctness gap for screen-reader users, not a
  keyboard-reachability blocker. Fixing it properly needs a roving-tabindex and
  arrow-key handler in `features/signalDeskShell.js`.

- **Legacy is the production default.** *(Gate 0 record; superseded by the
  Wave 11 flip.)* Signal Desk was reachable only through `BF_UI=signal-desk`.
- **Signal Desk is a QA preview, not a production composition root.** It mixes
  live Talk/status/contact adapters with runtime fixtures for Library, Studio,
  Utilities, Settings, privacy, models, devices, diagnostics, jobs, and
  onboarding.
- **Production mock data is present in an Electron-loadable page.** This blocks
  Gate 1 even though the page is opt-in.
- **Onboarding is not durable application consent.** The legacy renderer uses a
  page-local `bf_onboarding_complete` value; Signal Desk's flow is QA-triggered
  and receives disposable in-memory storage.
- **Versions disagree.** Electron package `0.1.0`, preview `v1.2.0`, and planned
  release `0.2.0-alpha.1` are not centralized.
- **Strict parity closure remains.** The release ledger has 434 blocked rows
  and four intentional cuts. The separate preview maps report Talk `28/33`,
  Library `11/23`, Studio `26/31`, Utilities `57/59`, and Settings `37/37`.
  Known placement/behavior gaps include capture/emergency controls and send
  details in Talk; most item mutation/recovery semantics in Library; active
  persona, edit, metadata, and teach-from-edit gaps in Studio.

- **267 of 438 parity rows are still not `wired` after the Wave 11 re-audit.**
  Current totals are 161 `wired` / 10 `intentional_cut` / 267 `blocked`. Of the
  blocked rows, **91 have no production anchor** (a real gap — chiefly the
  hotkey and wake-word capture controls, part of the legacy model-manager
  surface, and the legacy backend status cards) and **176 are anchored in
  production but unevidenced** (no production-target QA names them, or the
  source row is prose with no code handle). Details and the ordered
  remediation list: [WAVE11_BLOCKERS.md](WAVE11_BLOCKERS.md).

- **The Persona Foundry and both overlay windows have no production-target QA.**
  All three ship in the production composition — the Foundry ids are in
  `signal-desk.html`, and `overlay.html` / `review-overlay.html` are separate
  always-on-top production windows — but `personas.mjs` runs against
  `index.html` and no scenario drives either overlay. 41 parity rows are
  blocked on this alone. It is a coverage gap, not a missing feature.

- **The legacy rollback page has a smaller privacy surface than production.**
  Ruled an intentional cut in Wave 11 (see WAVE11_BLOCKERS.md R-1): a user who
  rolls back to `BF_UI=legacy` can still wipe and export — those are
  registry-driven in the backend and identical on both pages — but cannot
  browse the store list or the persona-learning disclosure from that page.

## Contacts, audience, and traits

- **Contacts — `unavailable` / partially implemented.** Create/select and
  backend CRUD exist, but visible manage/edit/delete, retroactive draft
  application, the applied-contact status cell, integrated export/lifecycle,
  Settings disclosure, and production composition are incomplete. Contacts
  must be completed or cut.
- **Audience context — `unavailable`.** Backend prompt support exists and the
  retained real-model [preservation result](PRESERVATION_BASELINE.md) is
  `PASS 3/3`, but the default is off and no visible Settings control or
  disclosure exists. It may not silently affect output.
- **Persona traits — `unavailable`.** Schema, storage, Studio sliders, and
  prompt rendering exist. The corrected current snapshot is three consecutive
  production True Janitor suites, each `PASS 3/3`, but the historical 0/3 and
  invalid earlier methodology leave qualification unreconciled. The dictation
  path keeps traits off pending a director-approved repeated policy and
  accepted qualification.
- **Gate disclosure is incomplete.** The current UI can save trait values
  without explaining that they are disabled in live cleanup.

## Privacy and data lifecycle

- **The new data registry is inventory-only.** Its category path, size, wipe,
  verification, and export callables are still stubs. The legacy privacy route
  separately reports and wipes contacts.
- **Persistent-store coverage is incomplete for the planned release.**
  Application profiles/registry, launcher workflows, voice-profile versions,
  audio-privacy journal, controller bindings, Stream Deck configuration, wake
  training samples/classifier metadata, and other future stores must be
  registered if created.
- **Persona-learning disclosure/export requires closure.** Existing learning
  behavior is local and consent-gated, but the final privacy dashboard must
  support inspect, per-item/persona/all deletion, export, and verified wipe.
- **Factory reset across Electron and Python state is not yet qualified.**

## Platform capability limitations

No package-level support statement below is green until Wave 12 produces signed
evidence.

| Capability | Windows | Linux | Current release status |
|---|---|---|---|
| Packaged install/launch/upgrade | `unknown` | `unknown` | The measured artifact count is zero on both platforms; workflows/configuration exist, but no planned artifact has been built or qualified. |
| Direct text injection | `unknown` | `unknown` | Source adapters exist; Linux result varies by X11/Wayland and installed tools. Clipboard fallback must remain available. |
| Clipboard-only delivery | `unknown` | `unknown` | Expected fallback path exists but package matrix is not rerun. |
| Capture-stream voice isolation | `unavailable` | `unavailable` | Required new privacy guards do not exist. Windows requires a feasibility spike; Linux requires journaled Pulse/PipeWire implementation. |
| Push-to-mute fallback | `experimental` | `experimental` | Existing configurable held-key behavior exists but the new lifecycle/schema and package qualification are incomplete. |
| Active-application profiles | `unavailable` | `unavailable` | Current foreground detection serves injection pacing; shared profile resolution is not implemented. |
| Restricted launcher workflows | `unavailable` | `unavailable` | Approved schema, validator, registry, and platform adapters are not implemented. |
| Controller first-class workflow | `experimental` | `experimental` | Existing pygame/controller foundations are not qualified against the required action/reconnect/emergency-stop matrix. |
| Stream Deck | `unavailable` | `unavailable` | Official thin adapter is not implemented. |
| Wake word | `experimental` | `experimental` | Detector/training foundations exist; shared audio broker, first-word protection, license manifest, and field qualification do not. |

### GPU acceleration (Linux) — CPU-only is an accepted state, not a defect

**This is not a bug to fix; it is a supported configuration with honest
performance expectations.** `hardware_report.py` models acceleration as a
named tier ladder, `TIER_ORDER = ["cpu-only", "igpu", "dgpu-8g", "dgpu-12g+"]`
(`hardware_report.py:387`), and `cpu-only` is a first-class member of it, not
an error branch: when no CUDA/Vulkan-capable device is detected, the tier
resolves to `"cpu-only"` with `guidance = "No GPU acceleration detected.
Stick to small models (4B Q4, Whisper base/small); expect a few seconds per
utterance."` (`hardware_report.py:421-423`). `llm_engine.py` sizes its HTTP
read timeout off the same assumption: the comment at `llm_engine.py:73-76`
calls the CPU-only case the "deliberately pessimistic... floor tier" the
system is tuned around, not a fallback bolted on afterward. This machine (per
[[user-hardware]] memory: 4B model, no GPU) runs in exactly this tier. No code
path treats "no GPU" as a verdict downgrade — `assess_model_fit()` appends an
informational reason string, it does not fail the assessment
(`hardware_report.py:329-333`).

### Linux-specific limitations — Wayland vs. X11

**Global hotkeys.** The live path is Electron's `app/src/main/hotkeys.js`,
which prefers `uiohook-napi` (gives key-up events, so push-to-talk works).
When it can't load or start — Wayland is the named example, alongside a
missing `libXtst` — the app degrades at runtime (a try/catch around
`ensureHookRunning`, not an upfront session-type check) to
`globalShortcut`, which only supports toggle mode, not push-to-talk
(`app/src/main/hotkeys.js:18-21`, `223-245`). `getHotkeyCapabilities()`
reports which backend is active and whether push-to-talk is supported
(`app/src/main/hotkeys.js:340-347`). The Python-side
`platform_capabilities.supports_global_hotkeys` flag
(`platform_capabilities.py:91`, gated on `is_linux and is_x11`) is vestigial:
`hotkey_manager.py:651` logs that native keyboard hooks are disabled and
hotkeys run via Electron IPC instead, so this Python flag is not what
actually gates the live capability.

**Text injection**, in `platform_capabilities.detect_injection_method()`
(`platform_capabilities.py:45-84`):
- X11: `xdotool` only.
- Wayland: `wtype` → `ydotool` → `xdotool` (only if an XWayland `DISPLAY` is
  also present) → clipboard paste.
- Clipboard backend selection (`_detect_clipboard_backend`,
  `platform_capabilities.py:22-42`): Wayland prefers `wl-copy`; otherwise
  `xclip`/`xsel`; falls back to `wl-copy` again for the XWayland case.
- `"none"` — no injection at all — is returned only when clipboard paste
  itself is unavailable too (`platform_capabilities.py:84`).

At runtime, if the chosen tool fails mid-session, `injector.py:264-280` falls
back to clipboard paste; if even that Ctrl+V path fails, the user is told
directly: *"No input-injection tool available to send Ctrl+V; the dictated
text is on the clipboard — press Ctrl+V to paste it."*
(`injector.py:362-365`, `507-508`). Detection is live, not cached at import:
`/doctor` re-runs `shutil.which()` on every call
(`platform_capabilities.py:140-172`), so a tool installed mid-session is
picked up without a restart.

**Doctor recovery guidance actually shown to the user**
(`server.py`, `recovery_guidelines`):
- `unsupported_wayland_injection`: *"Text cannot be delivered to other
  applications: this Wayland session has no typing tool (wtype or ydotool) and
  no clipboard tool (wl-clipboard), so both the typing path and the clipboard
  fallback are unavailable. Install wl-clipboard to restore copy-to-clipboard,
  and wtype (or ydotool) for direct typing; then restart BetterFingers.
  Dictation, transcription and drafts keep working — only delivery into
  another window is affected."*
- `failed_clipboard`: *"The clipboard manager is not responding. On Linux,
  ensure xclip or xsel is installed."*
- `platform_capabilities.injection_hint` (`platform_capabilities.py:117-120`)
  adds a targeted install hint when the method is `"none"`: `wl-clipboard` on
  Wayland, `xclip`/`xsel` on X11.

**Two doc/code mismatches found while verifying this section, reported to the
release supervisor rather than fixed here (this pass is docs-only):**
1. The vocabulary this document previously used — `clipboard_only` /
   `unavailable` — does not match what the injection status API actually
   returns. Those tokens belong to a different capability vocabulary
   (`audio_status.py`'s D-0009 `CAPABILITY_STATUSES`, used for voice-privacy
   and wake status), never applied to injection. The live injection status
   reports concrete method names (`wtype`, `ydotool`, `xdotool`, `paste`,
   `none`) plus booleans, not that enum — corrected above.
2. **Code-level finding — now FIXED (2026-07-29, sup-backend).** The
   `unsupported_wayland_injection` card only fires when
   `is_wayland && !supports_input_injection`
   (`app/src/renderer/features/utilitiesWorkspace.js:489`), and
   `supports_input_injection` is false only when clipboard paste has *also*
   failed (`platform_capabilities.py:84,102`). The old text claimed
   *"BetterFingers has safely fallen back to copying text to the clipboard"*
   — reassuring the user about the one path that had just failed too, so
   nothing reached the target application while the doctor said all was well.
   The recovery text in `server.py` now states that delivery is unavailable
   and names the packages that restore it (`wl-clipboard`, `wtype`/`ydotool`),
   while making clear dictation/transcription/drafts are unaffected.
   Pinned by `tests/test_server_platform_runtime.py::
   test_wayland_recovery_text_does_not_claim_a_fallback_that_also_failed`,
   which drives `/doctor` in the exact triggering state (Wayland, no tools)
   and asserts the text does not claim a fallback succeeded.
   Verified: `.venv/bin/python -m pytest
   tests/test_server_platform_runtime.py -q` -> 16 passed.
- AppImage launch/upgrade evidence on Linux is still pending (Wave 12
  packaging, unrelated to the injection/hotkey behavior above, which is
  implemented and unit-testable today).

### Windows-specific limitations

- Safe capture-session isolation is unproven. BetterFingers must never disable
  the physical microphone.
- Authenticode signing depends on a certificate not yet established for this
  release. Without one, any public artifact must be labeled an unsigned
  experimental alpha.
- CPU-only, NVIDIA, AMD/Intel Vulkan, installer upgrade/uninstall, Discord,
  game clipboard, controller, wake, workflow, privacy, and crash-recovery
  evidence are pending.

## Wake-model licensing

- The code path may support OpenWakeWord-compatible models, but bundled and
  hosted-training artifacts can have different licenses.
- No wake model may ship without recorded source, license, redistribution
  permission, and privacy/export/wipe behavior.
- No CPU, accuracy, false-accept, false-reject, or latency claim is accepted
  until measured on defined hardware.

## Packaging and publication

- The current include graph has not been reduced to a named release allowlist.
  No installer exists to inspect. The source rules broadly select
  `assets/**/*` and `images/**/*`, can duplicate those trees through the
  sidecar and Electron resources, and still compile the preview page into
  `app/out`; design archives, backup images, licenses/notices, the missing
  configured icon, and PyInstaller collection rules require explicit Wave 12
  decisions.
- Windows and Linux artifact counts are both zero. Therefore no evidence can
  yet show that artifacts came from the same tag.
- Checksums, provenance, SBOM, manifest, signing status, install guides,
  compatibility warnings, support routes, and Source Arcanum download copy are
  pending for this release identity.
- No update installer may be silently downloaded or executed. The first public
  release may provide a manual check against a signed or integrity-verifiable
  release manifest.
