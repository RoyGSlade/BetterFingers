The grand TODO list
Phase 1: Lock the alpha’s scope

Before changing anything else, write down exactly what this alpha supports.

Supported for v1.1.0-alpha.1

Use a deliberately narrow claim:

Windows 11 x64
Linux x86_64 on X11
Linux Mint 22.x and/or Ubuntu 24.04 only after testing those exact versions
CPU-only inference as the minimum supported runtime
NVIDIA acceleration only on hardware you physically test
Core workflow:
record
transcribe
locally rewrite
review/edit
read aloud
inject or copy
recover failed recordings
Experimental
Linux Wayland
Controller activation beyond whichever controller you test
Applications outside the recorded injection matrix
AMD/Vulkan acceleration unless physically tested
Explicitly excluded from this alpha
macOS
Automatic updates
Guaranteed support for every Linux distribution
Selected-text TTS unless separately qualified
Voice-cloning synthesis
Universal GPU support
A complete Scribe notebook/project system
Production-grade at-rest encryption

The README already identifies Windows and Linux as intended targets while stating that Windows, general injection/PTT, Wayland, selected-text TTS, audio, hardware, package installation, and reliability are not yet qualified. It also states that no signed installer or auto-update channel exists and that voice cloning has no bundled synthesis engine.

Completion condition

Create:

docs/release/SUPPORTED_PLATFORMS.md
docs/release/KNOWN_LIMITATIONS.md

Every visible feature must then be one of:

Supported and tested
Experimental and labeled
Hidden from this release

No mysterious fourth category called “the control exists, but spiritually.”

Phase 2: Repair the release evidence

The current evidence directory contains a real contradiction.

The branch is preparing v1.1.0-alpha.1, but the committed X11 qualification evidence identifies:

App version 0.2.0-alpha.1
Artifact BetterFingers-0.2.0-alpha.1.AppImage
Repository commit ef1ed0d...
An older artifact hash

That evidence may be historically useful, but it cannot qualify the current release.

Required work
Move the existing evidence to:
docs/release/evidence/historical/v0.2.0-alpha.1/
Create a clean directory:
docs/release/evidence/v1.1.0-alpha.1/
Refresh OPERATOR_QA.md, whose heading still says it is the script for v0.2.0-alpha.1.
Add a release manifest:
docs/release/evidence/v1.1.0-alpha.1/release-manifest.json

It should record:

{
  "version": "1.1.0-alpha.1",
  "tag": "v1.1.0-alpha.1",
  "commit": "<exact-sha>",
  "windows": {
    "filename": "<installer>.exe",
    "size_bytes": 0,
    "sha256": "",
    "authenticode_status": ""
  },
  "linux": {
    "filename": "<appimage>.AppImage",
    "size_bytes": 0,
    "sha256": ""
  },
  "qualification_status": "PENDING"
}
Every qualification report must include:
Exact tag and commit
Exact artifact filename
SHA-256
Operating-system build
X11 or Wayland session
CPU, RAM, GPU
Microphone
Runtime and model identifiers
Tester
Date
PASS, FAIL, or UNTESTED
Completion condition

There is no current-release evidence containing 0.2.0-alpha.1, an older commit, or a different binary hash.

Phase 3: Finish the candidate source
Required work
Let current CI finish.
Confirm every required job is green.
Read the Ruff report and fix meaningful findings even though Ruff is report-only.
Run the complete local release validation from a clean checkout.
Rebuild the renderer before Electron QA.
Commit all final release-document changes.
Freeze features.

Recommended local validation:

git switch release/v1.1.0-alpha.1
git pull --ff-only
git status --short

python3 tools/parity_ledger_build.py
python3 tools/parity_validator.py

env -u BETTERFINGERS_DATA_DIR \
    -u BF_QA_USER_DATA_DIR \
    .venv/bin/python -m pytest -q

cd app
npm ci
npm run test:unit
npm run build
cd ..

rm -rf /tmp/bf-qa-data /tmp/bf-qa-user
mkdir -p /tmp/bf-qa-data /tmp/bf-qa-user

BETTERFINGERS_DATA_DIR=/tmp/bf-qa-data \
BF_QA_USER_DATA_DIR=/tmp/bf-qa-user \
node app/tests/qa/run.mjs

