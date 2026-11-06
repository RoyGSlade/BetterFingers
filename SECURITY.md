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

- **A person's yes is a native dialog, not a request field.** Approving a workflow, teaching a
  persona an example and placing a draft into another application each need a short-lived,
  single-use ticket that only the Electron main process can sign, and only after a native dialog
  showed the exact, complete content and the person clicked Approve. The signing key is held by
  the main process and the backend it spawns; renderers never see it, and the backend refuses
  approvals without it. A spoken phrase, a request flag or a model's text is never an approval.
- **The local API accepts only loopback Host headers and no foreign browser Origin**, and every
  call needs the bearer token. The token is never printed, never in a URL, and is masked in logs.
- **llama-server runs with a per-run API key**, no web UI, no slots endpoint, loopback only.
- **Each window has its own minimal preload and a strict CSP**; the overlay and the splash cannot
  call workflow, draft, privacy or file channels. Web permissions (camera, screen, clipboard,
  location) are denied; the microphone is allowed only for the dashboard's own recorder.
- **MCP servers get an allowlisted environment** with none of the app's credentials.
