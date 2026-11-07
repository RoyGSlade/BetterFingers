# BetterFingers v1.1.0-alpha.4: packaged QA, final check (BF-I1)

**Tested HEAD: `f4b7c15`** (worktree `BetterFingers-wt\i1-packaged-qa`). `arc/assistant` is two commits ahead at `6d8bf08`. `b41003d` and `6d8bf08` change only `docs/release/notes/1.1.0-alpha.4.md`, `tests/test_release_workflow_contract.py` and `tools/smoke_installer.ps1` (`git diff --name-only f4b7c15 arc/assistant`), so this build is valid for the product.

Machine: GIGABYTE AERO X16, AMD Ryzen AI 9 HX 370, RTX 5070 laptop (the packaged app does not use it: the frozen backend ships no cuBLAS/cuDNN, so speech runs on CPU int8), 31 GB RAM, Windows 11 Home 10.0.26200. All builds are **unsigned local builds**: every exe reports Authenticode `NotSigned`.

Evidence files named below live in the QA worktree (`app/artifacts/i1-final/`), not in the repo; the earlier run's are in `docs/release/evidence/alpha4-qa/` of that worktree.

Labels: **V** verified (ran it, read the output), **I** inferred (read code or logs, not run), **U** not run.
Timings: one laptop, warm file cache, other python and node processes running ("under background load"), 4 fresh processes each. These are not the 20-run p95 that `docs/design/FIRST_RUN.md` section 7 asks for.

Safety record: the installer was never run. The owner's installed alpha.3, `%APPDATA%\BetterFingers` and `%APPDATA%\betterfingers-electron` were not read or changed. The reset driver only reads the modification time of those two folders before and after each run (`real_folders_untouched: true` in all four reset runs). Every probe ran from build output with a disposable profile under `%TEMP%\bfqa-a4f-*`.

## 0. Results of this run

