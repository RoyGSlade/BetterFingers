# First run: two screens, local dictation, explicit consent

BF-D2 design proposal, 2026-10-04. Spec only; no implementation or runtime qualification.

**Recommendation:** bundle a pinned `base.en` speech model, ask for consent plus microphone confirmation on Screen A, then one mode on Screen B. First-run setup requires no external network. Keep optional model upgrades, AI cleanup, wake listening, and the tour out of this path.

## 1. Evidence and definition of done

Code citations below refer to this isolated worktree at `f6aaa6f937a3a2c808ee35eadf324a998770eec3`. The main checkout is being reorganized; its root-module paths and line numbers will move. Audit citations refer to read-only, gitignored inputs in `C:\Users\Laptop\Documents\Codex\2026-08-16\p\BetterFingers\docs\arc\`. Re-resolve code locations at implementation time.

Labels: **[S]** verified source inspection; **[M]** historical measured evidence reported by the audit, not rerun here; **[I]** inference or arithmetic; **[P]** proposed behavior or target, unmeasured.

| Current fact | Evidence | Consequence |
|---|---|---|
| Current best path is 14 screens/cards, or 8 with the tour skipped; 11 inputs to first placed text, 17 with the tour walked. | `docs/arc/SETUP_AUDIT.md:64-68` [S: audit's source-count estimate, not a new user study] | Count setup separately from recording, review, and placement. |
| Fresh V2/V3 probes contacted Hugging Face before consent; model fetch began at backend spawn +2.459/+3.825 s. | `docs/arc/SETUP_AUDIT.md:14-17`, `:101-105` [M] | Renderer gating alone cannot fix this. |
| Residency defaults STT on, LLM/TTS off; startup preloads and then can attempt STT again. | `utils.py:921-923`, `server.py:654`, `:2783-2802`, `:685-700` [S] | Residency must never imply acquisition permission. |
| Uncached load can fetch weights; cached-load failures can retry with `local_files_only=False`. | `transcriber.py:563-610`, `:657-676`, `:752-760` [S] | Both missing and corrupt cache paths need a fail-closed acquisition guard. |
| A scheduled update check runs 15 seconds after renderer load and reaches the updater without an onboarding check here. | `app/src/main/main.js:193-205`, `app/src/main/updateController.js:220-225` [S] | Waiting at consent must not produce updater traffic. |
| Setup treats any installed Whisper model as ready; it need not be the selected model or inference-tested. | `app/src/renderer/features/firstRun.js:81-95`, `:110-137` [S] | Separate installed, loaded, inference-ready, and microphone-confirmed. |
| Runtime status takes the model lock; an async status route invokes the snapshot synchronously. | `transcriber.py:497-511`, `:736-737`, `server.py:3287-3289` [S] | Event-loop blocking is a source-supported risk [I]; no timing proof in this task. |

Done means a disposable installed profile completes two setup screens; captures no audio before explicit local consent; makes zero external DNS/HTTP/socket attempts before consent; reaches an inference-verified model offline; and produces a reviewed draft through the actual microphone path. Shipping a five-second claim additionally requires the harness and usability measurements in section 7. A document is not that evidence.

## 2. Screen A: consent and the real microphone

Exact proposed copy for the recommended bundled build:

> **Your voice stays on this computer**
>
> BetterFingers transcribes your speech on this device. Your recordings and drafts are not uploaded. Dictation may save recordings and drafts locally; you can delete them in Privacy.
>
> A speech model is included. Setup does not need the internet. Downloads, update checks, and support reports require a separate action from you.
>
> The microphone check below listens locally for up to 8 seconds and shows its level. It does not save, transcribe, or upload this test audio. Dictation starts only when you start a recording.
>
> Capture only speech you are authorized to record.

Unchecked checkbox:

> **I accept how BetterFingers handles my data and allow this local microphone check.**

Device row: **Microphone: {resolved device name}**. Prompt after consent: **Say a word.** Before consent: **Microphone off** with meter at 0 and no claim of listening. Primary action: **That's me**. Secondary: **Continue without testing**. Persistent escape: **Decline & quit**. Device recovery: **Choose another microphone**. Expanded policy is available locally, with no external link opened automatically.

Interaction contract [P]:

1. Open the dialog immediately when the durable consent state is missing, corrupt, unreadable, or outdated. Keep the existing focus trap, keyboard navigation, and non-dismissible consent gate. Escape cannot bypass it. No hotkey, recording route, tray action, alternate renderer, or imported profile can bypass the gate.
2. Resolve the system default input locally; enumerate input-capable devices only. Checkbox starts no capture until the main process has durably acknowledged the current consent version and explicit `local_mic_diagnostic` grant. Existing atomic write semantics must remain (`app/src/main/onboardingStore.js:100-119`). If writing fails, show **Couldn't save consent. Your microphone is still off. Try again.** Do not advance or capture.
3. Consent acceptance and setup completion become separate durable facts. Checking the box authorizes the specified local operation, not network traffic or completed onboarding. Bump the consent version from the current `1` for this new diagnostic grant (`app/src/main/onboardingStore.js:25-26`). Prior accepted records do not retroactively grant a first-run diagnostic. Store version, purpose, grant state and timestamp, never diagnostic audio or speech.
4. Start a short-lived `meter` subscription to the same `AudioInputBroker` used by dictation, using the same device resolution, sample rate/channel conversion, and capture-privacy policy. Broker supports the subscriber label but the production meter route is new work (`backend/audio/audio_input_broker.py:135-169`; recorder path `backend/audio/recorder.py:186-202`, `:233-248`). Do not call browser `getUserMedia`: today's Utilities meter uses that separate path (`app/src/renderer/features/utilitiesWorkspace.js:1706-1711`).
5. Backend returns levels and actual resolved device identity, not raw audio. The meter is a signal check, never speaker identification. Enable **That's me** once a real non-silent signal arrives; the user's click confirms the device. Do not treat a threshold crossing as consent, speech recognition, or ownership proof. Keyboard users receive an equivalent level/status announcement without a flood of live-region updates.
6. At 4 seconds without signal, show **No sound yet. Check Windows microphone access or choose another microphone.** Keep **Continue without testing** available after consent. At 8 seconds, stop capture and offer **Test again**. Permission denied, busy, unplugged, or unsupported device: show the actual failure class, close the subscription, leave model/setup progress visible, and offer selection or skip. Never draw an animated fake meter.
7. If opening falls back to another device, disclose its actual name and require confirmation of that device; do not preserve a false confirmed identity. Save the selected device fingerprint plus current index through the existing resolver contract. Follow-system-default remains an explicit option; at recording time disclose a changed actual device rather than silently reusing the old confirmation.
8. Close the meter on confirmation, skip, uncheck, decline, leaving the screen, renderer disconnect, test timeout, or process shutdown. A backend lease expires without renewals; a crashed renderer must not strand capture. Unchecking immediately revokes the diagnostic capability and stops the lease. No recorder frames, recovery WAV, draft history, transcription job, ducking side effect, clipboard read, injection, TTS, or wake subscriber may be created by the diagnostic.

Skipping testing does not waive consent and does not imply a working microphone. Screen B can complete; Talk shows **Microphone not checked** and a local **Test microphone** action. A blocked device cannot be labeled **Ready to dictate**.

## 3. Screen B: one mode choice

Heading: **What are you using BetterFingers for?** Subcopy: **You can change this later.** Match BF-D1's shared contract:

| Label | `use_mode` | First-run description |
|---|---|---|
| Work | `work` | Review your words before placing them. |
| Gamer | `gamer` | Push to talk; reviewed text goes to the clipboard. |
| Ideas | `ideas` | Capture longer thoughts, then review them. |
| Messages | `messages` | Draft a message and review it before placing it. |
| Hands-free | `hands_free` | Start a recording, then stop on silence. |

Default `work` on new profiles. One click on an available card applies its preset and completes setup after a successful durable save; Enter activates the currently focused available card. Keep a visible **Continue with Work** action for users who do not choose another card. Failure to save remains on Screen B with retry; no success toast followed by lost state. Switching modes later is outside setup.

Gamer is unavailable until BF-D1's validated push-to-talk/stop binding and delivery guards are qualified; show **Game setup needs a tested push-to-talk binding**. No extra wizard is forced into first run and no fallback secretly converts it into toggle capture. F1's renderer-only correction does not prove global game safety. Hands-free means manual-start silence-stop here; wake stays off and no ambient listening is armed. Optional read-back remains off until its local engine is qualified or separately acquired. A mode tap does not enable or download an LLM, TTS model, wake backbone, controller runtime, or larger STT model.

Land on Talk after Screen B, even if the local model is still preparing; display preparation inline and disable recording until section 6's readiness predicate is satisfied. For Work show **Record: F8. Review: Accept. Place: F9.** Confirm names against the actual applied bindings before display. Gamer and Hands-free use their own applied bindings. Do not promise an emergency-stop key when none is configured. The current F9 path needs prior Accept; the tutorial claim of accept-and-send is stale (`Tutorial_Script.txt:46`; `docs/arc/SETUP_AUDIT.md:25-30`). A future F9 fix is a separate dependency, not silently included in this budget.

### Counts and timing claim [P]

| Metric | Current audit | Proposed normal tested-mic path |
|---|---|---|
| Setup screens/cards | 4 onboarding + 7 auto-tour + model banner | 2, then ordinary Talk |
| Setup decisions | Consent; optional tour/download/recovery choices | Consent, mic confirmation, mode: 3 total, 2 after consent |
| Setup inputs | 5 onboarding + 1 tour skip + 1 download = 7 | Checkbox, That's me, mode = 3 |
| Inputs to first placed text | 11 with skipped tour | 7: 3 setup + Start, Stop, Accept, Place |
| Screens/cards to first placed text, splash/review included | 14 with tour, 8 skipped | 5: splash, A, B, Talk, review |

Installer clicks are excluded on both sides. Speaking is an additional human action. Skipped mic uses the same three inputs but leaves microphone status unverified. Device recovery adds inputs and time. A unavailable Gamer card is not a successful mode selection.

**Five seconds is a mechanical setup target, not a proven comprehension time or launch-to-dictation promise.** Proposed allocation after Screen A is interactive: accept ~1 s, say a word and confirm ~3 s, choose mode ~1 s [P]. Consent reading has no timer or pressure. Measure full participant time including reading separately; do not strip it from a customer-facing five-second claim. If users cannot understand the copy in that time, change the claim, not the protection.

## 4. Zero network before consent, and no first-run acquisition surprise

Here network means external/non-loopback communication, including DNS, metadata/HEAD requests, updater checks, redirects, analytics, web fonts, crash upload, and downloader retries. Authenticated localhost IPC remains allowed so the desktop can communicate with its backend. This exception must appear in technical tests; it cannot hide external traffic through a localhost proxy.

Use a main-owned durable capability gate, enforced independently by backend acquisition paths and updater/relay entry points. Renderer flags and `HF_HUB_OFFLINE` alone are not authority. Pass consent state to the sidecar through a validated local bridge; missing/unreadable state fails closed. An arbitrary backend call cannot mint consent. Each external operation requires current consent **and** a scoped explicit user action identifying destination, artifact/size when relevant, and purpose. Local mic consent grants none of those operations.

Defaults and boot [P]:

- Fresh profile `model_keep_stt_loaded=false`, `model_keep_llm_loaded=false`, `model_keep_tts_loaded=false`. Keep `llm_enabled=false`, wake off. While unconsented, effective residency is false for all components even if an imported/old profile says true. Construct observation-only status objects with no loader side effects.
- Before consent: no model load, acquisition, microphone open, wake arming, or scheduled update check. Local device enumeration and bundled manifest inspection are permitted. On acceptance, start one worker to verify the bundled model, construct it locally and run inference; the mic meter runs independently. No second warmup attempt hidden behind residency flags.
- For normal consenting profiles, STT residency may become true after verified admission to fit BF-D3's measured hardware policy; record the choice once. Low-memory systems retain false/on-demand residency. Capability permission remains distinct from a residency preference.
- `ensure_loaded` must default to `allow_download=false`, force local-only resolution, and refuse uncached/corrupt files. Remove the local-only failure retry that turns network access on. The only download path accepts a one-operation acquisition grant after user disclosure. Recording, warmup, recommender, Doctor, status polling and cache repair cannot create that grant.
- Do not run the 15-second updater timer before consent. For this first-run contract, disable automatic update checks on fresh profiles; offer **Check for updates** later with destination/purpose disclosure. Restore automatic checks only through a separate optional opt-in after setup. Existing installations need migration rather than silently rewriting an explicit prior preference.
- No support relay, report submission, cloud font, remote image, help page, login, recommendation catalog refresh, or HF cache metadata fetch occurs because setup opened. Bundle required UI assets/catalog metadata locally. Consent decline shuts down local processes without fetching anything.

After consent, the recommended first-run path still makes zero external requests. Optional upgrades are explicit later actions; recommendations may be shown from local catalogs. This intentionally rejects the audit's silent tier upgrade proposal (`docs/arc/SETUP_AUDIT.md:255-263`) and resolves the consent-copy conflict by changing behavior (`docs/arc/SETTINGS_INDEX.md:410`).

## 5. Model acquisition: choose one

Sizes are the audit's 2026-10-04 Hub observations and prior V3 artifact measurements, not newly queried provider values (`docs/arc/SETUP_AUDIT.md:106-109`, `:248-257`). Decimal MB throughout. Bundled installer arithmetic assumes no extra compression; an actual signed build must establish its size.

| Option | Numbers | First-dictation implications |
|---|---|---|
| **Bundle `base.en` — recommended** | `model.bin` 145,216,508 B + ~2.55 MB support files = ~147.8 MB payload [M/I]. V3 installer 231,819,753 B [M] → ~379.6 MB estimated [I], ~64% growth. | No acquisition network/wait at first run. Still pays integrity verification, load and inference; those are unmeasured here. Preserves documented floor `base.en` (`DESIGN.md:851-857`). |
| Download after explicit consent and download action | Installer ~231.8 MB baseline [M]; transfer ~147.8 MB [I]. At 10 MB/s ≥14.8 s; at 2 MB/s ≥73.9 s, before connection/protocol/load overhead [I]. | Cannot promise fast first dictation. Needs host/size disclosure, real byte progress, cancel/retry, offline/proxy/rate-limit/disk-full handling. Consent checkbox alone is not download intent. |
| `tiny.en` then upgrade | `tiny.en` weights 75,537,502 B + ~2.55 MB = ~78.1 MB [M/I]; bundle estimate ~309.9 MB [I]. A later full `base.en` download adds ~147.8 MB, or `small.en` ~486.1 MB [I]. | Saves ~69.7 MB installer but adds model quality qualification and upgrade state. Silent acquisition is rejected. No measured accuracy/speed win here; not the smallest reliable first-run path. |

Bundle pinned revision and per-file SHA-256 manifest, size, source, license and provenance; include tokenizer/config/vocabulary. Release pipeline acquires and verifies this payload ahead of signing, with model license entries. Runtime verifies the actual bundled bytes and seeds an app-owned cache atomically, or loads from an explicit verified local directory through a dedicated resolver. Do not pass an arbitrary slash-containing path to the model-ID parser and hope it works. Existing HF cache counts only after matching the pinned revision and manifest; a cache miss/corruption never triggers network repair. Avoid double disk copies where safe, but measure installed footprint and extraction cost before promising savings. Provenance requirements: `DESIGN.md:652-661`; existing presence-only checks: `transcriber.py:704-734`.

If bundling is rejected, the honest fallback is explicit post-consent download with an unbounded-by-us network wait, not the same five-second-ready claim. No new speech engine in D2. BF-D3's initial default is this included `base.en` on CPU int8; optional device changes require local inference/performance qualification. Higher quality models remain later opt-in acquisitions. Do not silently substitute `tiny.en` on a slow machine.

## 6. Readiness and recovery

Proposed states: `awaiting_consent → verifying_files → loading → probing → inference_ready`, with `model_missing`, `verification_failed`, `device_unavailable`, `admission_refused`, or `inference_failed` branches. File presence means installed only; construction means loaded only. **Speech ready** requires verified artifact identity plus `inference_ready=true` and `probe_passed=true` for the current model revision, device/compute configuration and current process generation. Clear proof after reload/unload/config change. Probe must actually consume a decode iteration; merely obtaining a lazy generator is not inference. Existing `runtime_probe` performs a real silence decode (`transcriber.py:941-963`), which proves execution, not microphone operation or recognition quality.

**Ready to dictate** additionally requires current local consent, a currently available capture device, valid active bindings, and applicable mode qualification. Mic-skipped profiles show **Speech ready · Microphone not checked**. Runtime probe failures retain detailed safe failure codes and an explicit retry; BF-D3 may attempt its bounded CPU fallback once, without acquisition or repeated hung GPU probes.

`/health`, `/runtime/status`, `/doctor`, model list/progress and voice-status heartbeat must remain responsive during long download/load/probe operations. Read an immutable short-lock snapshot with generation/state/job ID; do not wait on `_model_lock`, perform inference, or inspect the provider remotely on the request/event-loop thread. Job-start endpoints return promptly with a job ID; background workers publish progress. Threadpool offloading alone is insufficient if status still waits for a loader lock. If a snapshot cannot be refreshed, return the last observation with `stale=true` and truthful `loading`, never a success flag inferred from stale files.

Replace the current 4-card onboarding with A/B; keep durable gating and expand its tests. Stop the seven-card tour auto-run (`app/src/renderer/bootstrap/signalDeskApp.js:954-961`, `:997-1004`); retain optional **Take a tour** replay (`:1044`) after setup. Replace the three-row **Finish local model setup** panel with a single non-modal speech readiness/error row in Talk. No LLM/runtime download checklist until that optional feature is explicitly enabled. Remove "installed means ready" copy (`app/src/renderer/signal-desk.html:230-232`). Reconcile the optional tour/script with actual F8/F9 and delivery behavior before offering replay; it cannot teach stale actions or claim voice readiness merely because narration finished (`Tutorial_Script.txt:46`, `:82`).

## 7. Measurement harness design, not executed

Extend the disposable-profile pattern in main's ignored `app/release/section10-20260907/probe_backend.py:16-30`, `:42-60`, `:73-79`: unique data root, isolated APPDATA/LOCALAPPDATA/USERPROFILE, production auth, ephemeral loopback port, monotonic timestamps, logs, and complete child cleanup. Also isolate Electron `userData`, `HOME`, `HF_HOME`, `HF_HUB_CACHE`, XDG cache and every app-owned model directory. Use a packaged installed build with known SHA-256/signature/manifest; no developer profile or globally warmed HF cache. The old probe's `no_llm_download` check only searches for GGUF/llama-server (`:66-69`); it does not prove no Whisper fetch or network attempt.

Two complementary runs are required:

1. **Privacy run, empty profile/cache:** observe externally blocked and attempted traffic across Electron/backend/child processes, including DNS/UDP and HTTP metadata. Renderer request interception is insufficient. Hold Screen A untouched for ≥30 s (past the existing 15 s updater timer), exercise status, hotkeys and launch/tray actions, then decline. Capture process/socket audit plus cache/file diff; assert zero external attempts and zero audio-open calls. Repeat with corrupt consent, imported residency=true, missing/corrupt bundled model, reconnect, and restart. OS/vendor background traffic is distinguished by process ownership, not hidden in a whole-machine total.
2. **Offline first-dictation run, bundled model:** only loopback permitted; scripted UI records consent, speaks a standardized short phrase over a physical test input, confirms microphone, chooses Work, records a fixed 10 s utterance, reviews and explicitly places into a disposable local text editor. Use the real PortAudio path for the acceptance run; a deterministic virtual microphone may make repeatable automation possible but must be labeled simulated-device evidence. A bundled synthetic fixture can measure inference separately; it cannot prove hardware capture. No user audio, transcripts, auth tokens or raw profile content in published logs; export stage times, booleans, safe codes and fixture ID/hash.

Required event stamps: process launch `t0`; Screen A interactive; consent persisted; actual mic stream-open; first level; confirmation; mode persisted; bundle verified; model constructed; inference verified; record key; capture acknowledged; Stop; streaming drain finished; draft committed; review visible; Accept; placement verified in the target. Cross-process monotonic clocks are not blindly subtracted: use correlated job IDs and a harness reference clock or establish clock mapping. Preserve traces even if a stage times out.

Report each duration separately: launch-to-A, full human setup time (including reading), mechanical setup time, consent-to-inference-ready, first record-to-draft including the fixed 10 s utterance, Stop-to-visible-draft, and launch-to-first placed text. Review/placement pauses are human time, not STT latency. Existing `/metrics` misses parts of the end-to-end path (`docs/arc/SETUP_AUDIT.md:31`, `:165`).

Proposed engineering budgets on the documented minimum 6c/12t, 16 GB, CPU-only floor [P, unmeasured]:

| Stage | Target p95 | Interpretation |
|---|---|---|
| Launch → Screen A interactive | ≤5 s | Independent of model/network state. |
| Three mechanical setup actions with mic sample | ≤5 s | Usability hypothesis; reading reported separately. |
| Consent persisted → bundled inference verified | ≤5 s | Includes local verification/load/probe. |
| `/health`, status and Doctor during a held loader lock | ≤250 ms each | No timeout or event-loop stall. |
| Record action → capture acknowledgment | ≤150 ms | Must mean actual open/recording state. |
| Stop → visible reviewed draft, fixed 10 s utterance | ≤1.5 s warm; ≤3 s first-use | Capture and review display included, cleanup off. |

Collect at least 20 fresh-profile process starts plus 20 warm dictations per qualified machine/build; report p50/p95/max, failures, hardware, CPU load, model revision, compute path, cache condition and cold OS-cache caveat. Do not represent 20 process restarts as 20 fresh installs. Gather a small observed new-user trial to test reading/mic comprehension; scripted clicking alone cannot validate five-second ease. Audit boot samples (1.67/2.74/4.61 s) are historical, sparse, unpacked/dev-host evidence, not these gates (`docs/arc/SETUP_AUDIT.md:96-109`).

## 8. Acceptance tests and smallest slice

| ID | Required evidence |
|---|---|
| FR-01 | Hold consent untouched >30 s: zero external attempts, no microphone open, no models loaded. Imported profiles and alternate entry points cannot bypass. |
| FR-02 | Missing/unreadable/corrupt/outdated consent and failed durable write leave capture/network gates closed. Checkbox rollback, uncheck, decline and restart work with keyboard/focus-trap coverage. |
| FR-03 | Real broker meter identifies the actual chosen/fallback device. No signal, unplug, denied permission, stream error and skip display truthful states. Timeout/disconnect cleans the lease with no audio/history files. |
| FR-04 | Bundled clean, absent, partial and corrupt models: hash/provenance verification, no cache-miss network retry, readiness follows current inference proof. File presence and stale proof never pass. |
| FR-05 | A deliberately held model lock or slow worker cannot stall health/status/Doctor/heartbeat; run the 250 ms budget concurrently with load/probe. |
| FR-06 | Two-screen count, three normal setup inputs, persistence/resume, no auto-tour and no multi-model banner. Saving failures remain recoverable. Existing profiles retain custom choices; completing mode does not forge mic verification. |
| FR-07 | Every available mode obeys BF-D1 and saves atomically; unavailable Gamer explains its gate; Hands-free opens no wake listener. No mode tap downloads/enables optional engines or grants network consent. |
| FR-08 | Offline installed build produces a real captured reviewed draft and explicitly placed fixture text; logs distinguish fixture/device/hardware evidence and report section 7 stages. |
| FR-09 | Explicit later download/update/report actions require current scoped consent. Canceled, revoked, or expired operation cannot continue/acquire silently. No acquisition work is smuggled into warmup/status/repair. |

**NOW, smallest useful implementation slice:** fix the consent capability boundary for all automatic acquisition and capture entry points, default warmup to local-only/no pre-consent residency, suppress the pre-consent updater check, and make status observations nonblocking. Add focused FR-01/02/05 regressions plus the disposable packaged privacy probe. Keep the existing UI until this proves no surprise fetch. Do not inflate this safety slice with the mode redesign.

**NEXT:** ship the verified `base.en` payload, add inference-backed readiness and the real broker diagnostic lease, then replace onboarding with A/B and remove automatic tour/banner. FR-03/04/06/07/08 and the floor-machine timings gate the first-run experience.

**LATER:** optional upgrades/cleanup/wake/read-back consent flows, improved tutorial, broader language models and binding personalization. These must not delay the first valuable offline dictation.

## 9. Open questions with working assumptions

- **Installer size:** assume the estimated ~380 MB is acceptable for deterministic offline first use. Actual signed compressed size, installed disk requirement and verification time need a build measurement; no size guarantee is made here.
- **English-only bootstrap:** `base.en` is the current floor; assume initial first-run qualification is English. Do not market all-language support from this English model. A language-required flow needs a separately consented acquisition or bundled multilingual choice, and a revised budget.
- **Model selection ownership:** BF-D3 chooses local hardware/compute policy. D2 fixes the included first-use artifact and forbids larger unsolicited acquisition. Resolve a conflict explicitly before implementation; hardware recommendations do not overrule consent.
- **Gamer:** assume BF-D1's required protection/binding gates stay closed until tested. F1 alone is not certification. A user choosing Work can complete setup while Gamer remains unavailable.
- **Consent record compatibility:** assume the schema can separate local-use consent, diagnostic purpose and setup completion while preserving atomic writes and existing wipe semantics. Existing profiles are neither automatically mic-tested nor overwritten with Work defaults; re-prompt only the newly required purpose/version.
- **Performance:** all proposed first-dictation budgets remain targets. Disk hashing, antivirus cold-start, mic/driver latency and CPU fallback could miss them; measure before promising "instant" or "ready in five seconds."

The next move is the NOW safety slice with packaged zero-network evidence, followed by the offline bundled first-dictation gate.
