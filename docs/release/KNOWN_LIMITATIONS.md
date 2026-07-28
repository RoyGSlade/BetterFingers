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

- **Legacy is the production default.** Signal Desk is reachable only through
  `BF_UI=signal-desk`.
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

### Linux-specific limitations

- Wayland injection may be `clipboard_only` or `unavailable` depending on the
  compositor and installed tooling. This must be detected live.
- X11/Wayland, PulseAudio/PipeWire, `xdotool`, `wtype`, `ydotool`, clipboard
  present/absent, and AppImage launch/upgrade evidence are pending.

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
