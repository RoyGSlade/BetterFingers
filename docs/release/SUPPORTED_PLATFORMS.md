# BetterFingers v1.1.0-alpha.3 support contract

This is the binding support boundary for the public `v1.1.0-alpha.3` prerelease
and for the newer, unpublished development checkout. Source code, a visible
control, or a green unit test is not by itself a platform-support claim.

## Evidence boundary

- **Public release:** tag `v1.1.0-alpha.3` at
  `7e03d09c2aa3217b8105b70609a198165a193d23`, published 2026-08-19.
- **Windows artifact:** `BetterFingers-Setup-1.1.0-alpha.3-x64.exe`, SHA-256
  `56254ef9c224d3e94366cff4691b4aaff24f6e31fe7f1e7f369cd250cbbcd696`,
  Authenticode status `Valid`, signed by Donaven Crenshaw.
- **Release workflow:** the exact tag passed the public build, signature,
  package, install, Alpha 2 → Alpha 3 replacement, verified model-download,
  launch/health, uninstall, checksum, SBOM, and publication jobs on
  [GitHub Actions run 32281801195](https://github.com/RoyGSlade/BetterFingers/actions/runs/32281801195).
- **Development checkout:** newer local fixes are not in the public Alpha 3
  binaries. Local test/build evidence may qualify the code under review, but it
  cannot retroactively qualify or change the published artifact.

## Status meanings

- **Supported and tested** — the claim is limited to the exact artifact,
  operating-system image, workflow, and hardware actually exercised.
- **Experimental and labeled** — available to alpha testers, but important
  hardware, desktop-session, application, or clean-machine coverage is still
  incomplete.
- **Hidden from this release** — not offered as a supported Alpha 3 capability.

There is no unlabeled fourth state for a visible but unqualified control.

## Platform matrix

| Platform | Alpha disposition | What is proved and what is not |
|---|---|---|
| Windows Server 2025 GitHub runner (`windows-2025-vs2026`) | **Supported and tested — package mechanics only** | The exact public installer passed signature verification, install, Alpha 2 → Alpha 3 replacement, no-LLM first launch, authenticated backend health, one real pinned wake-model download, and uninstall. This does not qualify microphones, global PTT, clipboard preservation, injection into third-party apps, SmartScreen reputation, or consumer Windows hardware. |
| Windows 11 x64, standard user | **Experimental and labeled** | A signed installer exists, but a recorded clean Windows 11 operator matrix is still required for audio devices, sleep/resume, models, PTT, selection, clipboard restoration, target-app injection, update UI, recovery, privacy wipe, and uninstall/reinstall. |
| Ubuntu 24.04.4 GitHub runner | **Supported and tested — AppImage build/launch only** | The exact AppImage passed build, checksum, and automated launch smoke. It was not a microphone, X11/Wayland input, model-performance, or desktop-injection qualification. |
| Linux Mint 22.x or other Linux distributions on X11 | **Experimental and labeled** | Run-from-source and AppImage paths exist. Each distribution still needs its own audio, dependency, model, selection, injection, restart, and privacy-wipe matrix. |
| Linux Wayland | **Experimental and labeled** | Hotkeys, selection, clipboard, and placement are compositor/tool dependent. Capability reporting and copy fallback do not turn that into a general Wayland guarantee. |
| macOS | **Hidden from this release** | No macOS artifact or support claim. |
| Other Windows versions, architectures, and desktop sessions | **Hidden from this release** | They may work, but they are unqualified. |

## Feature matrix

| Feature or surface | Alpha disposition | Boundary |
|---|---|---|
| Local microphone recording and Whisper transcription | **Experimental and labeled** | Model download and local inference exist; microphone permissions, device changes, sleep/resume, long recordings, and performance remain hardware-specific. |
| Local LLM rewrite | **Experimental and labeled** | Requires a compatible local llama.cpp runtime and model. AI cleanup is optional and disabled on a fresh install. |
| Review/edit/read-aloud before delivery | **Experimental and labeled** | Review is the safety boundary. TTS voice/runtime compatibility and audio output remain machine-specific. |
| Paste/inject or copy fallback | **Experimental and labeled** | Never infer compatibility from tool presence. Only target applications and desktop sessions actually tested may be claimed. |
| Failed-recording and draft recovery | **Experimental and labeled** | Recovery paths are implemented and tested, but zero-loss claims require real microphone and failure-injection qualification on the target machine. |
| NVIDIA acceleration | **Experimental and labeled** | Claim only for models and GPUs physically measured. CPU-only remains a valid operating mode. |
| AMD/Vulkan acceleration | **Hidden from this release** | No general Alpha 3 support claim. |
| Controller activation and Game Night workflows | **Experimental and labeled** | Limited to tested devices, mappings, games, Discord/manual-join behavior, and explicit safety approvals. |
| Wake phrase training and live testing | **Experimental and labeled** | The flow is local and privacy-gated. Model provenance, false-accept/false-reject rates, microphone hardware, and field reliability remain qualification gates. |
| Voice-cloning synthesis | **Experimental and labeled** | A real optional Kanade conversion runtime is implemented and checksum-pinned, but it is not bundled and remains hardware/performance dependent. Consent and sample ownership are mandatory. |
| Automatic updates | **Experimental and labeled** | Alpha 3 publishes channel metadata; check, download, and install are separate user actions. A future signed release must still prove the live Alpha 3 → newer-version path. |
| In-app Discord/email bug delivery | **Experimental and disabled by default** | The development tree has a review-first, bounded relay client and deployable server component. No relay endpoint or server-side credentials are deployed by this checkout; Alpha 3 uses manual GitHub/Discord reporting. |
| Per-application Windows capture isolation | **Hidden from this release** | The Windows Core Audio adapter remains feasibility-only. BetterFingers must not disable the physical microphone. |
| Production-grade at-rest encryption | **Hidden from this release** | Speech processing is local, but stored recordings, drafts, profiles, and history are not promised to be encrypted at rest. |
| Universal GPU, desktop, application, or model compatibility | **Hidden from this release** | Compatibility is limited to configurations actually qualified. |

## Core workflow acceptance gate

A platform can be promoted from **Experimental and labeled** only when one exact
release artifact completes a recorded, user-level workflow: record, transcribe
locally, rewrite locally, review/edit, read aloud, place or copy without an
unintended send, recover from a forced failure, restart, update where applicable,
and wipe data.

The report must bind the result to the exact tag, commit, filename, SHA-256,
operating-system build/session, CPU, RAM, GPU, microphone, target application,
runtime/model, tester, date, and PASS/FAIL/UNTESTED result.
