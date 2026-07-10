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

BetterFingers runs inference locally. The only intended outbound network traffic is
model/runtime downloads the user initiates. If you observe any other outbound connection,
that is a reportable issue. See [DESIGN.md §9](DESIGN.md) for the data-lifecycle and
supply-chain model.
