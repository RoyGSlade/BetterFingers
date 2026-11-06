# Security Policy

BetterFingers is a local-first application: speech, transcripts, drafts, and recordings
are among the most sensitive data on a user's machine. We take reports seriously.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Report privately through one of:

- GitHub's **[private vulnerability reporting](https://github.com/RoyGSlade/BetterFingers/security/advisories/new)**
  (Security tab → "Report a vulnerability"), or
- email the maintainer at **donavencrenshaw@gmail.com** with `BetterFingers security` in
  the subject.

Please include: affected version/commit, platform, a description of the issue, and
reproduction steps or a proof of concept. If your report involves a captured recording or
transcript, redact any real personal content before sending it.

We aim to acknowledge reports within a few days. As a solo-maintained project, fix
timelines are best-effort; we will keep you updated and credit you in the release notes
unless you prefer to remain anonymous.

## Scope

In scope — issues in this repository, for example:
- Local privilege or sandbox-escape via the Electron shell, sidecar, or IPC boundary.
- Leakage of user speech/transcripts/recordings to disk, logs, diagnostics, or the network
  beyond what the privacy model documents.
- The privacy wipe failing to remove data it reports as removed.
- Auth-token handling on the local REST/WebSocket boundary.
- Unverified model/binary download or path-traversal in model management.

Out of scope:
- Vulnerabilities in third-party model weights or upstream runtimes (report those
  upstream), though we want to know if BetterFingers uses them unsafely.
- Attacks requiring an already-compromised machine or physical access.
- Missing hardening that is already tracked on the roadmap in [DESIGN.md](DESIGN.md)
  (e.g. at-rest encryption, code signing) — a heads-up is welcome, but these are known.

## Data & network posture

BetterFingers runs inference locally. Intended outbound traffic is limited to model/runtime
downloads the user initiates, update checks against the project's public GitHub Releases
channel (none before the user accepts the privacy notice; automatic checks are off on a fresh
install until the user turns them on; a manual "Check for updates" works after consent),
and a bug report the user explicitly prepares, reviews, consents to, and confirms through a
configured HTTPS support relay. Without that relay, bug reporting
only copies the reviewed report and opens the user's email client or Discord; the app does not
claim delivery. Any other outbound connection is a reportable issue. See [DESIGN.md §9](DESIGN.md)
for the data-lifecycle and supply-chain model, and [docs/BUG_REPORTING.md](docs/BUG_REPORTING.md)
for the bug-report privacy boundary and relay contract.

## Local trust boundaries

What the app enforces on the machine itself (details in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)):

- **A person's yes is a native dialog, not a request field.** Approving a workflow, changing a
  persona's examples and placing a draft into another application each need a short-lived,
  single-use ticket that only the Electron main process can sign, and only after a native dialog
  showed the exact, complete content and the person clicked the approving button. The signing key
  is held by the main process and the backend it spawns; renderers never see it, and the backend
  refuses approvals without it. A spoken phrase, a request flag or a model's text is never an
  approval. **Everything fails closed**: if the content cannot be fetched, verified or shown,
  nothing is approved.
- **A dialog that cannot show everything offers no way to approve.** Every approval dialog has a
  line budget (26 lines, fewer on a short screen) and a character budget (1600 characters, with a
  short headline), counted on exactly what would be shown. Lines are wrapped by their estimated
  rendered width so the toolkit never wraps them again; the budgets were measured by opening the
  real dialog under a virtual display at 1920x1080, 1366x768 and 1280x720
  (`app/tests/nativeDialogXvfb.test.mjs`). Anything over either budget gets a dialog with a single
  Close button that says it is too long to show in full and where to read it (the review window
  for a draft, the Workflows page, the persona editor); nothing is signed. Long lines are wrapped,
  never cut, and invisible characters are shown as `<U+XXXX>`.