| Check | Result | Label | Evidence (`app/artifacts/i1-final/` unless a path is given) |
|---|---|---|---|
| Build | `npm run dist:win`, exit 0, 176.5 s | V | `build.log`, `run_build.ps1` |
| Installer size | 360,480,772 B. +128,661,019 B vs alpha.3 (231,819,753 B), 1.56x. SHA-256 `F5C50D8E9EE33BB97C204B5C3638E8DF2C6BA6B88928B766CCB2332BB41A8854` | V | `app/release/BetterFingers-Setup-1.1.0-alpha.4-x64.exe` |
| app.asar content | 4,296,070 B (4.1 MB). 405 entries: `out/` only (main 19, preload 2, renderer 29), `package.json`, and 18 runtime packages in `node_modules`. No `src/`, `tests/` or backend copy | V | `asar_summary.final.txt` |
| asar CI budget | 50 MB (`.github/workflows/build-installer.yml:297`). The old 684 MB asar would fail it; this build passes | I | `build-installer.yml:287-299` |
| Bundled base.en | 4 files in `_internal/bundled_models/base.en`. Sizes and SHA-256 match `bundled_manifest.json`. No other file there | V | `frozen_backend_inventory.final.txt` |
| Notices | `LICENSES-MODELS.md` and `bundled-base.en-NOTICE.txt` present, byte-identical to the repo copies, with the OpenAI 2022 and SYSTRAN 2023 copyright lines | V | `frozen_backend_inventory.final.txt` |
| Frozen backend, offline, empty HF home | 4/4 fresh processes PASS. The bundled base.en transcribes the 10.7 s clip with 0 canary hits, 0 non-loopback sockets and an empty HF home. Transcript check (WER at most 0.15) passes every run; WER 0.059 in run 1 | V | `backend-run1..4.json`, `backend-runs.log` |
| Timings (under background load) | launch to /health 9.28-9.36 s; /health to STT ready 0.80-0.95 s; warm-up probe 0.35-0.39 s; first transcription of the clip 0.53-0.61 s | V | `backend-run1..4.json` (`timings`) |
| /runtime/status while the model loads (250 ms budget) | 16-68 ms during load, 45-116 ms during forced reloads. 0 samples over 250 ms | V | `backend-run1..4.json` |
| /doctor while loading (250 ms budget) | **Not met.** First call 590-727 ms in 4/4 runs (644-727 ms during load, 590-617 ms after ready). Calls during reloads 167-207 ms. The harness records this as "informational, D5 deferred" | V | `backend-run1..4.json` |
| /doctor CPU fallback is truthful | `using_cpu_fallback: true`, reason "CUDA inference probe failed", code `cuda_runtime_missing`. Agrees with /runtime/status in 4/4 runs (earlier D6, fixed) | V | `backend-run1.json` (`doctor_cpu_fallback`) |
| Model policy A: intact | base.en cannot be deleted (HTTP 200, `ok: false`, "ships with BetterFingers"). Selecting small.en (not installed): warm-up `model_missing`, transcribe 503 `model_missing`, no download. Reselecting base.en: ready, transcribes | V | `model-policy.json` (`A_intact_policy`) |
| Model policy B and C: model.bin flipped / deleted | /health 200; state `verification_failed`; transcribe 503 `verification_failed`; nothing fetched. The old HTTP 200 with empty text is gone (earlier D7, fixed) | V | `model-policy.json` (`B_corrupt_model_byte`, `C_model_bin_missing`) |
| Model policy D and E: bundle or bundled_models dir removed | state `model_missing`; transcribe 503 `model_missing`; nothing fetched | V | `model-policy.json` (`D_whole_bundle_removed`, `E_bundled_models_dir_removed`) |
| Zero network before consent (unpacked app, fresh profile, consent untouched 35 s) | 3/3 runs: 0 non-loopback sockets (1,698-1,985 socket polls per run), 0 URL requests, 0 TCP connects, 0 canary hits | V | `electron-run1.json`, `electron-run2.json`, `electron-run3-noproxy.json`, `*.netlog.json` |
| WPAD note (Chromium system proxy auto-detect) | Runs 1 and 2: 12 `wpad:80` DNS lookups before the consent screen is live. Not an app request (earlier D3, open). Run 3 with `--no-proxy-server`: zero DNS lookups of any name | V | `electron-run1.netlog.json`, `electron-run3-noproxy.netlog.json` |
| After consent, no update opt-in (about 46 s observed) | 0 external URL requests and 0 non-loopback sockets in 3/3 runs. `onboarding.json`: `accepted: true`, `automatic_updates: false`. Settings card: "Automatic update checks are off.", box unticked, "Version 1.1.0-alpha.4" | V | `electron-run*.json` (`update_card`), `electron-run1.04-settings-update-card.png` |
| Speech model loads while consent is showing (earlier D4, open) | Backend RSS 368-385 MB at hold start, 391-394 MB at hold end. Run 3 had `model.bin` open at hold start. Local only, bundled copy | V | `electron-run*.json` (`backend_at_hold_start/end`) |
| Factory reset, bridge, downloaded models kept | Reset HTTP 200; verified straight after; consent asked again after relaunch; dictionary empty; seeded Local Storage keys gone; no canary left in files | V | `reset-bridge/evidence.json` |
| Factory reset, bridge, downloaded models deleted | As above; the `tts/` voice stand-in is deleted with them | V | `reset-models/evidence.json` |
| Legacy migration (Local Storage says done, no `onboarding.json`) | Before the reset the app wrote `accepted: true` and **`automatic_updates: true`** without showing consent. After reset and relaunch, consent is asked again. See open item O3 | V | `reset-legacy/evidence.json` (`afterLegacyMigrationState`, `onboardingJsonAfterMigration`) |
| Persona drafts removed by reset (earlier D2, backend part) | `persona_drafts.json` (4,270 B before) is gone after reset | V | `reset-bridge/snap-3-after-reset-app-running.json` |
| Local Storage cleared | Seeded keys gone after relaunch; Local Storage canary gone after final quit, in 4/4 runs | V | `reset-*/evidence.json` (`lsMarkerFinal`) |
| `profiles/` recreated after reset (known item) | The app writes `profiles/Default.yaml` (3,309 B) again. Post-reset verify fails on `profiles` in all 4 reset runs | V | `reset-*/evidence.json` (`verifyAfterReset`) |
| Factory reset through the real Settings UI | **U (owner by-hand).** The UI steps ran and the reset completed, but the post-reset check fails on `profiles/`, and the UI's own success text says "nothing remains". See 4.2 | U | `reset-ui/`, `reset-ui.out.log` |
| Uninstaller covers persona drafts, voices and both folders | `installer.nsh` lists `tts` (line 209) and `persona_drafts.json` (line 229), and removes both `%APPDATA%` folders (lines 338, 340). Code read only | I | `app/build/installer.nsh` |
| Kokoro voice files: pinned and hash-checked | Pins 325,532,387 B and 28,214,398 B with SHA-256. The download code checks size and hash before use. Download not run | I | `backend/tts/tts_engine.py:30-32, 1065-1088` |
| Installer run, install, upgrade, uninstall | Not run (rule: no installers on this laptop) | U | n/a |
| Real mic, F8/F9 into real windows, read-aloud, game profile, Library Clear dialogs, Report a Bug | Not run (owner steps, section 5) | U | section 5 |

