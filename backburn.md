# BetterFingers â€” Backburner

> Deliberately deferred work. Nothing in this file is abandoned; it is prevented from
> destabilizing the active OpenAI Build Week and alpha plan in `ACCOMPLISH.md`.

This file exists because BetterFingers already has more promising directions than one
small team can safely build at once. A deferred idea may be valuable and still be the
wrong next task.

---

## 1. Rules for this file

1. Work stays parked unless the coordinator explicitly promotes it into
   `ACCOMPLISH.md` with an owner, dependency, test gate, and schedule.
2. â€œAn agent has spare timeâ€ is not a promotion reason. Spare capacity is used for tests,
   review, documentation, compatibility, or evidence.
3. No worker may implement a backburner item as adjacent cleanup.
4. A promoted item must have a smaller task packet than the entry in this file.
5. Items that touch the microphone, clipboard, injection, tool execution, voice cloning,
   or stored user content require an explicit safety review before promotion.
6. Items that require real hardware remain `UNTESTED` until that hardware exists. Code or
   CI stubs cannot convert them to `PASS`.
7. If an item conflicts with the core loopâ€”activate â†’ speak â†’ transcribe â†’ refine â†’
   review â†’ place â†’ recoverâ€”the core loop wins.

### Promotion checklist

Before moving an item into the active plan, answer:

- What user problem does it solve?
- Which one of Capture, Refinement, Review, Recovery, Placement, or Recall improves?
- What existing behavior could it break?
- What data does it read, store, transmit, or delete?
- What is the smallest vertical slice?
- Which exact files and contracts are involved?
- What automated and real-hardware evidence will prove it works?
- What current active task will be delayed or removed to make room?

---

## 2. Priority bands

| Band | Meaning | Earliest promotion point |
|---|---|---|
| B1 | Required before a broad public release, but not required for the Build Week submission | After the submission branch is frozen and backed up |
| B2 | Completes an existing subsystem or strengthens the first public alpha | After the reliability benchmark has a green primary-platform run |
| B3 | Product expansion that adds new modes, permissions, or platform complexity | After 1.0 core-loop gates remain green over time |
| Research | Important uncertainty that needs a spike or design decision before implementation | When a named product decision depends on it |
| Cut | Explicit non-goal for the foreseeable roadmap | Only after a new strategy decision |

---

## 3. B1 â€” post-submission, pre-public-release hardening

These items should be revisited soon after Devpost, but pulling them into the submission
window would threaten the visible Message Rescue slice or release evidence.

### B1.1 Reconcile the long-horizon documentation

**Work**

- Reconcile every completion marker in `DESIGN.md` against the release commit.
- Update the architecture diagram after backend/renderer extraction.
- Replace stale test counts with generated or release-recorded values.
- Reconcile `Tutorial_Script.txt` with the actual settings and Message Rescue UI.
- Update `LICENSES-MODELS.md` for every final downloadable artifact.
- Archive or link superseded planning documents instead of duplicating task queues.

**Why parked**

The submission README and Build Week log receive the verified facts first. A full
historical reconciliation is valuable but should not block the demo.

**Promotion gate**

Release commit selected; active task list frozen; coordinator has the final capability
matrix and artifact URLs.

### B1.2 DataRegistry and one canonical lifecycle

**Work**

Create one registry for recordings, transcripts, drafts, history, personas, dictionaries,
macros, voices, model metadata, logs, diagnostics, screenshots, temporary audio, context,
learned persona examples, and MCP configuration. Each category declares:

- storage path;
- schema version;
- retention policy;
- whether it may contain user text;
- export behavior;
- wipe behavior;
- diagnostics behavior;
- encryption status;
- migration behavior.

Generate privacy report, export, and wipe behavior from the registry. Eliminate parallel
lists in routes and diagnostics.

**Why parked**

This is a cross-cutting migration with high data-loss risk. Message Rescue must register
its new data honestly during the hackathon, but replacing every existing path should occur
under its own migration and recovery plan.

