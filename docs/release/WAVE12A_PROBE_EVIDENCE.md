# Wave 12A, Objective B — scratch probes: what they tested and what they found

These three scripts live at `probe_wave12a/` at the repo root
(`appdata_check.py`, `probe.py`, `run_backend.sh`), committed in `9399e54`
alongside Wave 12A's UI and data-root work. This document is their
evidentiary content, folded in so nothing the probes established is lost
regardless of when the directory itself is removed.

**Deletion status: BLOCKED, not done.** The 2026-07-29 repo-hygiene pass
intended to `rm -rf probe_wave12a` (not `git rm`, since the goal was an
untracked-style cleanup after folding evidence here) but every removal
attempt — plain `rm -rf`, `rm` on individual files, `rm -rf` with the sandbox
override, and a `mv` out of the repo, tried independently by both
`worker-releasedocs` and `sup-backend` — was hard-blocked by the agent
sandbox's file-removal policy for this session. The three files are still on
disk, unmodified, still tracked by git from `9399e54`. Deleting them now
requires an operator running `git rm -r probe_wave12a` (or a plain `rm -rf`)
outside the agent sandbox; this is tracked as an open release-hygiene item,
not a completed cleanup.

Both scripts hard-code `REPO = "/home/donaven/Desktop/BetterFingers"` — a
different local username/path than this checkout
(`/home/roygslade/Desktop/BetterFingers`). They were written by
`sup-dataroot` for the **director** to run (`probe.py`'s own docstring: "Run
by the director (sup-dataroot cannot launch a server or read outside the
repo)"), so the path is whoever's machine ran them, not a bug to fix here.

## `appdata_check.py` — did HEAD's `resolve_base()` honor `APPDATA`?

**What it tested.** Executes `app_paths.py` as it stood at `HEAD` (via `git
show HEAD:app_paths.py`, `exec`'d into a throwaway module) with `APPDATA` set
to an isolated temp directory and a fake, populated `$HOME/BetterFingers`
underneath a mocked `Path.home()`. It then checks whether `resolve_base()`
returned a path under the `APPDATA` directory or under the fake home.

**What it found, and where that finding already lives.** This is the exact
methodology behind the correction recorded in
[`WAVE12A_UI_CONTROLS.md`](WAVE12A_UI_CONTROLS.md)'s "Director correction to
the P0 narrative (2026-07-29)" section: commit `2507930`'s message claimed the
pre-fix `APPDATA` branch "ignored its value and returned the real
`~/BetterFingers`", and that claim is wrong — `_legacy_home_base()` reads
`APPDATA` itself and returns `$APPDATA/BetterFingers` when set, proven by
executing the pre-fix source directly. **No new content to fold in here** —
the probe's finding is already fully captured in prose in
`WAVE12A_UI_CONTROLS.md`, including the caveat that this disproves the
destroyer theory but does **not** establish what actually deleted the owner's
`models/`, personas, voices and presets.

## `probe.py` + `run_backend.sh` — real-backend probe for findings 5, 8, 9

**What they were designed to test.** `run_backend.sh` boots `server.py` on
port 8011 against a clean `BETTERFINGERS_DATA_DIR` under `probe_wave12a/`, the
same shape a new user's first boot would have. `probe.py` (meant to run
against that live backend, or to launch its own copy the same way) covers
three product-owner hand-test findings from Wave 12A's hunt:

- **Finding 5** ("stuck warming up and won't work") — part A greps running
  `llama-server` processes for `--model` arguments and checks the target
  model file still exists on disk, and whether any of the process's open file
  descriptors point at a `(deleted)` inode (the fingerprint of a server
  holding a model file open after it was removed from under it). Part B2
  times `POST /runtime/warmup` and re-times `GET /personas` immediately after,
  to see whether the warmup call blocks the event loop long enough to starve
  the dropdown-feeding endpoints past the renderer's 2500ms fetch budget
  (`api/backend.js`'s `fetchJson` default timeout).
- **Finding 8** ("can't select it as my main voice after saving") — part C
  saves a blended voice preset via `POST /voice-presets`, re-lists it, and
  calls `POST /voice-presets/<name>/make-default` to see whether the backend
  route round-trips correctly.
- **Finding 9 context / findings 6-7** ("settings fetch failing throughout") —
  part B times `GET /personas`, `GET /tts/voices`, `GET /voice-presets` and
  `GET /profiles` against the 2500ms renderer budget on a cold, clean data
  root.

**Verification status: UNVERIFIED — these were not run, or at least no
output survives.** `probe_wave12a/` contained only the three source files; no
`dataroot/` subdirectory, log file, or captured output was present in this
checkout, and no release doc (`DECISIONS.md`, `WAVE12A_UI_CONTROLS.md`, or any
other `docs/release/*.md`) references a result for findings 5 or 9, or quotes
any output from `probe.py`. Do not read "the probe exists" as "the probe ran
and passed."

**Finding 8 is independently corroborated, by a different route.** Wave 11B/
11C's evidence work reached the same conclusion by reading source rather than
running a server: [`WAVE11_INTEGRATION_DIFFS.md`](WAVE11_INTEGRATION_DIFFS.md)
and [`WAVE11_BLOCKERS.md`](WAVE11_BLOCKERS.md) both record rows `UI-07-126`
and `UI-15-012` — `setDefaultVoicePreset()` / `clearDefaultVoicePreset()`
exist in `app/src/renderer/api/backend.js` and the backend routes exist, but
"the only occurrences in the renderer are the wrapper definitions and the
export list" — no UI control calls them. That confirms `probe.py`'s finding-8
hypothesis (the backend route works; there is no "make this my main voice"
button) without needing the probe's own run to have happened. Both rows are
still `blocked` in the parity ledger as of Wave 11C.

**Findings 5 and 9 remain open questions.** Nothing else in `docs/release/`
corroborates or refutes the llama-server-holding-a-deleted-model-file
hypothesis or the warmup-blocks-the-event-loop hypothesis. If either matters
to the release, it needs to be re-run for real and the result recorded —
this document is not that evidence, only the record that the question was
asked and not yet answered.
