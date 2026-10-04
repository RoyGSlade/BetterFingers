# BetterFingers Known Limitations

Last reviewed: 2026-08-27

BetterFingers is public as `v1.1.0-alpha.3`. The public release contains a
signed Windows installer and an experimental Linux AppImage. The current
development checkout also contains later stabilization work that has not been
committed, tagged, or published. Do not describe those local changes as part
of Alpha 3.

The public release and the current checkout are intentionally separated below.

## Public Alpha 3 evidence

- Release: <https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.3>
- Tag commit: `7e03d09c2aa3217b8105b70609a198165a193d23`
- Windows installer SHA-256:
  `56254ef9c224d3e94366cff4691b4aaff24f6e31fe7f1e7f369cd250cbbcd696`
- The Windows installer has a valid Authenticode signature for Donaven
  Crenshaw.
- Release workflow: <https://github.com/RoyGSlade/BetterFingers/actions/runs/32281801195>

That workflow qualified its exact artifacts on hosted Windows and Ubuntu
runners. It did not establish broad hardware compatibility, SmartScreen
reputation, or support for every desktop, microphone, game, and communication
application.

## Current user-visible limitations

### Desktop automation and audio capture are environment-dependent

Keyboard injection, clipboard automation, microphone selection, per-process
audio capture, wake-word behavior, and Discord or OBS control can vary with
permissions, device drivers, desktop session, target application, and anti-cheat
or security software. BetterFingers must not be presented as universally
compatible with every game or desktop application.

Windows per-application capture isolation is unavailable. When the product
cannot prove an isolated application stream, it must not silently substitute a
broader system-audio stream.

Linux support remains experimental. Wayland compositors can restrict global
shortcuts, keyboard injection, clipboard access, window discovery, and audio
session inspection more heavily than X11. macOS is not a qualified target.

### Privacy is local-first, not magically risk-free

Core transcription and automation can run locally, but BetterFingers may still
make network requests for user-approved model or runtime downloads, release
update checks, and an explicitly reviewed bug report when a relay is configured.

Transcripts, history, profile data, diagnostics, and recordings can be sensitive.
BetterFingers does not currently provide application-level encryption at rest.
Users remain responsible for operating-system account security, disk encryption,
backups, and deleting data they no longer want retained.

The optional bug-report workflow sends a bounded, reviewable event trail and
environment summary—not arbitrary raw logs. Raw logs are deliberately excluded
because they can contain transcripts, local paths, tokens, or other private
data. The relay code is implemented, but no public relay endpoint is deployed
or configured in this checkout. Alpha 3 users must report issues manually.

### Models and optional runtimes are not all bundled

Large speech, wake, and language models can require substantial downloads,
memory, disk space, and startup time. Results vary by model, microphone, accent,
noise, CPU, and GPU. Model availability is not a guarantee that a particular
machine can run it well.

Voice-clone support has an optional runtime implementation, but its dependencies
and models are not bundled with the standard package. The feature must stay
disabled or clearly unavailable until that runtime is installed and qualified.

### Updates remain user-controlled

Alpha 3 includes update-channel plumbing and a user-driven update flow. It does
not silently replace the application. A future-version upgrade has not yet been
qualified end to end because no later public BetterFingers release exists.
Updater unit and contract tests do not substitute for a real upgrade using the
next signed public installer.

### Windows trust prompts can still occur

A valid Authenticode signature establishes publisher and file integrity; it does
not guarantee immediate Microsoft Defender SmartScreen reputation. New or
low-download releases can still show a warning. Consumer Windows 11, WDAC, and
reputation-based installation behavior require separate clean-machine checks.

## Current engineering and release limitations

- The parity inventory now records `409 wired / 29 intentional cuts / 0
  blocked`. That proves source/test anchoring in this checkout; it does not prove
  clean-machine behavior or that these local changes exist in public Alpha 3.
- A signed package proves only the source tree and dependency set used to build
  that exact package. Any later code change requires a fresh build and signature
  verification before release.
- The stabilization work in this checkout is local and dirty. Its signed package
  passed local verification, but it is neither the public Alpha 3 tag nor a
  committed release candidate and has not been installed or published.
- Clean Windows 11 hardware, representative microphones and applications,
  SmartScreen reputation, WDAC policies, a future live update, and an external
  bug-relay deployment remain outside automated local qualification.

## Recently resolved in the development checkout

The current local stabilization work fixes the clipboard snapshot/restore crash
boundary, settings refresh ordering, status navigation and contrast, history
delete error propagation, Windows archive-link fallback behavior, and the
six former wake/blend parity evidence gaps. The canonical ledger now has zero
blocked rows. The work also fixes strict-mode Windows signing-tool discovery and
review-first bug-report client/relay contract. These fixes are local until a new
release is explicitly authorized and published.

See also:

- [Supported platforms](SUPPORTED_PLATFORMS.md)
- [Release board](RELEASE_BOARD.md)
- [Bug reporting](../BUG_REPORTING.md)
- [Parity inventory](PARITY_INVENTORY.md)

Historical gate and wave notes are useful audit history, but old Alpha 1
statements are not the current product contract.