**Promotion gate**

Backups and historical-store fixtures exist; privacy/wipe tests are green; release data
locations are frozen; a migration rollback plan is accepted.

### B1.3 At-rest privacy controls

**Work**

- Document full-disk encryption as the default platform posture.
- Add â€œdo not persist raw audioâ€ mode.
- Add retention choices: never, until accepted, 24 hours, 7 days, manual-only.
- Design an optional encrypted vault using OS key storage rather than home-grown crypto.
- Ensure backups, exports, support reports, and crash artifacts follow the same policy.

**Why parked**

Key management and retention migrations require careful platform-specific testing. Local
processing alone does not make stored transcripts safe at rest.

**Promotion gate**

DataRegistry accepted; threat model written; Windows DPAPI/Credential Manager and Linux
Secret Service behavior tested; no HIPAA-readiness marketing claim.

### B1.4 Complete job-manager breadth

**Work**

Register TTS, voice cloning, model loads, model downloads, and long rewrites as jobs. Add:

- resource estimates;
- progress;
- cooperative cancellation;
- retry semantics;
- abandoned-task cleanup;
- low-disk behavior;
- concurrent model-download UI;
- raw-transcript preservation when LLM cleanup is cancelled.

**Why parked**

Dictation already has job tracking. Expanding every subsystem is important but not needed
to demonstrate the new feature.

**Promotion gate**

Message Rescue cancellation and recovery contracts are stable; model/resource UI owner
is available; heavy-resource integration tests can run without competing sessions.

### B1.5 Full dependency and toolchain pinning audit

**Work**

- Reconcile human-maintained `.in` ranges with generated exact locks.
- Remove stale claims that `requirements.txt` is the only dependency source.
- Decide whether `requirements.txt` remains a compatibility export or is removed.
- Pin Node, npm, Python, PyInstaller, Electron, electron-builder, and actions to the chosen
  policy.
- Verify lock freshness on Windows and Linux from a clean runner.
- Document why Linux and Windows use different Python versions and TTS stacks.

**Why parked**

Release workflows already use hashed locks and pinned runtime versions. The remaining
policy cleanup is broader than the submission artifact gate.

**Promotion gate**

Release workflow green; dependency update process documented; no active feature branch is
changing requirements.

### B1.6 Curated visual-regression baselines

**Work**

- Select stable screenshots from the deterministic QA harness.
- Store baselines under an intentional versioned path.
- Add reviewable diff artifacts and clear update commands.
- Keep negative controls that prove the harness catches lying backend states.

**Why parked**

The current QA report is useful and scenarios are required for new work. Curating a full
baseline library is not necessary for the three-minute demo.

**Promotion gate**

Message Rescue UI frozen; dynamic regions consistently masked; CI storage budget agreed.

### B1.7 Broader release operations

**Work**

- Closed-friends alpha workflow and support expectations.
- Issue templates that request the privacy-safe support report.
- Release rollback and revoked-artifact process.
- Source Arcanum release/changelog integration.
- Download telemetry decision consistent with â€œno telemetry.â€
- Optional donation and community links without in-app nags.

**Why parked**

Devpost needs a public artifact and project story, not a complete community operations
program.

**Promotion gate**

At least one signed or clearly unsigned alpha artifact is qualified; support channel and
response expectations are decided.

---

## 4. B2 â€” complete existing subsystems after reliability is green

### B2.1 TTS DSP and playback completion

**Work**

- Streaming playback.
- BS.1770 or well-defined RMS loudness normalization.
- Crossfade between chunks.
- Cache and cancellation behavior under rapid repeated reads.
- Voice/preset loudness comparison by ear.
- Natural reading for currency, titles, URLs, dates, abbreviations, and symbols.

**Why parked**

TTS works today. A small demo-blocking clarity bug may be promoted, but a complete audio
pipeline needs listening tests and should not share devices with active STT work.

