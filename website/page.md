BetterFingers is a local-first desktop dictation app. It captures speech, transcribes it locally, gives the user a review step, and places approved text into the focused application. Local language-model cleanup is available as an option, but it is off on a fresh install and is not required for basic dictation.

## Download the friend-testing alpha

Version `v1.1.0-alpha.2` is available for invited friend testing:

- [Download the Windows 11 x64 installer](https://github.com/RoyGSlade/BetterFingers/releases/download/v1.1.0-alpha.2/BetterFingers-Setup-1.1.0-alpha.2-x64.exe)
- [Open the release page for SHA-256 checksums, the signature report, SBOM, and experimental Linux AppImage](https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.2)

This is experimental alpha software. Azure signing validation is still pending, so the Windows installer is unsigned and Microsoft SmartScreen can warn about it. Download only from the official links above, compare the installer against its `.sha256` sidecar, and do not disable Windows Security or antivirus protections.

In PowerShell, calculate the downloaded installer's hash with:

```powershell
Get-FileHash .\BetterFingers-Setup-1.1.0-alpha.2-x64.exe -Algorithm SHA256
```

The resulting value must match the hash in `BetterFingers-Setup-1.1.0-alpha.2-x64.exe.sha256` on the release page before running the installer.

## First setup

Speech-to-text requires one local Whisper speech model. BetterFingers downloads that model only after the tester chooses it in setup, so network access and adequate disk space are required.

The separate multi-gigabyte language model used for AI cleanup is optional. Leave **Enable AI cleanup** off to dictate with Whisper alone. Model processing is intended to remain local; the release does not require a hosted LLM.

## What to test

Please use short, non-sensitive dictation while this build is experimental:

1. Install and launch BetterFingers.
2. Download a Whisper speech model and record a short sentence.
3. Review the transcript, edit it, and try copying or placing it into another application.
4. Quit and relaunch, then confirm the installed speech model is still found.
5. Try the same flow with the applications and microphone you normally use.
6. Uninstall BetterFingers when finished and report whether the app, backend, and Start Menu entry were removed cleanly.

Report reproducible problems through [GitHub Issues](https://github.com/RoyGSlade/BetterFingers/issues). Include the Windows version, CPU/GPU, microphone or audio interface, target application, exact steps, and visible error. Do not attach private transcripts or recordings.

## Current capabilities

The alpha includes local speech capture and Whisper-based transcription, optional local LLM refinement with personas, formatting commands, a personal dictionary, text macros, an editable review overlay, text-to-speech read-back, cross-application text placement, searchable history, recording recovery, privacy reporting, and data-wipe controls. Hardware-aware model recommendations help identify local model tiers that fit the machine.

## Boundaries and supported platforms

Windows 11 x64 is the primary friend-testing installer target for this alpha. A Linux AppImage is included as an experimental artifact; Linux X11 has the stronger compatibility path, while global hotkeys and text injection on Wayland remain best effort. macOS is not supported.

Raw recordings can be retained for recovery, and production-grade at-rest encryption is not included. Testers should not dictate highly sensitive, regulated, or confidential material. Automatic updates are not included, and friend testers will need to install later builds manually.

## Running from source

Developers can still run BetterFingers from a source checkout. On Linux, the repository documents a hardware-aware environment setup followed by the Electron development command:

```bash
python3 tools/setup_venv.py
cd app && npm install && npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

The local language-model runtime is required only when AI cleanup is enabled. These commands describe developer source-running and are separate from the alpha installers above.

## Release status

BetterFingers `v1.1.0-alpha.2` is an unsigned tagged public alpha for invited testing, not a stable or broadly qualified release. Friend feedback, Azure signing, reliability evidence, and wider hardware and application compatibility remain active qualification work.