### Re-check after the reset-verify fix (2026-10-08)

Rebuilt the unsigned test build at `3cafd3b` (exit 0, 420 s under background load): installer 360,484,357 B, `app.asar` 4,296,070 B (unchanged), bundled `base.en` present. Re-ran the real-app factory reset (`drive_reset.mjs bridge`, throwaway profile): all 13 checks pass, including **verify straight after the reset** and **verify a moment later** (`reset-bridge/`; the `f4b7c15` run is kept as `reset-bridge-f4b7c15/`). The owner checklist below uses this build. **V**

### Open after this run

- **O1 `profiles/` is recreated after reset.** Every reset path leaves `profiles/Default.yaml`. Only the UI path also fails the check straight after the reset. The cause is not established: the app calls `GET /settings/profiles/Default` after the reset in the bridge run as well (`reset-bridge/app.log`), so that alone does not explain the difference. Not debugged (one retry only). Known item; alpha.4 ships with it per the brief.
- **O2 The UI success text overclaims.** It says "Done ... nothing remains", while "Check what's left" says "Still present: profiles." (`reset-ui/03-settings-after-reset.png`, `reset-ui/03b-settings-check-whats-left.png`). Director call: fix the text or the behaviour. **Fixed after this run (2026-10-08):** the `profiles` check now accepts the untouched `Default.yaml` the running app recreates from defaults, and still fails on any changed setting, extra profile, stray file or `config.yaml` (`tests/test_factory_reset_recreated_profile.py`). This closes O1's check failure too; the file itself is still recreated, by design. Step 7 of the checklist re-checks it by hand on the rebuilt test build.
- **O3 Legacy upgrade turns automatic update checks on without asking.** `app/src/main/onboardingStore.js:247-261` writes `accepted: true` and `automatic_updates: true` for any profile with the old Local Storage flag, and skips consent. The comment at lines 96-99 says this keeps the old always-check behaviour. It is still an update opt-in nobody was asked. Decide whether that is intended before alpha.4 ships. **Director decision (2026-10-08): intended.** Those installs were already checking automatically; the alpha.4 notes (Upgrading from Alpha 3) now say so.
- **O4 `/doctor` first call is 590-727 ms** against the 250 ms budget (D5, open).
- **O5 WPAD lookups before consent** (D3, open). Reword "zero network" or change the code: director's call. **Director decision (2026-10-08): keep the code** (turning off proxy detection would break update checks behind a proxy); the notes list it under Known limitations.
- **O6 The speech model loads while consent is showing** (D4, open). Local only.
- **O7 First read-aloud downloads about 354 MB** with no separate question (known limitation; hash-checked in code).
- **Fixed since the earlier run (V):** D1, the 684 MB asar (commit `5fb0b8f`, asar now 4.3 MB); D2 backend, persona drafts and Kokoro files (`23fbd48`); D6, `/doctor` fallback reason (`a0a68eb`); D7, `/transcribe` answers 503 when the model fails (`a0a68eb`); consent re-granted after reset (`f4b7c15`; consent asked again in all 4 reset runs).