**Promotion gate**

Core reliability benchmark green; audio ownership is explicit; curated listening corpus
exists; task owns `__audio-device__` and `__full-test-suite__` when required.

### B2.2 Voice-cloning completion

**Work**

- Publish and verify `clone-runtime-v1` artifacts.
- Complete export routes.
- Resolve native backend blending instead of base-voice fallback.
- Investigate ONNX export of the Kanade pipeline.
- Add optional audible disclosure marker for exports.
- Recheck WavLM/derivative licensing and attribution.
- Expand consent, deletion, and provenance QA.

**Why parked**

The provisioning and engine work is substantial but the artifact publication and
cross-platform runtime remain incomplete. It adds large dependencies and abuse-sensitive
behavior unrelated to Message Rescue.

**Promotion gate**

Core alpha released; license review accepted; abuse controls reviewed; artifact host and
hash policy established; dedicated platform matrix available.

### B2.3 Persona editor completeness

**Work**

- Live composed-prompt preview.
- Full base/blend/speed/modulation controls.
- Rich few-shot raw-to-output editor.
- Dictionary-scope control.
- Model-hint routing that never triggers a surprise download.
- Persona import/export and conflict resolution.
- Voice-preservation evaluation dashboard.

**Why parked**

The hackathon adds only the controls needed to inspect and remove learned examples. A full
expert editor is a separate UX project.

**Promotion gate**

Learned-example schema stable; persona migration fixtures green; real users demonstrate
which controls they need.

### B2.4 Golden audio and alternative STT qualification

**Work**

- Check in consented or synthetic `.wav`/`.txt` fixtures.
- Build `test_golden_audio.py` and per-model WER thresholds.
- Add representative accents, noise levels, domain terms, hesitations, and long pauses.
- Qualify larger Whisper choices by hardware tier.
- Evaluate Moonshine or Parakeet-ONNX behind the transcriber interface.

**Why parked**

Message Rescue retains timing from the existing Whisper backend. Adding another STT
engine before the result contract is field-tested would multiply variables.

**Promotion gate**

Structured transcription contract accepted; fixture license/consent recorded; model cache
and CI resource budget available.

### B2.5 Wake-word and command qualification

**Work**

- Real recorded positive/negative fixtures.
- False-accept and false-reject measurement.
- Field recordings across microphones, speakers, rooms, and accents.
- Sensitivity calibration and false-trigger log.
- Import/export polish.
- Observed-transcript alias learning.
- Complete voice-command preview and confirmation UX where still incomplete.

**Why parked**

Always-listening and ambient-command paths have a higher safety bar. The builder existing
does not substitute for real FA/FR evidence.

**Promotion gate**

Core microphone ownership and reliability are green; privacy review accepted; an audible
and visual armed state is tested; no destructive action can bypass confirmation.

### B2.6 Model-resource diagnostics UI

**Work**

- Render `/models/resources` ledger in Diagnostics.
- Show resident models, estimated memory, headroom, and idle eviction.
- Surface structured LLM admission refusal and lighter-model suggestion.
- Define equivalent structured STT/TTS refusal details or document the asymmetry.

**Why parked**

Backend and QA contract exist. This is useful but does not improve the judge's primary
communication flow unless a memory refusal blocks the demo.

**Promotion gate**

No Message Rescue renderer hotspot is active; API response is stable; visual scenario
owner available.

### B2.7 Injection matrix completion

**Work**

Run real probes across Chrome, Google Docs, Outlook, Word, VS Code, Discord, Slack,
Notepad, an EHR-like form, and remote desktop on supported platforms. Record:

- plain text;
- multiline;
- Unicode and punctuation;
- selection replacement;
- clipboard restoration;
- focus loss;
- elevated windows;
- latency;
- editor-specific failures.

**Why parked**

The active plan qualifies a smaller, honest release matrix. Completing every target
requires multiple real machines and accounts.

**Promotion gate**