The environment separation matters because the repository’s operator script warns that using the QA data variables during Python tests creates false failures. It also warns that Electron QA executes the built renderer rather than current source files.

Completion condition
Working tree clean
All required GitHub checks green
Local Python suite green
Renderer suite green
Production Electron board green
Production build green
Parity blocked count zero
No feature changes after this point

After this freeze, only release-blocking bug fixes are permitted. “One more neat feature” is how software projects quietly become archaeological sites.

Phase 4: Fix the reliability-reporting gap

The current reliability framework knows about:

100 consecutive dictations
50 restart-recovery cycles
Long recordings
Microphone unplug/replug
Sleep/resume
Clipboard restoration
Application injection

But the live CLI only accepts --dictations, --health-checks, --json, and --skip-manual. It has no way to import completed human results. If manual checks are included, they remain incomplete and the gate cannot pass.

There is another important distinction: the current automated “dictation” test creates mock drafts, accepts and declines them, and repeats health requests. It does not process live microphone audio through Whisper, the LLM, review, and real placement. Fifty health requests also are not fifty application restart cycles, despite both numbers containing fifty and therefore apparently looking interchangeable to computers.

Required work

Add:

--manual-results <path>

The manual-results file should support:

{
  "checks": [
    {
      "name": "sleep_resume",
      "status": "pass",
      "detail": "Windows 11; app resumed and completed five dictations"
    }
  ]
}

The runner must:

Reject missing required checks
Reject unknown check names
Require PASS or FAIL
Merge automated and manual evidence
Include artifact metadata
Exit nonzero if anything fails or remains incomplete
Completion condition

One command produces a single final reliability JSON report whose top-level result is passed: true, with no skipped or pending checks.

Phase 5: Build and prequalify branch artifacts

Before merging or tagging, run build-installer manually against the final branch head.

This is a rehearsal run. Its purpose is to find packaging and clean-machine failures before permanently creating the release tag.

Download and test

Use:

A clean Windows 11 machine or VM
A clean Linux X11 machine or VM
At least one physical machine for microphone, hotkey, audio, and sleep/resume testing

Do not test only on the development computer. Developer machines are contaminated with every runtime, library, environment variable, and half-remembered workaround installed since the Bronze Age.

Completion condition

The final branch artifacts pass:

Windows clean install
Linux clean launch
First-run onboarding
Initial model installation
First dictation
Restart and cache rediscovery
Uninstall/reinstall or replacement
Basic injection
Recovery after one forced failure

Fix anything discovered, rerun CI, rebuild, and repeat this phase.

Platform qualification
Phase 6: Windows qualification

Use a standard user account with no Python, Node, Git, llama.cpp, or developer checkout installed.

Installation
Download the candidate installer.
Verify its SHA-256:
Get-FileHash .\<installer>.exe -Algorithm SHA256
Compare it with the .sha256 sidecar.
Record the Authenticode status from the included signature report.
Install to the default path.
Confirm the app launches without developer tools.
Record the exact SmartScreen experience if unsigned.
First run
Onboarding opens automatically.
Consent is understandable.
Declining does not pretend to continue.
Startup reports real backend, model, and audio states.
The microphone starts at System Default.
Missing models show an explained installation state.
Download progress shows file, size, progress, verification, and ready status.
Interrupt one large model download and confirm it resumes correctly.
Restart the app and confirm installed models are rediscovered.
Core workflow

Complete at least ten varied dictations:

One sentence
Several paragraphs
Punctuation
Numbers
Unicode
A correction or edit
Persona rewrite
Read-aloud playback
Placement into another app
Recovery after a forced pipeline failure

For every run:

No injection occurs before review approval.
No Enter key is sent unexpectedly.
Existing clipboard contents return afterward.
Raw audio remains recoverable after failure.
Runtime status reflects reality.
Hardware behavior
Select a different microphone.
Unplug the selected microphone.
Confirm fallback or clear failure messaging.
Reconnect it.
Put the system to sleep and resume.
Close and relaunch BetterFingers repeatedly.
Test CPU-only mode.
Test NVIDIA acceleration only if the machine actually has supported NVIDIA hardware.
Windows injection matrix