## Earlier run (superseded)

The first pass tested `cd313e4`, before the commits `5fb0b8f`, `a0a68eb`, `23fbd48`, `2173f2a` and `f4b7c15`. Its installer was 708,830,796 B because `win.files` in `app/electron-builder.config.cjs` held only a negation, so `app.asar` packed all of `app/` (D1). Backend probes were 4/4 PASS, and the Electron probe showed zero app traffic before consent, with the same WPAD lookups. Its reset residue (persona drafts, Kokoro files) and its `/doctor` and `/transcribe` defects are the ones fixed above. Its detailed sections were replaced by this run; its evidence stays in `app/artifacts/i1-alpha4-qa/` and `docs/release/evidence/alpha4-qa/`.

## 1. Build

Command (`app/artifacts/i1-final/run_build.ps1`): `npm run dist:win` in `app/`, with `BETTERFINGERS_BUNDLED_MODEL_SOURCE` set to the read-only local base.en snapshot, `BETTERFINGERS_PYTHON` set to the main checkout's `.venv`, and `BETTERFINGERS_SIGNING_MODE` empty. The build log ends with `END exit=0 elapsed_seconds=176.5`, and shows "Verified bundled model staged" for the frozen backend. The installer was built into `app/release` and was never run.

`app/release/BetterFingers-Setup-1.1.0-alpha.3-x64.exe` (706,243,530 B) is the old pre-fix build from the first QA pass, not the real alpha.3 release. It is not used here. The alpha.3 comparison size (231,819,753 B) comes from the brief.

## 2. Frozen backend probe

Script `probe_backend_a4.py`: 4 fresh processes, production auth with a random token, empty `HF_HOME`, no `HF_HUB_OFFLINE`, proxy canary, socket poll. Auth checks, `/runtime/version` (`1.1.0-alpha.4`), `base.en` installed and bundled, and the offline transcript pass in every run.

| Run | launch to /health | /health to STT ready | warm-up probe | first transcription | /runtime/status max while loading | /doctor first call |
|---|---|---|---|---|---|---|
| 1 | 9.316 s | 0.835 s | 0.388 s | 0.608 s | 20.8 ms | 727 ms (during load) |
| 2 | 9.279 s | 0.824 s | 0.372 s | 0.600 s | 68.4 ms | 617 ms (after ready) |
| 3 | 9.356 s | 0.948 s | 0.367 s | 0.533 s | 16.3 ms | 644 ms (during load) |
| 4 | 9.292 s | 0.798 s | 0.349 s | 0.587 s | 62.6 ms | 590 ms (after ready) |

All timings are under background load.

## 3. Network before and after consent

Script `probe_electron_privacy.py` on the unpacked app. Fresh profile, NetLog, 35 ms socket poll, proxy canary. The consent dialog was left untouched for 35 s, then accepted without the update option, then 46 s observed. Results are in section 0.

Runs 1 and 2 (default) show 12 `wpad:80` lookups each. Run 3 (`--no-proxy-server`) shows none. Screenshots: `electron-run1.01..04-*.png`. Run 3's backend had `model.bin` open at hold start (O6).

## 4. Factory reset (throwaway profile, unpacked app)

### 4.1 Driver runs

`drive_reset.mjs <scenario> <label>`. Each run seeds a dictionary term, a persona draft, a 4 KiB stand-in for the Kokoro voice file, recovery copies and Local Storage canaries. It flushes Local Storage to disk, resets, and relaunches.

| Run | Downloaded models | Reset | Verify straight after | Verify later | Consent asked after relaunch | Dictionary empty | Canaries gone |
|---|---|---|---|---|---|---|---|
| bridge (`window.betterFingers.factoryReset`) | kept | HTTP 200 | pass | fail: `profiles` | yes | yes | yes |
| models | deleted | HTTP 200 | pass | fail: `profiles` | yes | yes | yes |
| legacy (migration before the reset) | kept | HTTP 200 | pass | fail: `profiles` | yes | yes | yes |
| ui (Settings UI, see 4.2) | kept | UI "Done" | **fail: `profiles`** | fail: `profiles` | yes | yes | yes |