- **Every workflow run is confirmed, and runs only what was shown.** Approving a workflow and
  running it are separate acts. Every run, whoever asks (a page, a Stream Deck key, a controller)
  and whatever it does, opens a native dialog first; there is no dialog-free run path. If the
  backend cannot describe the run, the preview does not verify, the workflow is not runnable right
  now (not approved, switched off, changed) or a target cannot be resolved, nothing is shown and
  nothing runs, and enabling it afterwards cannot rescue that answer. The click yields a
  single-use run authorization bound to the exact plan and to the launch targets resolved at that
  moment (the program and its argument list, each link, each folder), which the dialog names. The
  executor runs only those frozen targets and stops if a confirmed application changes before its
  step. Replacing a confirmed application's entry also needs a native dialog showing before and
  after. The send shortcut never places text by itself: a press opens the native dialog showing
  the draft main fetched from the backend, and only Ctrl/Alt/Meta chords or function keys are
  accepted as that shortcut.
- **Persona examples change only with a tap, and the whole list is what is approved.** Any change
  to a persona's few-shot list (an addition, an edit, a removal, a reordering, a repeated copy,
  emptying it) is shown as a before/after diff of the complete resulting list and signed against
  the list before and after; deleting one learned example needs the same. Clearing all learned
  examples is a privacy wipe with its own explicit confirmation, not an example edit.
- **Voice only requests.** "Send it" opens the same native dialog as a click on Place; nothing
  spoken confirms anything, and there is no voice-confirmation flow. Spoken commands that would
  need a confirmation are refused.
- **Clipboard (policy).** Copying a draft to the clipboard (`copy_only`) and the page's clipboard
  write channel need no dialog. They put text on this machine's clipboard and send nothing to
  another application or over the network; any onward use is a paste the person makes. This is a
  deliberate exception to the dialog rule, not an oversight. A placement into another application
  (paste, type, open the chat and send) always needs the dialog.
- **The local API accepts only loopback Host headers and no foreign browser Origin**, and every
  call needs the bearer token. The token is never printed, never in a URL, and is masked in logs.
- **llama-server runs with a per-run API key**, no web UI, no slots endpoint, loopback only.
- **Each window has its own minimal preload and a strict CSP**; the overlay and the splash cannot
  call workflow, draft, privacy or file channels. Web permissions (camera, screen, clipboard,
  location) are denied; the microphone is allowed only for the dashboard's own recorder.
- **MCP servers are untrusted by default and start only confined.** The backend's own
  credentials are never in its environment (the shell hands them over a pipe), and on Linux the
  backend makes itself non-dumpable BEFORE it reads them; if it cannot, it exits rather than hold
  them. An MCP server gets an allowlisted environment and, on Linux, the required confinement:
  bubblewrap, with its own PID/IPC/UTS namespaces, no new privileges, no capabilities, a read-only
  filesystem, empty stand-ins for the app's data folder and `~/.ssh`, `~/.gnupg`, `~/.aws`,
  `~/.kube`, `~/.config/gcloud`, the whole `$XDG_RUNTIME_DIR` masked (D-Bus session bus, Wayland,
  PipeWire), the X11 socket directory and X authority files masked, the system bus masked, and
  `--die-with-parent`. The network stays on unless the server's entry says `"network": false`.
  **If that confinement cannot be established** (no usable bubblewrap, Windows, macOS, or an entry
  with `"sandbox": "off"`), **the server is refused** with an error saying why, unless the owner
  has marked it "trusted on this machine" in a native dialog that shows its exact configuration.
  That consent is bound to a digest of the configuration (any change voids it), stored in
  `mcp_trust.json` (declared in the privacy inventory; removed by a personal-data wipe and a factory
  reset), and can be withdrawn at any time. A trusted server runs with the weaker confinement the
  machine has: no-new-privs on Linux, **nothing on Windows and macOS**, where it runs with your own
  rights. Known limit: with the network on, a confined server shares the host network namespace,
  so abstract-namespace sockets (such as an X server's `@/tmp/.X11-unix/X0`) stay reachable; the X
  authority files are masked, which defeats cookie authentication, and `"network": false` closes
  it entirely. The backend's environment route for credentials (`python server.py` with
  `BETTERFINGERS_AUTH_TOKEN`) is for development only and is not hardened.
