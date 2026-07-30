# QA NOTES — the single intake for every issue found

Companion to [`PUBLISH_PLAN.md`](PUBLISH_PLAN.md). **Every** problem anyone
finds — operator, worker, supervisor, director — lands here, in the section for
its screen/feature, using the entry format below. Nothing gets fixed from
memory, chat scrollback, or a commit message alone; if it isn't in this file,
it doesn't exist.

## How to file an entry

Append under the right section, newest last:

```
### QA-<screen>-<number> · <one-line title> · <RED|YEL|GRN> · OPEN
- Found by / date: <who> / <YYYY-MM-DD>
- Where: <exact surface — element id, route, file:line if known>
- Repro: <numbered steps from a known state; say which data dir / target>
- Expected vs actual: <one line each>
- Evidence: <QA report path, screenshot path, test name, or "manual">
- Disposition: (director fills) → task <ID> in PUBLISH_PLAN | deferred §7 | not-a-bug
```

- **Severity:** `RED` blocks publish. `YEL` fix if cheap before publish. `GRN`
  observation, no action promised.
- **Status:** `OPEN` → `TRIAGED` (director set Disposition) → `FIXED (commit)`
  → `VERIFIED (by whom)`. Only an Opus reviewer or the operator moves an entry
  to `VERIFIED`.
- **Numbering:** per-section, sequential: `QA-TALK-001`, `QA-SET-001`, …
- Workers who find something outside their task's file claim: file it here and
  keep going — do **not** fix it in place (PUBLISH_PLAN §1 rule 3).

## Routing map (where fixes come from)

| Section prefix | Screen / surface | Fixes flow into |
|---|---|---|
| `QA-FR` | First-run / onboarding / consent | PUBLISH_PLAN D-series; parity B-1 |
| `QA-TALK` | Talk workspace | B-2/B-3; D-series |
| `QA-LIB` | Library workspace | D-series |
| `QA-STU` | Studio / personas | B-4; D-series |
| `QA-UTIL` | Utilities / models / doctor | D-series |
| `QA-SET` | Settings / privacy / voice | B-5/B-6/B-8; C-4; D-series |
| `QA-OVL` | Overlay windows (ring, review) | A-1; B-7 |
| `QA-SEC` | Security / privacy boundary | C-1..C-4 (escalate RED to director same day) |
| `QA-PKG` | Installer / packaged app | F-1/F-2 |
| `QA-DOC` | Docs that contradict the code | E-series |
| `QA-BL` | Backlog / out-of-scope ideas | nowhere this release — §7 candidates |

---

## First-run & onboarding (QA-FR)

_No entries yet._

## Talk (QA-TALK)

### QA-TALK-001 · Delivery offers three methods where one is intended · YEL · TRIAGED
- Found by / date: publish planning / 2026-07-29
- Where: `#sdDeliverySegmented`, `app/src/renderer/signal-desk.html:3211`
- Expected vs actual: one delivery method (Paste) per D-0036 / segmented
  control offers Type / Paste / Copy
- Evidence: D-0036; `features/talkWorkspace.js:492`
- Disposition: → task **B-3a**

### QA-TALK-002 · Recording toggle only partially anchored in production · YEL · OPEN
- Where: `#toggleRecordingButton`, parity row UI-06-016
- Expected vs actual: whole control resolves on the shipping page / some
  handles resolve only in legacy `index.html`
- Disposition: needs director ruling → task **B-3b**

## Library (QA-LIB)

_No entries yet._

## Studio / Personas (QA-STU)

_No entries yet._

## Utilities / Models (QA-UTIL)

_No entries yet._

## Settings / Privacy / Voice (QA-SET)

_No entries yet._

## Overlays (QA-OVL)

### QA-OVL-001 · Review Deck Read/Stop second press never posts /tts/stop · RED · TRIAGED
- Found by / date: qa board `91d19b8` / 2026-07-29
- Where: `#readButton`, `app/src/renderer/review-overlay.html:620`;
  scenario `review-overlay-rewrite-instruct-and-read` (`overlay-prod.mjs`)
- Repro: full board run `node app/tests/qa/run.mjs`; second press of Read must
  POST `/tts/stop`; captured request array is empty (Expected 1, Received 0)
- Expected vs actual: toggle stops playback via `/tts/stop` / no request issued
- Evidence: `app/tests/qa/out/signal-desk-prod/qa-report.md` (96/97 header)
- Disposition: → task **A-1** in PUBLISH_PLAN

## Security / privacy boundary (QA-SEC)

### QA-SEC-001 · Wake-model import skips upload_safety · RED · TRIAGED
- Found by / date: remediation reconciliation / 2026-07-29
- Where: `routes_wake.py:390` — raw unbounded `handle.write(await file.read())`
- Expected vs actual: same streamed/size-capped/magic-checked path as
  dictation/clone/OCR / raw unlimited write
- Evidence: code citation, verified at HEAD `be2ebaa`
- Disposition: → task **C-1**

### QA-SEC-002 · Dev routes mounted unconditionally on the backend · YEL · TRIAGED
- Where: `server.py` — `/graph/`, `/intent/`, `/project/`, `/mcp/`, `/llm/process`
- Evidence: absent from Electron `ROUTE_ALLOWLIST` but reachable by anything
  that can reach the port
- Disposition: → task **C-2**

### QA-SEC-003 · project_generator accepts arbitrary target_dir · YEL · TRIAGED
- Where: `project_generator.py`, `routes_foundry.py` — no
  resolve-inside-root check, no system-path refusal
- Disposition: → task **C-3**

## Installer / package (QA-PKG)

_No entries yet — opens with Wave 12 (F-1/F-2)._

## Docs vs code (QA-DOC)

### QA-DOC-001 · Docs claim "this machine has no GPU"; it has a 4060 Ti 16 GB · YEL · TRIAGED
- Where: `KNOWN_LIMITATIONS.md` GPU section; `docs/archive/REMEDIATION_WHATS_LEFT.md` Phase 4
- Evidence: `nvidia-smi` + `hardware_report.get_hardware_tier()` → `dgpu-12g+`/`cuda`
- Disposition: → task **E-1**

### QA-DOC-002 · Parity totals differ across three docs vs live validator · YEL · TRIAGED
- Where: `RELEASE_BOARD.md` (396/21/21 and 161/10/267), `KNOWN_LIMITATIONS.md`
  (0/4/434); validator says 398/23/17
- Disposition: → task **E-2**

### QA-DOC-003 · Lifespan migration + Finding #3-residual reported open; both landed · GRN · TRIAGED
- Where: `docs/archive/REMEDIATION_WHATS_LEFT.md`
- Evidence: `server.py:2353/:2366`; `wipeSummary.mjs` dict handling
- Disposition: → task **E-3**

## Backlog / out of scope this release (QA-BL)

_Ideas land here instead of in code. Director reviews after publish._