The legacy run: before the reset, the app had written `accepted: true` and `automatic_updates: true` with no consent screen (O3). The reset then asked for consent again.

### 4.2 UI retry (the one bounded retry, `reset-ui/`)

- Started 2026-10-08 05:34:32 with `node drive_reset.mjs ui ui` under `timeout 480`. It finished in about two minutes. The driver was not edited. The unfinished earlier attempt is kept as `reset-ui-attempt3-killed-superseded/` (`.out.log` and `.err.log` renamed with it).
- Consent accepted through the real dialog (5 steps OK). Settings > Privacy opened with a real mouse click.
- The reset button stayed disabled with "DELETE EVER" and enabled with "DELETE EVERYTHING" (`02b`).
- Confirmation text: "Reset this install to a fresh state? ... (downloaded models are kept)".
- The reset took 4.4 s. Success text: "Done. This install was reset and re-checked: nothing remains." (`03`).
- "Check what's left" then showed "Still present: profiles." (`03b`). The harness verify agreed: `profiles` only.
- After relaunch, consent was asked again (`04`). Dictionary empty, Local Storage canaries gone, and the voice stand-in stayed because models were kept.
- Outcome: the UI steps and the reset ran, but the post-reset check did not pass, and the success text is wrong about `profiles/`. Per the brief's rule, this step is recorded as **U (owner by-hand)**, not as a pass. The two earlier UI completions (`reset-ui-attempt1-dom-click-superseded/`, `reset-ui-attempt3-superseded/`) show the same immediate verify failure.

## 5. Owner by-hand checklist

Run these in order. Steps 1-7 and 9-10 use the unpacked test build and a throwaway profile. Step 8 needs a second Windows account or a VM. Nothing in this section is run by Claude.

### Before you start (5 min)

1. Quit the installed BetterFingers from its tray icon first. It uses the same F8 and F9 keys.
2. In PowerShell, set up the throwaway profile and start the test build:

```powershell
$qa = "$env:USERPROFILE\bf-qa-a4"
New-Item -ItemType Directory -Force "$qa\data","$qa\userdata","$qa\hf" | Out-Null
$env:BETTERFINGERS_DATA_DIR = "$qa\data"   # app data goes here, not in %APPDATA%
$env:HF_HOME = "$qa\hf"                     # empty: the speech model must come from the bundle
& 'C:\Users\Laptop\Documents\Codex\2026-08-16\p\BetterFingers-wt\i1-packaged-qa\app\release\win-unpacked\BetterFingers.exe' "--user-data-dir=$qa\userdata"
```

Keep that window open and reuse `$qa` in every step. To start over, quit the app and delete `$qa`.

### Step 1. Real-mic dictation, offline (10 min)

- **Do:** Turn Wi-Fi off (airplane mode). Start the test build. Press **F8**, say "Hey, quick update on the launch. I moved the review meeting to Thursday at three thirty.", then press **F8** to stop.
- **Must happen:** The review overlay shows the text within about 2 seconds of stopping. No download starts: `Get-ChildItem "$qa\hf" -Recurse` finds nothing. Under Utilities > Models, base.en is installed and cannot be removed. Choose small.en: you get a "download it in Models" message, not a download. Choose base.en again.
- **Record:** Seconds from stop to text; the exact message for small.en.
- [ ] Pass  [ ] Fail  Seconds: ____  Notes: ____

### Step 2. F9 places the text into a disposable Notepad window (15 min)

- **Do:** Open a new blank Notepad window (throwaway: you can close it without saving). Click into Notepad, press F8, dictate, and when the review overlay shows, press **F9**.
  - a. One dictation, one F9.
  - b. One dictation, two quick F9 presses.
  - c. One dictation. Click into the overlay text, change one word (do not save), then press F9.
- **Must happen:** a. The exact text appears in Notepad once. b. It appears once, not twice. c. F9 refuses and Notepad is unchanged.
- **Record:** Pass/Fail for a, b and c; what Notepad showed.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 3. Escape keeps the draft, then F9 reads a selection aloud (10 min)