Artifacts stable; test machines available; no active injection implementation changes;
privacy-safe evidence format agreed.

### B2.8 Audio device ownership coordinator

**Work**

Give STT capture, TTS playback, wake monitoring, and previews one negotiated owner per
device. Handle unplug/replug, default-device changes, busy devices, and cancellation.

**Why parked**

The architecture is important but touches every audio subsystem. The active build keeps
wake expansion and cloning frozen to limit ownership conflicts.

**Promotion gate**

Core Message Rescue path released; device state machine designed; platform-specific test
hardware available.

### B2.9 InputCoordinator

**Work**

Centralize keyboard, uiohook-napi, controller, Electron shortcuts, missed key-up recovery,
rebind mode, shutdown, and duplicate trigger suppression.

**Why parked**

Current single-flight and watchdog behavior protects the core path. Centralization is
still required before expanding triggers.

**Promotion gate**

Core input tests green on Windows/X11; exact event ownership contract written; no active
hotkey UI work.

### B2.10 Electron updater and release channel

**Work**

- NSIS and AppImage update channels.
- Signature verification.
- Differential update behavior.
- Rollback and failed-update recovery.
- Clear consent and bandwidth behavior.

**Why parked**

An updater amplifies release mistakes. Manual alpha downloads are safer until signing and
rollback are proven.

**Promotion gate**

Two qualified releases exist; signing is stable; rollback artifact is available.

---

## 5. B3 â€” post-1.0 expansion

### B3.1 Meetings mode

Loopback plus microphone capture, offline diarization, speaker review, notes, action items,
and Library timeline.

**Risks:** consent, multi-speaker privacy, long-duration resource use, diarization errors,
and a large new persistence surface.

**Promotion gate:** 1.0 core loop stable; DataRegistry and retention controls complete;
separate design and consent model approved.

### B3.2 Brainstorm mode

Streaming STT, VAD turn-taking, question-generating loop, constellation UI, and project
export.

**Risks:** conversational mode complexity, unsolicited interruptions, scope drift, and
duplicating other notebook/agent products.

**Promotion gate:** 1.0 stable; user research shows a distinct BetterFingers advantage;
separate vertical-slice design accepted.

### B3.3 Threads and Echo cards

Long-lived communication threads, resurfaced memories, and related-message cards.

**Risks:** persistent sensitive history, confusing provenance, and accidental context
leakage between conversations.

**Promotion gate:** DataRegistry, retention, encryption, and explicit context controls are
complete.

### B3.4 Semantic recall

sqlite-vec or another local vector index for semantic search.

**Risks:** embedding model cost, migration, deletions that fail to remove vectors, and
search results exposing old sensitive content.

**Promotion gate:** canonical history store and wipe/export invariants proven.

### B3.5 MCP tool execution

Local LLM tools bridge, per-persona allowlists, visible permission prompts, command
transcripts, default-deny writes, and destructive confirmation.

**Risks:** ambient speech to external side effects, prompt injection through selected
context, data exfiltration, unclear identity, and irreversible actions.

**Promotion gate:** explicit security design, threat model, sandbox, redaction audit,
per-tool permissions, and human confirmation prototype. Read-only MCP listing remains the
default until then.

### B3.6 Large Stream/Library/Studio UI evolution

Chronological utterance Stream, Library, Studio, status rail, design tokens, tactile
visual language, and fully rendered confidence.

**Risks:** broad regression surface and distraction from core reliability.

**Promotion gate:** incremental proposal with one view at a time; deterministic screenshot
baseline; no framework migration.

### B3.7 macOS support

Signed/notarized package, permissions, accessibility injection, audio behavior, keychain,
and hardware qualification.

**Risks:** new platform, signing/notarization costs, permission UX, and untested injection.

**Promotion gate:** explicit funding/hardware decision and dedicated maintainer capacity.

---

## 6. Research queue

Research tasks produce a decision record or prototype, not production behavior.