Test at minimum:

Target	Required
Notepad	Yes
Browser textarea	Yes
VS Code	Yes
Discord or Slack	Yes
Word or LibreOffice Writer	Yes
PowerShell or Windows Terminal	Yes
Elevated application	Expected limitation must be documented

For each target test:

Plain text
Multiline text
Unicode
Punctuation
Selected-text replacement
Clipboard restoration
Focus loss
No accidental Enter
No automatic send
Installation lifecycle
Uninstall
Record whether user data remains or is removed
Reinstall
Confirm expected model and settings continuity
Confirm privacy wipe actually removes drafts, history, and recordings
Completion condition

A committed windows-qualification.json reports PASS for the core workflow, with every unsupported case explicitly marked rather than silently omitted.

Phase 7: Linux X11 qualification

Use a clean Linux installation running an actual X11 session.

Confirm:

echo "$XDG_SESSION_TYPE"

It should report:

x11
Package launch

Verify and launch normally:

sha256sum -c <appimage>.AppImage.sha256
chmod +x <appimage>.AppImage
./<appimage>.AppImage

Then test the fallback:

./<appimage>.AppImage --appimage-extract-and-run

The automated workflow currently uses --appimage-extract-and-run under Xvfb, so it proves that the package and bundled backend can launch. It does not prove ordinary desktop execution through FUSE on a clean user system.

Dependency behavior

Test once without xclip, xsel, and xdotool.

The app should identify the missing dependency and explain what function is unavailable. It should not simply sit there looking disappointed.

Then install the required X11 tools and repeat.

The README states that X11 selection, copying, and typing paths depend on DISPLAY, xclip or xsel, and xdotool.

Core workflow

Repeat the Windows first-run, model-installation, dictation, recovery, audio-device, sleep/resume, privacy-wipe, and restart checks.

Linux injection matrix

Test:

Terminal
Browser textarea
VS Code
xed, Kate, or another native editor
LibreOffice Writer
Discord or Slack

The current matrix already has useful automated results for Terminal, VS Code, Chrome, and an EHR-like web form. LibreOffice is only partial, while Discord, Slack, Google Docs, Word, Outlook, Notepad, and remote desktop remain untested. It also contains no Windows results.

Distribution claim

Only claim the Linux systems you test.

For example:

Qualified on Linux Mint 22.3 Cinnamon using X11 and Ubuntu 24.04 using X11. Other distributions may work but are unqualified.

Do not write “Linux supported” as if Arch, Fedora, Debian stable, Ubuntu, Mint, NixOS, and somebody’s custom window manager are one obedient species.

Completion condition

A committed linux-x11-qualification.json passes the full core workflow against the exact release AppImage hash.

Reliability qualification
Phase 8: Complete the real reliability run

Run the repository’s automated benchmark, but do not substitute it for real use:

python3 tools/reliability_benchmark.py \
  --dictations 100 \
  --health-checks 50 \
  --json docs/release/evidence/v1.1.0-alpha.1/reliability-automated.json \
  --skip-manual

Then complete the production-path testing.

Required real-world checks
100 consecutive real dictations on the primary release platform
50 full application/backend restart cycles
5-minute recording
15-minute recording
30-minute recording
60-minute recording
Microphone unplug/replug
Sleep/resume
Kill the backend during processing
Interrupt and resume a model download
Clipboard restoration
Application injection matrix
Privacy wipe
Recovery from failed transcription
Recovery from failed LLM processing
Recovery from failed placement

Use a fixed test script of 25 phrases repeated four times for the 100-dictation run. Include:

Short commands
Long paragraphs
Names
Numbers
Punctuation
Technical terms
Unicode
Intentional silence
Interrupted speech
Speech with corrections

Record each activation separately.

Hard reliability requirements
Zero unintended sends
Zero unintended Enter presses
Zero lost recordings
Zero unrecoverable drafts
Zero injections before review approval
100 of 100 completed or recovered
50 of 50 restart cycles return to a usable state
Every failure has an understandable message

The repository’s own operator status still lists the exact package checks, real model installation, Windows and Linux matrices, 100-dictation run, signing disclosure, and public-link verification as open release gates.