- **Do:** Dictate a sentence. Press **Escape**: the overlay hides but the draft is kept. Click into Notepad, select a sentence, and press **F9**.
- **Must happen:** The selected text is read aloud. The draft is not placed into Notepad, and it is still in Scribe > Library.
- **Note:** The first read-aloud starts the voice-file download in step 9 (about 354 MB). Keep the network on and expect a wait.
- **Record:** Pass/Fail; how long the first read took.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 4. Update opt-in and a manual "Check for updates" (10 min)

- **Do:** Network on. Open Settings, search "update", and find the BetterFingers Update card.
  - a. Before touching anything: the card says "Automatic update checks are off.", and "Check for updates automatically" is unticked.
  - b. Click **Check for updates**.
  - c. Tick "Check for updates automatically". Restart the app, wait about 30 seconds, then untick it and restart once more.
- **Must happen:** a. As described, and nothing downloads. b. One short check to GitHub, then "up to date" or a message about a newer version. Nothing downloads. c. With the box ticked: one automatic check about 15 seconds after launch. With it unticked: none. The choice survives a restart.
- **Optional proof:** Watch the Network tab in Resource Monitor while you do this.
- **Record:** Pass/Fail; the card text at each point.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 5. A game profile forces copy-only (5 min)

- **Do:** Settings: search "Application Profiles". Under "Temporary override", pick the generic game profile (`game_generic`). Click into a blank Notepad window, dictate, and press **F9**. Press Ctrl+V in Notepad to see what the clipboard holds. Then clear the override, dictate again, and press F9.
- **Must happen:** With the override on, the text goes to the clipboard and is not typed or pasted into Notepad (Ctrl+V gives it). After Clear, F9 places the text as in step 2.
- **Record:** Pass/Fail; what Notepad showed with the override on.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 6. Library "Clear" asks first, then works (5 min)

- **Do:** Dictate two items so Scribe > Library has history and a saved recording. Click **Clear drafts & history**, read the dialog, press **Cancel**, and check nothing changed. Click it again and confirm. Then click **Clear saved recordings**, then **Clear all conversation data**.
- **Must happen:** Each button opens its own confirmation that lists what it removes and what it keeps. Cancel deletes nothing. Confirming one scope does not clear the others. Each list is empty afterwards, as it should be.
- **Record:** Pass/Fail per button; wording that surprised you.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 7. Factory reset in Settings, then relaunch (10 min, throwaway profile only)

- **Do:** Settings > Privacy > Factory reset. Leave "Also delete downloaded models" unticked. Type "DELETE EVER" first: the reset button must stay greyed out. Then type the rest, "DELETE EVERYTHING". Click **Reset this install...**, read the confirmation, and confirm. Then click **Check what's left**. Quit, and start the test build again with the command above.
- **Must happen:** The button stays disabled until the exact phrase is typed, and the reset finishes in a few seconds. **Known issue:** after the reset, the app recreates `profiles/`. So "Check what's left" says "Still present: profiles.", and the green success text ("nothing remains") is wrong. Record both. After relaunch, the Welcome dialog asks for consent again. The dictionary and Library history are empty.
- **Record:** Pass/Fail; the exact "Check what's left" text; whether consent came back.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 8. Uninstall with "remove my data" (20 min, second Windows account or VM only)

- **Warning:** This installer replaces the alpha.3 install (same app). Do not run it on your daily account.
- **Do:** On the second account or VM, install `app/release/BetterFingers-Setup-1.1.0-alpha.4-x64.exe`, launch once, and close. In `%APPDATA%\BetterFingers`, create these recovery copies (empty files are fine): `contacts.json.bak-v1`, `contacts.json.corrupt`, `personas.yaml.bak-v1`, `draft_history.json.migrated`. Then go to Settings > Apps > BetterFingers > Uninstall. Tick all five "remove" boxes.
- **Must happen:** Afterwards, both `%APPDATA%\BetterFingers` and `%APPDATA%\betterfingers-electron` are gone, including the `.bak-v*`, `.corrupt` and `.migrated` copies, and the install folder is gone. Check with `Test-Path`.
- **Record:** Pass/Fail. If anything stayed, paste the output of `Get-ChildItem "$env:APPDATA\BetterFingers","$env:APPDATA\betterfingers-electron" -Force -Recurse`.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 9. First read-aloud downloads the voice files (known limitation, observe only) (10 min, network on)