### RQ.1 Text-box inactivity and â€œthe user is stuckâ€ detection

Investigate Windows UI Automation and Linux AT-SPI for detecting focused editable fields,
selection, value changes, dwell time, and app identity. Document Wayland limitations and
permission requirements.

Questions:

- Can focus be observed without reading the field contents?
- Can the feature be opt-in per application?
- How is ordinary thinking distinguished from being stuck?
- What false-positive rate is acceptable?
- How does the user dismiss or disable suggestions instantly?
- Can the system avoid monitoring password, payment, health, and secure fields?

Do not build a global 30-second timer until these questions have evidence-backed answers.

### RQ.2 Automatic conversation context

Investigate platform accessibility APIs and app-specific adapters, but preserve explicit
selection as the default. Any automatic approach must answer:

- exactly what text is read;
- how much history is captured;
- how the user previews and removes it;
- whether it leaves the device;
- whether it persists;
- how secure fields and unrelated windows are excluded;
- how prompt injection inside received messages is contained.

### RQ.3 Emotion-model evaluation

Compare deterministic prosody features, lexical local-LLM assessment, and dedicated local
speech-emotion models across accents, neurotypes, microphones, languages, and recording
conditions. Measure calibration and disagreement rather than only top-label accuracy.

The product should prefer delivery axes and evidence over a single emotion label unless a
model demonstrates trustworthy calibrated behavior.

### RQ.4 Longitudinal voice preservation

Study whether approved examples are sufficient or whether BetterFingers needs a separate
style profile. Evaluate:

- sentence length and rhythm;
- contractions;
- punctuation;
- directness;
- hedging;
- emoji and sign-offs;
- preferred vocabulary;
- audience-specific voice;
- drift and undo behavior.

Avoid biometric â€œvoiceprintâ€ terminology unless the implementation truly handles
biometric data and its obligations. â€œWriting styleâ€ or â€œpersona examplesâ€ is safer today.

### RQ.5 Model routing

Determine whether `model_hint` should select a loaded model, suggest a model, or remain
metadata. Never trigger a surprise download or unload during dictation.

### RQ.6 Cross-vendor acceleration

Evaluate Vulkan llama-server/whisper.cpp as a universal path, CUDA variants, AMD behavior,
Intel iGPU behavior, KV-cache quantization, prompt caching, and hot switching. This
requires published binaries and real hardware, not only configuration code.

### RQ.7 Per-app injection profiles

Evaluate active-window detection in Electron and platform-specific Wayland adapters.
Document app identity stability, focus races, elevation boundaries, and privacy.

---

## 7. Explicit cuts

These are not planned unless the product strategy changes.

- Cloud-required transcription, rewriting, or TTS as the default path.
- Silent collection of conversation history.
- Automatic learning from messages without user approval.
- Claims that emotion inference reveals a user's true mental state.
- Medical, legal, therapeutic, or HIPAA-readiness claims without the corresponding
  validation and governance.
- Destructive MCP or voice actions without confirmation.
- Bundling model weights without verified source, revision, license, hash, and expected
  size.
- Pretending Linux Wayland has Windows/X11 injection parity.
- Calling an unsigned Windows artifact signed.
- Calling the hackathon build 1.0.
- A framework rewrite undertaken only to make the repository look modern.
- In-app donation nags or a hidden future paywall.

---

## 8. Parking-lot entry template

Add new items with this structure:

```markdown
### <ID> <Title>

**Problem**

<User problem, not implementation excitement.>

**Proposed slice**

<Smallest demonstrable behavior.>

**Why parked**

<Risk, dependency, missing evidence, or displaced active work.>

**Promotion gate**

<Concrete conditions required before moving into ACCOMPLISH.md.>

**Likely claims**

<Files, shared resources, and contracts.>
```

The backburner protects the product from feature amnesia and from feature panic at the
same time. BetterFingers does not need every good idea immediately. It needs the current
communication loop to be trustworthy, understandable, and finished.