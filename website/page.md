BetterFingers is a local-first desktop dictation app. It captures speech, transcribes it locally, gives the user a review step, and places approved text into the focused application. Local language-model cleanup is available as an option, but it is off on a fresh install and is not required for basic dictation.

## Download the signed friend-testing alpha

Version `v1.1.0-alpha.3` is the signed Windows updater bootstrap for invited friend testing:

- [Download the signed Windows 11 x64 installer](https://github.com/RoyGSlade/BetterFingers/releases/download/v1.1.0-alpha.3/BetterFingers-Setup-1.1.0-alpha.3-x64.exe)
- [Open the release page for updater metadata, SHA-256 checksums, the Authenticode report, SBOM, and experimental Linux AppImage](https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.3)

This is experimental alpha software. The Windows installer is Authenticode signed by Donaven Crenshaw and carries a Microsoft timestamp, but a new publisher or low-download build can still receive a Microsoft SmartScreen reputation warning. Download only from the official links above, confirm the signature, compare the installer against its `.sha256` sidecar, and do not disable Windows Security or antivirus protections.

In PowerShell, calculate the downloaded installer's hash with:

```powershell
Get-FileHash .\BetterFingers-Setup-1.1.0-alpha.3-x64.exe -Algorithm SHA256
```

The resulting value must match the hash in `BetterFingers-Setup-1.1.0-alpha.3-x64.exe.sha256` on the release page before running the installer. Alpha 2 users install Alpha 3 manually over the existing copy; the installer keeps the same application identity and preserves user data by default.

## Updates after Alpha 3

Alpha 3 is the one-time updater bootstrap. Once it is installed, supported later Windows builds can be checked from the BetterFingers Update card in Settings. BetterFingers never downloads an update merely because it found one: **Download update** and **Restart and install** are separate user-approved actions. The signed update feed remains the public `RoyGSlade/BetterFingers` GitHub Releases channel.

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

The alpha includes local speech capture and Whisper-based transcription, optional local LLM refinement with personas, formatting commands, a personal dictionary, text macros, an editable review overlay, text-to-speech read-back, cross-application text placement, searchable history, recording recovery, privacy reporting, data-wipe controls, a guided setup tour, and consent-based signed Windows updates. Hardware-aware model recommendations help identify local model tiers that fit the machine.

## Boundaries and supported platforms

Windows 11 x64 is the primary friend-testing installer target for this alpha. A Linux AppImage is included as an experimental artifact; Linux X11 has the stronger compatibility path, while global hotkeys and text injection on Wayland remain best effort. macOS is not supported.

Raw recordings can be retained for recovery, and production-grade at-rest encryption is not included. Testers should not dictate highly sensitive, regulated, or confidential material. Updates do not remove settings, models, recordings, history, or other user data; optional data-category removal is available only through explicit uninstall choices.

## Running from source

Developers can still run BetterFingers from a source checkout. On Linux, the repository documents a hardware-aware environment setup followed by the Electron development command:

```bash
python3 tools/setup_venv.py
cd app && npm install && npm run fix:electron
BETTERFINGERS_PYTHON=../.venv/bin/python npm run dev
```

The local language-model runtime is required only when AI cleanup is enabled. These commands describe developer source-running and are separate from the alpha installers above.

## Release status

BetterFingers `v1.1.0-alpha.3` is a signed updater-enabled public alpha for invited testing, not a stable or broadly qualified release. Alpha 2 users must install this bootstrap manually. Friend feedback, reliability evidence, the first real Alpha 3-to-later-version updater test, and wider hardware and application compatibility remain active qualification work.