- **Do:** Network on. Select text in Notepad and press **F9** with no draft pending (or use read-aloud in Studio). Do not cancel the download.
- **Must happen:** The app starts downloading the voice files from GitHub with no separate question. When it finishes, `Get-ChildItem "$qa\data\tts\kokoro_onnx" | Select-Object Name,Length` shows `kokoro-v1.0.onnx` at 325,532,387 B and `voices-v1.0.bin` at 28,214,398 B. The app checks size and SHA-256 before using them (code check, not run).
- **Record:** Minutes it took; what the UI said while it ran; the final sizes.
- [ ] Pass  [ ] Fail  Notes: ____

### Step 10. Optional: upgrade in place from a COPY of your alpha.3 data (10 min)

- **Do:** Quit alpha.3 from its tray icon. Copy both folders (read only):

  ```powershell
  New-Item -ItemType Directory -Force "$qa\upgrade" | Out-Null
  Copy-Item "$env:APPDATA\BetterFingers" "$qa\upgrade\BetterFingers" -Recurse
  Copy-Item "$env:APPDATA\betterfingers-electron" "$qa\upgrade\betterfingers-electron" -Recurse
  ```

  The consent flag lives in the Electron folder, so you need both. Start the test build with `$env:BETTERFINGERS_DATA_DIR = "$qa\upgrade\BetterFingers"` and `--user-data-dir="$qa\upgrade\betterfingers-electron"`. Never point the test at your real folders, and do not run the installer over alpha.3.
- **Must happen:** Personas, settings and Library history are all still there. `.bak-v1`-style copies appear next to migrated files (expected). If your alpha.3 profile had accepted consent, no consent screen appears (if one does, note it). Check whether "Check for updates automatically" is ticked. It is ticked if alpha.3 was checking on its own, and that can happen without a new question (O3).
- **Record:** Pass/Fail; anything missing; whether the box was ticked.
- [ ] Pass  [ ] Fail  Notes: ____

## 6. Evidence index

All in `app/artifacts/i1-final/` (git-ignored) unless a path is given.

| What | Files |
|---|---|
| Build | `build.log`, `run_build.ps1`, `asar_summary.final.txt`, `frozen_backend_inventory.final.txt`; installer `app/release/BetterFingers-Setup-1.1.0-alpha.4-x64.exe` (and `.blockmap`) |
| Backend probe | `backend-run1..4.json`, `backend-run1..4.backend.log`, `backend-runs.log`, `probe_backend_a4.py` |
| Model policy | `model-policy.json`, `model-policy.log`, `probe_model_policy.py` |
| Electron privacy | `electron-run1.json`, `electron-run2.json`, `electron-run3-noproxy.json`, `*.netlog.json`, `*.app.log`, `*.png`, `electron-runs.log`, `probe_electron_privacy.py` |
| Factory reset | `reset-bridge/`, `reset-models/`, `reset-legacy/`, `reset-ui/` (each with `evidence.json`, `snap-*.json`, `app.log`, `*.png`), `reset-*.out.log`, `reset-runs.log`, `drive_reset.mjs`, `run_reset_scenarios.ps1` |
| Superseded attempts | `reset-bridge-attempt1-superseded/`, `reset-ui-attempt1-dom-click-superseded/`, `reset-ui-attempt2-bridge-accept-modal-blocked-superseded/`, `reset-ui-attempt3-superseded/`, `reset-ui-attempt3-killed-superseded/` (unfinished, renamed at the start of this retry) and their `.out.log` files |
| Earlier run | `app/artifacts/i1-alpha4-qa/`, `docs/release/evidence/alpha4-qa/` |

All 16 temp profiles named in this run's logs and evidence were removed at the end. One folder with the same prefix, `bfqa-a4f-reset-cbR9KA`, is named in no log, so it was left in place. The list is in the handoff section of `CODEX_BRIEF.md`.
