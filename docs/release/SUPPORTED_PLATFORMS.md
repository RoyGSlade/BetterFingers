# BetterFingers v1.1.0-alpha.1 support contract

This is the binding scope for the `v1.1.0-alpha.1` prerelease. A platform or
feature is not called supported merely because source code, CI, or a control
exists. The exact release artifact must pass the named qualification before an
entry can move from **Experimental and labeled** to **Supported and tested**.

## Status meanings

- **Supported and tested** — the exact tagged artifact and hash passed the
  recorded clean-machine workflow on the named operating-system build.
- **Experimental and labeled** — available to alpha testers with an explicit
  limitation or an outstanding qualification gate.
- **Hidden from this release** — not offered in the alpha UI or documentation
  as a usable feature.

There is no unlabeled fourth state for a visible but unqualified control.

## Platform matrix

| Platform | Alpha disposition | Qualification required before support claim |
|---|---|---|
| Windows 11 x64, standard user | **Experimental and labeled** | Exact `.exe` hash; clean install; first run and model installation; core workflow; restart/cache rediscovery; recovery; Windows injection matrix; clipboard restoration; uninstall/reinstall; privacy wipe. |
| Linux x86_64, Linux Mint 22.x on X11 | **Experimental and labeled** | Exact AppImage hash on the exact Mint build; ordinary FUSE launch plus extract-and-run fallback; dependency failure/recovery; core workflow; Linux injection matrix; restart/cache rediscovery; privacy wipe. |
| Linux x86_64, Ubuntu 24.04 on X11 | **Experimental and labeled** | The same AppImage qualification on the exact Ubuntu build. Do not inherit a Mint result. |
| Linux Wayland | **Experimental and labeled** | Compositor-specific hotkey, selection, clipboard, and placement behavior must remain capability-reported. No general Wayland support claim. |
| macOS | **Hidden from this release** | Out of scope for this alpha. |
| Other Windows versions, Linux distributions, architectures, and desktop sessions | **Hidden from this release** | No compatibility claim. They may work, but they are unqualified. |

No platform is yet **Supported and tested** for `v1.1.0-alpha.1`. Current
evidence is still `PENDING`; historical `v0.2.0-alpha.1` evidence is archived
and cannot qualify this release.

## Feature matrix

| Feature or surface | Alpha disposition | Boundary |
|---|---|---|
| Record from the selected/system-default microphone | **Experimental and labeled** | Must pass unplug/replug, sleep/resume, long-recording, and clean-package checks. |
| Local Whisper transcription | **Experimental and labeled** | CPU-only is the minimum target. Model download, verification, resume, and cache rediscovery must pass on the exact package. |
| Local LLM rewrite | **Experimental and labeled** | Must report the real runtime/model and preserve a recoverable draft on failure. |
| Review and edit before delivery | **Experimental and labeled** | No injection may occur before approval; no automatic Enter or send is allowed. |
| Read aloud | **Experimental and labeled** | Must pass audible playback and stop/restart checks on qualified hardware. |
| Paste/inject or copy fallback | **Experimental and labeled** | Only applications recorded in the platform matrix may be claimed. Clipboard restoration and focus-loss behavior must pass. |
| Failed-recording and draft recovery | **Experimental and labeled** | Zero lost recordings and zero unrecoverable drafts are hard gates. |
| NVIDIA acceleration | **Experimental and labeled** | Claim only on physically tested NVIDIA hardware. CPU-only behavior remains the support floor. |
| AMD/Vulkan acceleration | **Hidden from this release** | No alpha support claim without physical qualification. |
| Controller activation | **Experimental and labeled** | Limited to the exact controller and mappings tested. Other controllers are unqualified. |
| Linux Wayland hotkeys, selection, and placement | **Experimental and labeled** | Best effort with honest capability/error reporting. |
| Applications outside a recorded injection matrix | **Experimental and labeled** | Copy fallback remains available; no application-specific guarantee. |
| Selected-text TTS | **Hidden from this release** | Selected-text rewrite evidence does not qualify selected-text speech. |
| Voice-cloning synthesis | **Hidden from this release** | Recording/import surfaces do not constitute a bundled synthesis engine. |
| Automatic updates | **Hidden from this release** | Alpha upgrades are manual and versioned artifacts are immutable. |
| Complete Scribe notebook/project system | **Hidden from this release** | Not part of the alpha core workflow. |
| Production-grade at-rest encryption | **Hidden from this release** | Processing is local, but stored alpha data is not promised to be encrypted at rest. |
| Universal GPU support | **Hidden from this release** | Hardware support is limited to configurations actually qualified. |

## Core alpha acceptance gate

The core workflow becomes **Supported and tested** for a platform only when one
exact release artifact completes:

1. record;
2. transcribe locally;
3. rewrite locally;
4. review and edit;
5. read aloud;
6. place or copy without an unintended send;
7. recover from a forced failure.

The qualification report must bind the result to the exact tag, commit,
filename, SHA-256, OS build/session, CPU, RAM, GPU, microphone, runtime/model,
tester, date, and PASS/FAIL/UNTESTED result.