Final release construction
Phase 9: Merge and create the exact release tag

The current PR language says not to merge or tag before exact artifacts pass. The workflow, however, only generates provenance-backed release artifacts after a tag is pushed. That wording should be corrected to:

Do not publish until the exact tag-generated artifacts pass qualification. Merge only after branch-artifact prequalification passes.

The clean sequence is:

Prequalify final branch artifacts.
Mark PR #94 ready.
Merge PR #94 into main.
Pull the exact merged main.
Record the commit.
Create the annotated tag.
Push only the tag.
git switch main
git pull --ff-only
git status --short
git rev-parse HEAD

git tag -a v1.1.0-alpha.1 \
  -m "BetterFingers v1.1.0-alpha.1"

git push origin v1.1.0-alpha.1

The tag workflow will:

Run the Windows test chunks
Build the Windows NSIS installer
Generate the Windows checksum and signature-status sidecar
Build and smoke-test the Linux AppImage
Generate the Linux checksum
Generate an SBOM
Create build-provenance attestations on the tag path
Stop at the protected release environment for approval
Important version rule

If the tagged artifacts fail final qualification:

Do not approve publication.
Do not replace the tag.
Do not upload corrected files under the same version.
Fix the problem on a new branch/version.
Release v1.1.0-alpha.2.

Immutable versions make bug reports meaningful. Quietly replacing binaries turns “alpha testing” into forensic accounting.

Phase 10: Qualify the exact tagged artifacts

Download the .exe and .AppImage generated by the tag workflow while the publication job waits for environment approval.

Repeat the decisive package checks against those exact hashes:

Clean installation or launch
First-run onboarding
Model download
Restart/cache rediscovery
One complete dictation workflow
One forced recovery
One injection target
Clipboard restoration
Uninstall/reinstall or AppImage replacement

Update the evidence manifest with the exact hashes.

This final pass prevents a branch build from receiving credit for a different tag-generated binary.

Completion condition

The release manifest states:

"qualification_status": "PASS"

and references the same filenames and hashes attached to the pending GitHub release.

Release documentation
Phase 11: Prepare the tester-facing material

Create or update:

README.md
docs/release/RELEASE_NOTES_v1.1.0-alpha.1.md
docs/release/INSTALL_WINDOWS.md
docs/release/INSTALL_LINUX.md
docs/release/KNOWN_LIMITATIONS.md
docs/release/TESTER_FEEDBACK.md
Release notes must contain
What BetterFingers does

A short description of:

Speak → transcribe locally → rewrite locally → review → place text
Qualified platforms

List exact versions and desktop sessions.

Experimental platforms

State clearly that Wayland is experimental.

Windows signing status

If unsigned:

This alpha installer is not Authenticode-signed and may trigger Microsoft SmartScreen. Verify the provided SHA-256 checksum before installation. Do not disable Windows security software.

Code signing is helpful, but it does not need to block a small trusted alpha because the existing workflow already creates an explicit signature-status report.

Privacy disclosure

Explain that:

Processing is local.
Model downloads require network access.
Raw recordings are retained for recovery.
The privacy screen can wipe stored data.
At-rest encryption is not yet implemented.
Testers should avoid dictating highly sensitive information during the alpha.

The README already distinguishes local processing from future optional at-rest encryption. Preserve that honesty.

Known limitations

Include:

No auto-update
Manual upgrade required
Wayland experimental
Some target applications unqualified
Windows installer may be unsigned
Voice-cloning synthesis unavailable
Model downloads can be large
Local models require meaningful RAM and CPU/GPU resources
Install instructions

Keep the process to:

Download
Verify checksum
Install or mark executable
Launch
Download recommended models
Dictate
Submit bugs
Feedback template
BetterFingers version:
Artifact filename:
Operating system:
Linux session type:
CPU:
RAM:
GPU:
Microphone:
Whisper model:
LLM model/runtime:

What I did:
What I expected:
What happened:
Can I reproduce it:
Did any recording or draft get lost:
Did BetterFingers send text automatically:

Support report attached:
Screenshot attached:

Warn testers not to attach private recordings or sensitive text to public GitHub issues.

Publication
Phase 12: Create and publish the prerelease

After exact-tag qualification passes:

Approve the GitHub release environment.
Let the workflow create the draft prerelease.
Inspect the draft.
Replace the generated placeholder text with the completed release notes.
Confirm Prerelease is enabled.
Confirm it is not marked latest.
Confirm every expected asset exists.
Publish.
Open the release page in a signed-out/incognito browser.
Download both platform packages from the public page.
Verify both checksum files once more.

The workflow is already configured to make a draft prerelease, not an immediately public release. It expects exactly one Windows installer, Windows checksum, signature report, Linux AppImage, Linux checksum, and CycloneDX SBOM.

Required release assets
BetterFingers-<version>-Setup.exe
BetterFingers-<version>-Setup.exe.sha256
BetterFingers-<version>-Setup.exe.signature.txt

BetterFingers-<version>.AppImage
BetterFingers-<version>.AppImage.sha256

betterfingers-sbom.cdx.json

Also confirm the tag-generated provenance attestations exist.

GitHub Pages, a promotional website, and Devpost are not blockers. The GitHub prerelease page is sufficient for sharing with trusted testers. A website can wait until the software has endured contact with humans.

Tester rollout
Phase 13: Release in rings
Ring 0: Qualification group

Use:

You
One separate Windows tester
One separate Linux X11 tester

They test before broad sharing.

Ring 1: Trusted alpha

Share with approximately 5 to 10 people who understand:

It is an alpha
It may break
They should report failures
They should not use it for critical or sensitive work
Ring 2: Wider personal circle

Expand only after Ring 1 has completed several normal sessions without:

Lost audio
Automatic sends
Installation failures
Model corruption
Repeated startup failures
Patch policy
Critical data-loss or unintended-send bug: pull the release or add a prominent warning immediately
Platform-specific breakage: update known limitations
Fixes: publish alpha.2, alpha.3, and so forth
Never silently replace alpha.1 assets
Hard definition of done

BetterFingers is ready to share as a full alpha when every box below is checked:

 Alpha scope is frozen
 Unsupported features are hidden or labeled
 Old 0.2.0-alpha.1 evidence is archived
 Operator QA documentation names 1.1.0-alpha.1
 Required CI is green
 Final branch artifacts pass prequalification
 PR #94 is merged
 Exact release tag is created
 Tag workflow builds Windows and Linux packages
 Tag-generated hashes are recorded
 Windows clean-machine qualification passes
 Linux X11 clean-machine qualification passes
 Real model installation and cache rediscovery pass
 Windows injection matrix is recorded
 Linux injection matrix is recorded
 100 real dictations pass or recover
 50 restart cycles pass
 Long recordings pass
 Microphone disconnect/reconnect passes
 Sleep/resume passes
 Clipboard restoration passes
 Zero unintended sends occur
 Zero recordings are lost
 Privacy wipe is verified
 Signing status is disclosed
 Release notes and installation guides are complete
 Draft prerelease contains all expected assets
 Public download works while signed out
 One feedback channel is ready
Recommended ticket board

Create these as the final release tickets, in this order:

Ticket	Task
ALPHA-01	Freeze supported-platform and feature scope
ALPHA-02	Archive stale 0.2.0-alpha.1 evidence
ALPHA-03	Refresh operator QA and release documentation
ALPHA-04	Add manual reliability-result import
ALPHA-05	Finish current CI and freeze candidate source
ALPHA-06	Build final branch artifacts
ALPHA-07	Prequalify Windows branch artifact
ALPHA-08	Prequalify Linux X11 branch artifact
ALPHA-09	Merge PR #94 and create release tag
ALPHA-10	Qualify exact Windows tag artifact
ALPHA-11	Qualify exact Linux tag artifact
ALPHA-12	Complete Windows injection matrix
ALPHA-13	Complete Linux injection matrix
ALPHA-14	Complete 100-dictation and restart reliability run
ALPHA-15	Finalize release notes, install guides, and feedback template
ALPHA-16	Approve draft creation and verify release assets
ALPHA-17	Publish prerelease and begin Ring 0/Ring 1 testing

The shortest honest path is therefore:

freeze scope → clean evidence → finish CI → prequalify branch packages → merge → tag → qualify exact tag packages → publish prerelease → share one GitHub link.